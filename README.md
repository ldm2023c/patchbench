# PatchBench

PatchBench is a coding-agent reliability and failure analysis platform. It is
intended to make repeated repository-level coding experiments reproducible and
inspectable, so that successes and failures can be compared using evidence
rather than a single successful run.

## Current status

The project has completed **Milestone 2 — Docker Execution**. A Run can now
optionally evaluate its task command in a Docker sandbox: PatchBench creates an
isolated Git worktree, FakeAgent edits that worktree on the host, captures the
agent patch, and mounts only the worktree read-write at `/workspace` for
evaluation. The sandbox supports explicit argv execution, optional CPU/memory
limits, timeout cleanup, and reliable container removal without enabling Docker
privileged mode.

Host evaluation remains the default, while `--docker` selects Docker-backed
evaluation. The controlled example uses Python's standard-library `unittest` so
it runs in the existing minimal Python image without dependency installation.
Coding agents do not yet execute inside Docker, and arbitrary repository
dependencies are not automatically provisioned. Network isolation, Codex
execution, and repeated experiments are not implemented. The current Docker
sandbox is not presented as a production-grade hostile multi-tenant security
boundary.

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

Evaluate the same Run inside Docker:

```bash
patchbench run --task tasks/example/task.yaml --agent fake --docker
```

Both modes start a detached worktree at the configured base commit, capture the
deterministic repair before evaluation, remove the temporary worktree, and
retain these files under `results/<run-id>/`:

```text
metadata.json
agent.log
test.log
patch.diff
```
