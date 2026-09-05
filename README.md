# PatchBench

PatchBench is a coding-agent reliability and failure analysis platform. It is
intended to make repeated repository-level coding experiments reproducible and
inspectable, so that successes and failures can be compared using evidence
rather than a single successful run.

## Current status

The project is at **Milestone 1 — Deterministic Local Run**. It provides a
validated YAML task format and can execute one local Run using an isolated Git
worktree, a deterministic FakeAgent, subprocess-based evaluation, and
filesystem artifacts.

Docker sandboxing, Codex execution, and repeated experiments are not
implemented yet.

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

Prepare the example fixture's deterministic local Git commit:

```bash
python scripts/prepare_example_fixture.py
```

The printed commit must match the `base_commit` recorded in the example task.
The preparation command is safe to run again when the fixture is already
prepared and clean.

Execute one local Run with FakeAgent:

```bash
patchbench run --task tasks/example/task.yaml --agent fake
```

Every Run starts a detached worktree at the configured base commit, evaluates
the deterministic repair, removes the temporary worktree, and retains these
files under `results/<run-id>/`:

```text
metadata.json
agent.log
test.log
patch.diff
```
