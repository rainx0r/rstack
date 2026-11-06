#!/usr/bin/env bash
#
# Watch a Slurm job on Isambard and exit as soon as it needs attention. The job can be
# an array, or a whole-node allocation that runs its tasks as srun steps.
#
# Usage: watcher.sh INTERVAL_SECONDS JOB_ID JOB_NAME SSH_HOST LOG_DIR [STATE_DIR]
#
#   INTERVAL_SECONDS  Seconds to wait between checks.
#   JOB_ID            Slurm job ID of the array or allocation.
#   JOB_NAME          Slurm job name. Logs must be named JOB_NAME-JOB_ID.out or
#                     JOB_NAME-JOB_ID_<suffix>.out.
#   SSH_HOST          ssh host of the cluster.
#   LOG_DIR           Absolute path of the task log directory on the cluster.
#   STATE_DIR         Local directory that records what has already been reported.
#                     Defaults to ~/.cache/rstack/watcher/isambard/JOB_ID.
#
# Exit codes:
#   0  Every task reached a terminal state.
#   1  Wrong arguments.
#   2  The cluster is unreachable over ssh (e.g. an expired clifton cert). Watchers share
#      an outage marker, so only one of them exits. The rest wait for ssh to recover.
#   3  New error lines in the task logs.
#   4  A task entered a failure state.
#   5  Three consecutive failed sacct queries (e.g. a wrong JOB_ID).
#   6  An hour has passed without another exit, so it's time to check on the job.

# Arguments
if [[ $# -lt 5 || $# -gt 6 ]]; then
  echo "Usage: watcher.sh INTERVAL_SECONDS JOB_ID JOB_NAME SSH_HOST LOG_DIR [STATE_DIR]" >&2
  exit 1
fi

interval=$1
job_id=$2
job_name=$3
ssh_host=$4
log_dir=$5
state_dir=${6:-$HOME/.cache/rstack/watcher/isambard/$job_id}

# Settings
max_query_failures=3
check_in_seconds=3600
outage_file=$HOME/.cache/rstack/isambard/outage
outage_report_minutes=360
log_error_pattern='Traceback|Error|CUDA error|OutOfMemory|out of memory|Killed|nan'
log_noise_pattern='Profiler record function|[: ]wandb: '
failed_states='FAILED|TIMEOUT|OUT_OF_MEMORY|NODE_FAIL|CANCELLED[^|]*|PREEMPTED|BOOT_FAIL|DEADLINE'
active_states='PENDING|RUNNING|REQUEUED|CONFIGURING|COMPLETING'

# Records of what has been reported, so a restart only reports new events
mkdir -p "$state_dir"
seen_errors_file=$state_dir/seen-errors-$job_id.txt
seen_failures_file=$state_dir/seen-failures-$job_id.txt
touch "$seen_errors_file" "$seen_failures_file"

# Print a line prefixed with the current time
log() {
  echo "$(date '+%F %T') $1"
}

# Print the lines of $2 that are not already recorded in the file $1
unseen_lines() {
  local seen_file=$1
  local lines=$2
  grep -vxFf "$seen_file" <<<"$lines" | sed '/^$/d'
}

# Succeed if this watcher is the one to report the current outage. Creating the marker
# is atomic, so only one watcher wins. An old marker expires in case its report was missed.
claim_outage_report() {
  mkdir -p "$(dirname "$outage_file")"
  find "$outage_file" -mmin +"$outage_report_minutes" -delete 2>/dev/null
  (set -o noclobber; : >"$outage_file") 2>/dev/null
}

# Fetch task states, pending tasks and matching log lines in a single ssh call.
# Returns 255 if ssh can't reach the cluster, and 1 if sacct fails or knows no tasks.
# squeue errors are ignored because it rejects a job that has left the queue, and sacct
# still has the job's state.
query_cluster() {
  local response
  response=$(ssh -o BatchMode=yes -o ConnectTimeout=30 "$ssh_host" "
    sacct -n -P -j $job_id --format=JobID,JobName,State,Elapsed,NodeList || exit 1
    echo '--PENDING--'
    squeue -r -j $job_id -h -t PD -o '%i %R' 2>/dev/null
    echo '--ERR--'
    grep -HnE '$log_error_pattern' '$log_dir'/${job_name}-${job_id}.out '$log_dir'/${job_name}-${job_id}_*.out 2>/dev/null \
      | grep -vE '$log_noise_pattern' \
      | head -40
  ") || return $?
  [[ $response != --PENDING--* ]] || return 1
  echo "$response"
}

query_failures=0

while true; do
  response=$(query_cluster)
  query_status=$?

  # Any answer from the cluster ends an outage
  if [[ $query_status -ne 255 ]]; then
    rm -f "$outage_file"
  fi

  # Retry failed queries. After too many in a row, exit if the cluster answered,
  # since waiting won't fix that. If it's unreachable, report it once and keep waiting.
  if [[ $query_status -ne 0 ]]; then
    query_failures=$((query_failures + 1))
    log "query failed ($query_failures)"
    if [[ $query_failures -ge $max_query_failures ]]; then
      if [[ $query_status -ne 255 ]]; then
        echo QUERY_FAILED
        exit 5
      fi
      if claim_outage_report; then
        echo CLUSTER_UNREACHABLE
        exit 2
      fi
    fi
    sleep "$interval"
    continue
  fi
  query_failures=0

  # Split the response into its three sections. Task states keep the allocation and srun
  # rows, since a failed step can sit inside an allocation that still reports COMPLETED.
  task_states=$(sed '/--PENDING--/,$d' <<<"$response" | grep -vE '^[^|]*\.(batch|extern)\|')
  pending_tasks=$(sed -n '/--PENDING--/,/--ERR--/p' <<<"$response" | sed '1d;$d')
  error_lines=$(sed -n '/--ERR--/,$p' <<<"$response" | tail -n +2)

  # Exit on log errors we haven't reported yet
  new_errors=$(unseen_lines "$seen_errors_file" "$error_lines")
  if [[ -n $new_errors ]]; then
    echo "$new_errors" >>"$seen_errors_file"
    log "LOG_ERRORS:"
    echo "$new_errors"
    echo "$task_states"
    exit 3
  fi

  # Exit on task failures we haven't reported yet
  failed_tasks=$(grep -E "\|($failed_states)\|" <<<"$task_states" | cut -d'|' -f1,3)
  new_failures=$(unseen_lines "$seen_failures_file" "$failed_tasks")
  if [[ -n $new_failures ]]; then
    echo "$new_failures" >>"$seen_failures_file"
    log "TASK_FAILED:"
    echo "$new_failures"
    echo "$task_states"
    exit 4
  fi

  # Exit once no task is pending or active
  if [[ -z $pending_tasks ]] && ! grep -qE "\|($active_states)\|" <<<"$task_states"; then
    log "ALL_TERMINAL:"
    echo "$task_states"
    exit 0
  fi

  # Exit for a check-in once nothing else needs attention
  if [[ $SECONDS -ge $check_in_seconds ]]; then
    log "CHECK_IN:"
    echo "$task_states"
    if [[ -n $pending_tasks ]]; then
      echo "$pending_tasks"
    fi
    exit 6
  fi

  # Otherwise print a one-line status and wait for the next check
  state_counts=$(cut -d'|' -f3 <<<"$task_states" | sort | uniq -c | tr -s ' ' | tr '\n' ',')
  pending_count=$(sed '/^$/d' <<<"$pending_tasks" | wc -l | tr -d ' ')
  log "ok: $state_counts pending=$pending_count"
  sleep "$interval"
done
