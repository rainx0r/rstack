---
name: create-experiment-playbook
description: Create a project's experiment playbook from project context. Use for /create-experiment-playbook, 'create an experiment playbook', or 'initialise EXPERIMENTS.md'.
---

# create-experiment-playbook

Create an experiment playbook for the project: the document that records what the project is trying to achieve, how experiments are set up and run, and what the current baselines are.

## Output location

Write the playbook to `EXPERIMENTS.md` at the project root, unless the user specifies another location (e.g. append to `AGENTS.md`). If a playbook already exists (check `EXPERIMENTS.md` and `AGENTS.md`), extend it with the missing information.

## Gather context

Begin by looking for any experiment entrypoints in the project and model as much as you can off them and their similarities.

Next, check if the project uses wandb to log runs. If not, ask the user where they log. Attempt to locate runs from the project and read their configurations and list of metrics. Look for evaluation metrics and general training performance indicators (e.g. loss / episodic return) and attempt to find the best performing baseline with best final or intermediate values on these metrics. For wandb, do not use `scan_history()` since it's quite slow.

If you were unable to discover the relevant context, ask the user to provide it upfront. Also ask the user how they like to track experiment results and whether they have project notes anywhere on Obsidian / Notion or elsewhere. If no entrypoints are present in the repository, ask the user which format they prefer (e.g. Python files, shell scripts, etc).

If it is not clear what the research project is ultimately trying to achieve (its "North Star"), ask the user.

## Write the playbook

A good experiment playbook should have the following sections:

- North Star
- Tasks and setups
- Methodology (number of seeds, experiment length, shorter experiment length, etc.)
- Baselines and current best run (which ideally includes wandb run or recorded results)

Also record the user's preferred entrypoint format and where experiment results and project notes are tracked, if they told you.

Do not commit the playbook; ask the user to review it.
