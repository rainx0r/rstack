---
name: design-experiment
description: Design an experiment. Gather context, sharpen the user's hypothesis, create the experiment entrypoint, and create hand-off for rstack:run-experiment. Use for /design-experiment, 'design an experiment to', or when the user says they want to perform an experiment.
---

# design-experiment

Help the user design an experiment within the context of a given project. This should help streamline going from a vague experiment idea to something to actually run and gain information from.

Workflow:

1. Gather context
2. Sketch and sharpen the hypothesis or question
3. Align with the user
4. Implement
5. Hand-off

## Gather context

Read the project's `AGENTS.md` and `EXPERIMENTS.md` files, if either exist, for context and guidance on running experiments within the context of this project.

If neither exist, or they do not contain sufficient information regarding baselines, evaluation metrics, general set-up (e.g. tasks, datasets, number of seeds), or how runs are compared to each other, load the `rstack:create-experiment-playbook` skill and follow it to add this context to the project before continuing.

## Sketch and sharpen the hypothesis or question

Identify what the baseline is and what results already exist for it, and whether they're still valid. What are we comparing to, on which metric(s), and do those results still count if we have them?

Search for hidden changes, e.g. changes in parameter count or hyperparameters that should likely be reconsidered given the changes the experiment calls for. Take note of what stays invariant and drives the comparison, and what changes.

Identify what the primary figure for the experiment should be. This is driven by which result arriving from the experiment would affect subsequent experiments the most, and also the project's research goals more generally.

### Special cases

If the user asks for a study, the sharp version of the research question is a grid of runs and what might be learnt from it.

If the user only listed a vague problem (e.g. "resolve training instability" or "reduce variance"), then diagnose existing runs and the sharp version would be a list of ranked hypotheses and a proposed first experiment.

## Align with the user

Concisely deliver the aforementioned sharpened hypothesis or research question to the user. Make it clear what the code changes will include to implement it, what the baseline will be and whether fresh baseline results are needed, what final figure(s) would be, and any hidden changes you found that the user should consider.

If the user provides feedback, move back to the sketching stage.

If you were unable to come up with a sharp version of the research question or hypothesis, interview the user to provide additional info.

## Implement

Implement the agreed upon experiment setup, keeping code changes minimal. Experiments should always be implemented in a new branch prefixed `exp/` (unless instructed totherwise by the user or other skills).

Additionally implement an experiment entrypoint file, or multiple if necessary. This file should provide the interface necessary to actually run the experiment. This includes:

- [ ] Checkpoint and resume functionality (if applicable).
- [ ] Configurable wandb run name / entity / group / mode.
- [ ] Configurable seed.
- [ ] Configurable checkpoint and cahe paths (if applicable).
- [ ] Logs for a throughput metric, and configurable total number of steps.

The project entrypoint's code should be largely self-explanatory, but also include a comment near the top of the file that concisely describes the research question or hypothesis and how it should be run.

## Hand-off

After implementation is complete, commit the changes to the branch, and write a concise hand-off message the user can pass on to an agent to run the experiment. This message should include a concise description of the experiments to run, the goal of the experiment, and which experiment entrypoint(s) to use.
