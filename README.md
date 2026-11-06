# rstack

My personal stack of agent skills for AI research. This is opinionated and specific to me so ymmv.

## Skills

| Skill name | Description |
| --- | --- |
| design-experiment | Help the user design an experiment and implement it. Also initialises project's experiment playbook if not already present |
| run-experiment | Run the experiment on a compute resource |
| estimate-runtime | Estimate an experiment's runtime by checking its throughput metric on the compute it will run on |
| use-isambard | Compute skill for the Isambard academic compute cluster |
| make-plot | Create paper-ready plots how I like them |

## Installation

### Claude Code

```
/plugin marketplace add rainx0r/rstack
/plugin install rstack@rainx0r
```

## Usage

```
/design-experiment <your description of what you want to do>
```

Then, once the experiment is very clear and implemented and context for how experiments should be run exists:

```
/run-experiment <design-experiment's handoff or description of the experiment and location of the entrypoint>
```

