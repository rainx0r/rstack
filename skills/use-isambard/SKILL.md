---
name: use-isambard
description: Use the Isambard AI Phase 2 compute cluster. Use for /use-isambard, 'use the isambard cluster to', 'run this on isambard' or when running experiments on Isambard.
---

# use-isambard

The Isambard AI Phase 2 cluster has 4 GH200 GPUs and 72 ARM CPUs per node.

## Queueing jobs

Never request an allocation of more than 24 hours for any given job. Treat this value as MAX_TIME.

The user account can use up to 32 GH200s at any given time without further authorisation. However more GPUs may be allocated if the user explicitly asked for it (e.g. because the project has been granted permission to use more compute). Treat this value as MAX_GPUS.

### Checklist

Before queueing:

- [ ] Checked the user is logged in to wandb on the login node, if the runs log to wandb
- [ ] Estimated the runtime using `rstack:estimate-runtime` in an interactive job if not cached, and released the allocation
- [ ] Time limit includes slack and is within MAX_TIME
- [ ] Chose between an array job and whole nodes with `srun`
- [ ] Requested > 1 CPUs per GPU for runs that need CPU compute, and adjusted settings to use them
- [ ] Array jobs use the `%` operator
- [ ] Checked `squeue --me`, and the jobs stay within MAX_GPUS, with dependencies added if necessary
- [ ] Code is staged in $HOME, with artifacts and caches on $SCRATCHDIR and $PROJECTDIR
- [ ] Whole-node jobs launch their `srun` steps from the `sbatch` script
- [ ] Logs follow the naming the watcher expects (`#SBATCH --output=<log_dir>/%x-%A_%a.out` for array jobs, `srun --output=<log_dir>/<job_name>-%j_<run_name>.out` for `srun` steps)

After queueing:

- [ ] Started a watcher in the background for each job
- [ ] Restarted the watcher after handling each exit, if any tasks are still running
- [ ] Checked task states and wandb before calling it done

### GPU / CPU resource allocation

For small numbers of runs (< MAX_GPUS), and when all the runs have a relatively high runtime (more than 1.5 hours), queue it as an array job. Otherwise, it might make more sense to request whole nodes and then execute each run using an `srun` command to amortise allocation/compilation and other such overheads.

For whole-node jobs, launch each run as an `srun --exact` step from the `sbatch` script, so steps don't block each other. Never launch steps from a login node, as they die when the ssh session ends. Give each step its own log with `--output=<log_dir>/<job_name>-%j_<run_name>.out`.

When queueing array jobs using slurm, always use the `%` operator to limit the maximum number of GPUs being allocated. Also check for any other queued or running jobs (`squeue --me`) and, if necessary, add a job dependency to never allocate more than MAX_GPUS jobs.

For runs that require CPU compute (e.g. RL experiments where the environment runs on CPU, or multithreaded/processed data loaders), always request 72 CPUs per GPU and adjust any CLI arguments and environment variables to make use of the extra processors to accelerate the run. Note that sometimes it makes sense to adjust these variables to a count lower than 72, (e.g. 64 to evenly divide number of parallel environments in RL), in which case go for it but make the decision transparent to the user.

### Fit the run within the time limit

If the run would require more than MAX_TIME based on the runtime estimate, ensure that checkpoint / resume code exists and would allow the run to resume from where it would terminate within that period. Run it with a reduced number of steps to fit within the time limit, but make sure things like learning rate schedules are compatible with the full run duration after resumption. Warn the user, and if it's not possible for the run to be split into multiple jobs, stop.

### Interactive jobs

Interactive jobs tend to be allocated much faster, or in most cases instantly. This makes them extremely useful for running steady-state throughput tests before queueing jobs to estimate their runtime, or testing a bug fix. Always use them for this purpose, or more generally when doing dev-related tasks, over normal, non-interactive queued jobs.

Always make sure to release the allocation as soon as you're done using it. Never allocate an interactive job with more than MAX_GPUS gpus.

### Storage

Use $HOME for staging code.

Use $SCRATCHDIR for all intermediate research artifacts (e.g. intermediate checkpoints and offline wandb logs) and temporary caches (e.g. torch, xla, triton, etc. caches).

For longer lived research artifacts or data, use `$PROJECTDIR/<user.isambard_project>/<project>`. Stage run-specific data, e.g. final and best checkpoints, into `$PROJECTDIR/<user.isambard_project>/<project>/<run_name>`. Also use the project directory for any datasets, model weights and any other general purpose data that is not part of the code.

If it's not possible to specify paths for run artifacts and caches as command line arguments or environment variables, ask the user to implement them and stop.

## Watcher

Use [`watcher.sh`](scripts/watcher.sh) to watch array jobs and whole-node jobs. It runs on your machine and checks on the job over ssh. It only exits when there's a new event to respond to, or for an hourly check-in. Run it in the background per job, using its path relative to this skill's folder:

```sh
scripts/watcher.sh 300 <job_id> <job_name> <ssh_host> <log_dir>
```

Before running it, discover `<ssh_host>` from the user's ssh config (`~/.ssh/config` and anything it includes). It looks like `<user.isambard_project>.aip2.isambard`. If there's no clear match, ask the user. Make sure `<log_dir>` is an absolute path.

The exit code tells you why it stopped:

| Exit code | Description |
|---|---|
| 0 | Every task reached a terminal state |
| 1 | Wrong arguments |
| 2 | The cluster is unreachable over ssh |
| 3 | New error lines in the task logs |
| 4 | A task entered a failure state |
| 5 | 3 consecutive failed `sacct` queries |
| 6 | Hourly check-in |

After handling an exit, restart the watcher with the same arguments if any tasks are still running. It only reports events it hasn't reported before.

On exit 2, read the error output. If ssh says `Permission denied (publickey)`, the clifton certificate has expired: ask the user to run `clifton auth`. Otherwise it's likely a transient ssh issue, so don't message the user. Either way, restart the watcher straight away and end your turn. It can come back after 6 hours if ssh still hasn't recovered, so remind the user if so.

On exit 5, check that the job ID is correct and that `sacct` works on the cluster. On exits 3 and 4, attempt to fix the job, informing the user as to what fixes you're deploying to handle the exit.

On exit 3, divergence can sometimes be the result itself. Only apply fixes like gradient clipping that change the experiment setup if instructed by other invoked skills, or the user. If you do end up applying such fixes, make sure it is abundantly clear to the user.

On exit 4, never rerun a cancelled task without asking. For OUT_OF_MEMORY, requesting more resources is fine, but do not change other settings unless explicitly instructed to do so from other skills or the user. Multiple TIMEOUT errors often indicate a wrong runtime estimate, in which case you should adjust the runtime request and potentially measure throughput again. If an `srun` step fails in a whole-node job, resubmit that run as a new job, since steps can't safely be added to a running allocation from outside.

On exit 6, nothing has failed. Check why any tasks are still pending, that the logs and wandb steps of running tasks have moved since the last check, and that throughput is on track against the runtime estimate to finish within the time limit. If everything looks fine, don't message the user. If a run looks stuck or won't finish in time, tell the user what you found. Either way, restart the watcher and end your turn.

When handling run failures, consider whether the failure might affect other jobs that have not errored yet. In that case do not patch runs one at a time, ship a more general fix and cancel/requeue jobs as appropriate.

Exit code 0 doesn't necessarily mean success, so always check task states and wandb before calling it done.
