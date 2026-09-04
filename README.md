# PatchBench

PatchBench is a coding-agent reliability and failure analysis platform. It is
intended to make repeated repository-level coding experiments reproducible and
inspectable, so that successes and failures can be compared using evidence
rather than a single successful run.

## Current status

The project is at **Milestone 0 — Project Skeleton**. It currently provides a
Python package, a validated YAML task format, and a CLI command for checking
task files. Docker sandboxing and Codex experiment execution are not implemented
yet.

## Development setup

PatchBench requires Python 3.12 or later. Create and activate a virtual
environment, then install the package and development dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run the tests with:

```bash
pytest
```

## CLI

Display the available command:

```bash
patchbench --help
```

Validate a task definition:

```bash
patchbench validate-task tasks/example/task.yaml
```

The repository path and base commit in the example task are placeholders;
Milestone 0 validates their configuration but does not access or execute a
repository.
