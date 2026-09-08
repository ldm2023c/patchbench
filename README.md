# PatchBench

PatchBench is a coding-agent reliability and failure analysis platform. It is
intended to make repeated repository-level coding experiments reproducible and
inspectable, so that successes and failures can be compared using evidence
rather than a single successful run.

## Current status

Milestones 0–3 are complete and merged to `main`. PatchBench supports
reproducible single Runs with FakeAgent or a real host-side CodexAdapter, actual
Git patch capture, host or Docker-backed evaluation, and structured per-Run
artifacts.

**Milestone 4 — Repeated Experiments** is in progress. M4.1 — Experiment Domain
+ Aggregation is complete on the current `feat/m4-repeated-experiments`
development branch; it defines completed-Experiment models and pure aggregation
without yet implementing repeated Run orchestration, an experiment CLI, or
experiment persistence. See [Project Status](docs/PROJECT_STATUS.md) for the
canonical current development state and exact next action.

Coding agents still execute on the host; `--docker` selects Docker-backed task
evaluation. Arbitrary repository dependencies are not automatically
provisioned, network isolation is not implemented, and the Docker sandbox is
not presented as a production-grade hostile multi-tenant security boundary.

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
