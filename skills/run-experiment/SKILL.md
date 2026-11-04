---
name: run-experiment
description: Run an experiment. Fetch related playbooks, run the experiment on the specified compute resource, ensure results are logged to wandb properly, and stay in the loop to manage the experiment lifecycle. Use for /run-experiment, 'run an experiment to', or when an experiment has been designed or a very clear hypothesis has been formed that requires experiments on compute resources to verify.
---

# run-experiment

Workflow:

1. Align with the user before running the experiment
2. Load related compute skills
3. Decide on logging strategy
4. Manage experiment lifecycle

## Align with the user before running the experiment

Running an experiment depends on already having a very clear hypothesis to test, and code to run. If neither are clear (e.g. skill was invoked with a very vague prompt), defer the user to the `rstack:design-experiment` skill and do not run the experiment.

As a quick sanity check, before starting the experiment, restate in your own words what you think the experiment setup, assumptions and hypothesis are, and ask for approval from the user to go through with the rest of the process.

Tell the user which compute resource you intend to use. If the user did not explicitly specify which compute to use, and it is not trivially inferrable from surrounding context (e.g. previous skill invocations in the same thread), ask.

## Load related compute skills

Usually experiments will not run on the same machine that you are running on because they need capable GPU resources.

In order to conduct the experiment, you will need to load the skill for the relevant compute resource. These skills all follow a standardised naming scheme in the plugin: `rstack:use-$COMPUTE` (e.g. `use-isambard`).

## Decide on logging strategy

Debug runs should not log to wandb (wandb mode: disabled). Every other run should. Ensure wandb logging can work from the specified compute resource, else abort the experiment as retrieving and visualising the results might not be reliable.

Infer wandb entity and project from context. If unclear, ask the user. Add runs to a group that clearly marks the experiment. Make sure each run has a name that clearly differentiates it, following repository and existing wandb project conventions as much as possible. Avoid adding timestamps or other unique identifiers to the run name, except seed number.

## Manage experiment lifecycle

Once runs are submitted, you own them until every run is in a terminal state and its results are confirmed in wandb. The compute skill has the mechanics: how to submit, query job state and find logs, and usually a watcher script. The rules below apply on any compute.

### Launch

Give every run its own run name and checkpoint directory, so runs can't collide or resume from each other.
Never change code or config that a running or queued run launches from. Ship a fix or a variant as its own copy.

As soon as the first runs start, confirm from their logs that they loaded the intended code and config, and that they appear in wandb under the expected group.

### Watch

Run the compute skill's watcher in the background. Do not poll in short foreground loops. It should exit only when something needs your attention, with a distinct reason for each case:

| Exit reason | Meaning |
|---|---|
| Log errors | New matching lines in run logs: tracebacks, out of memory, NaNs, killed processes |
| Run failed | A run entered a failure state: failed, timed out, preempted, cancelled |
| All terminal | Every run has finished, one way or another |
| Lost access | Several consecutive failures to reach the compute resource |

A watcher must also:

- Remember what it has reported.
- Filter known noise out of log matches.
- Treat a failed query as a failure. A watcher that can't tell "nothing happened" from "couldn't check" looks healthy while nothing is running.

After every exit, read the output, act on it, and restart the watcher for whatever is still running. If access was lost because credentials expired, ask the user to renew them and stop.

If the compute skill has no watcher, write one to these rules for this experiment and propose adding it to that skill.

### Respond to failures

1. Read the log of the failed run and find the cause.
2. Fix the cause in a copy of the code or job script. Running runs must keep what they launched with.
3. Decide how to restart. If the run has a useful checkpoint, resume it into the same wandb run. Otherwise, clear the partial state and start fresh.
4. Rerun only the affected runs, and restart the watcher.
5. Note any stub wandb runs the failed attempt left behind, for cleanup later.
6. Tell the user in a few lines what failed, why, what you changed and what's still running.

Stop and ask before applying a fix that changes what the experiment measures, or that would make finished runs incomparable with the rest, unless the user has explicitly requested unsupervised experiment running for a given amount of time (e.g. overnight runs).

### Finish

When every run is terminal:

1. Confirm in wandb that every planned run finished, comparing the count against the plan.
2. Delete stub runs from failed or cancelled attempts. Select them by group and state, and check the count before deleting. If you can't delete them, list their IDs for the user.
3. Report back. List what failed and was rerun, the wandb group, and any leftovers on the compute resource.

