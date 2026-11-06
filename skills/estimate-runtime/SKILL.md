---
name: estimate-runtime
description: Estimate how long an experiment will take by measuring its steady-state throughput. Use for /estimate-runtime, 'how long will this run take', 'measure the throughput', or before queueing a job that needs a time limit.
---

# estimate-runtime

Workflow:

1. Check for a cached measurement
2. Measure steady-state throughput
3. Estimate the total runtime
4. Cache the measurement

Runtime estimation should take up to one hour. Use the fastest way to get compute on the given resource. The compute skill says what that is.

If the skill was invoked without any clear compute target to measure the throughput on, let the user know and exit.

## Check for a cached measurement

Measurements are cached in `~/.cache/rstack/<project>/throughput.csv`. If a row matches the current commit, settings and hardware, reuse it instead of measuring again.

## Measure steady-state throughput

Read the experiment entrypoint file at least, and figure out what the throughput metric is and how to estimate the total experiment ETA from it. If there are no logged throughput metrics or instrumentation that facilitates this, edit the code but revert it for the actual run, and warn the user, recommending them to improve monitoring.

Make sure your measurement covers all code paths in the run (e.g. including evaluation / checkpointing) if possible. If this is not possible (e.g. the first evaluation is done hours into training), run a separate throughput test on just those code paths and combine it with the general measurement, taking into account the cadence or frequency of said code path.

One potential risk factor is when certain code paths do not have a fixed runtime length (e.g. evaluation time could vary with rollout length, which changes as the model improves or degrades). Identify whether this is the case, attempt to simulate the maximum possible runtime length of those code paths for the measurement, and warn the user.

## Estimate the total runtime

Estimating the runtime from the throughput depends on the job. Take compilation overhead into account as well. When requesting a time limit, add around 30 minutes of slack to the estimate.

## Cache the measurement

Add a row to the cache file with these columns:

| Column | Contents |
|---|---|
| `commit_id` | The commit that was measured |
| `settings` | Any settings relevant to throughput (e.g. batch size, number of environments, rollout size, number of gradient steps, model size) |
| `hardware` | The hardware and cluster used |
| `throughput` | The measured throughput, with its unit |
