# PatchBench

PatchBench is a coding-agent reliability and failure analysis platform. It is
intended to make repeated repository-level coding experiments reproducible and
inspectable, so that successes and failures can be compared using evidence
rather than a single successful run.

## Current status

The project has completed **Milestone 2.2 — Docker Command Execution + Workspace
Mount**. In addition to the deterministic local Run from Milestone 1, the
sandbox can create and reliably destroy a Docker container without enabling
Docker privileged mode, bind-mount one explicit host workspace read-write at
`/workspace`, and execute explicit argv-style commands there.

LocalRun does not use Docker yet. Automatic workspace integration, Dockerized
agent or evaluator execution, resource limits, timeout management, Codex
execution, and repeated experiments are not implemented.

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

Docker integration tests are explicitly opt-in:

```bash
PATCHBENCH_RUN_DOCKER_TESTS=1 pytest -m docker
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
