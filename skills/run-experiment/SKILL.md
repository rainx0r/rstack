---
name: run-experiment
description: Run an experiment. Gather context, sanity check the setup, plan the runs and logging, give the user a rundown, load the relevant compute skill to run it, and confirm the results in wandb. Use for /run-experiment, 'run an experiment to', or when the user asks to run an experiment on a compute resource.
---

# run-experiment

This skill decides what runs and checks what came back. The compute skill decides how and where it runs.

Workflow:

1. Check the experiment setup
2. Load related compute skills
3. Plan the runs
4. Give the user a rundown
5. Run the experiment
6. Close out

## Check the experiment setup

Running an experiment depends on already having a very clear hypothesis to test or question to answer, and code to run. If neither are clear (e.g. skill was invoked with a very vague prompt and no experiment entrypoint exists), defer the user to the `rstack:design-experiment` skill and do not run the experiment.

Also check the project's `AGENTS.md`, or `EXPERIMENTS.md`, if either file exists, for additional context and instructions, e.g. fany experiment trackers to update or where to describe the final results.

If the user did not explicitly specify which compute to use, and it is not trivially inferrable from surrounding context (e.g. previous skill invocations in the same thread), ask.

## Load related compute skills

Usually experiments will not run on the same machine that you are running on because they need capable GPU resources.

In order to conduct the experiment, you will need to load the skill for the relevant compute resource. These skills all follow a standardised naming scheme in the plugin: `rstack:use-$COMPUTE` (e.g. `use-isambard`).

## Plan the runs

Debug runs should not log to wandb (wandb mode: disabled). Every other run should.

Infer wandb entity and project from context. If unclear, ask the user. Add runs to a group that clearly marks the experiment. Make sure each run has a name that clearly differentiates it, following repository and existing wandb project conventions as much as possible. Avoid adding timestamps or other unique identifiers to the run name, except seed number.

Give every run its own run name and checkpoint / logging directories in the compute resource's storage, so runs can't collide or resume from each other. Note how many runs you plan to start, since you'll check the count at the end.

## Give the user a rundown

Before using any compute, restate in your own words what you think the experiment setup, assumptions and hypothesis are. Tell the user which compute resource you intend to use, which runs you plan to start (how many, their names and the wandb group), and what will happen next. Ask for approval from the user to go through with the rest of the process.

Measuring runtime can take a while, so don't wait for an estimate before asking. If the compute skill produces one, share it just before queueing.

## Run the experiment

Follow the compute skill to launch and watch the runs. Once runs are submitted, you own them until every run is in a terminal state and its results are confirmed in wandb.

Never change code or config that a running or queued run launches from. Ship a fix or a variant as its own copy.

As soon as the first runs start, confirm from their logs that they loaded the intended code and config, and that they appear in wandb under the expected group.

Stop and ask before applying a fix that changes what the experiment measures, or that would make finished runs incomparable with the rest, unless the user has explicitly requested unsupervised experiment running for a given amount of time (e.g. overnight runs).

## Close out

When every run is terminal:

1. Confirm in wandb that every planned run finished, comparing the count against the plan.
2. Delete stub runs from failed or cancelled attempts. Select them by group and state, and check the count before deleting. If you can't delete them, list their IDs for the user.
3. Report back. List what failed and was rerun, the wandb group, and any leftovers on the compute resource.
