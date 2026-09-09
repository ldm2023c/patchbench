# PatchBench

PatchBench is a coding-agent reliability and failure analysis platform. It is
intended to make repeated repository-level coding experiments reproducible and
inspectable, so that successes and failures can be compared using evidence
rather than a single successful run.

## Current status

Milestones 0–5 are complete and merged to `main`. PatchBench supports
reproducible single Runs with FakeAgent or a real host-side CodexAdapter, actual
Git patch capture, host or Docker-backed evaluation, and structured per-Run
artifacts.

**Milestone 5 — Minimal Failure Analysis & Replay** is complete and merged to
`main` through merge commit `223e5de`. Its three slices were implemented,
reviewed, and accepted, and M5 passed whole-branch code review. See [Project
Status](docs/PROJECT_STATUS.md) for the canonical milestone state and exact next
action.

M5 adds deterministic classification of directly observable Run failure
conditions, explicit deterministic descriptive comparison of one PASS and one
FAIL Run, and historical patch Replay. Classification does not infer semantic
root causes, and comparison does not establish causality.

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

Execute three independent sequential Runs as one Experiment:

```bash
patchbench experiment \
  --task tasks/example/task.yaml \
  --agent fake \
  --runs 3
```

The command prints separate Evaluation and Agent reliability metrics and writes
the completed Experiment record to
`results/experiments/<experiment-id>/metadata.json`. Its `run_ids` reference the
unchanged standalone child artifacts under `results/<run-id>/`.

Evaluate the same Run inside Docker:

```bash
patchbench run --task tasks/example/task.yaml --agent fake --docker
```

Both modes start a detached worktree at the configured base commit, capture the
deterministic repair before evaluation, remove the temporary worktree, and
retain these files under `results/<run-id>/`:

```text
metadata.json
prompt.txt
agent.log
agent.stderr.log
test.log
patch.diff
```

Replay a historical Run's canonical patch without invoking an Agent:

```bash
patchbench replay \
  --task tasks/example/task.yaml \
  --run-id <historical-run-id>
```

Add `--docker` to use Docker-backed evaluation. Replay creates a fresh detached
worktree at the base commit from the caller-supplied TaskSpec, applies the saved
patch, and writes separate Replay metadata and evaluation output under
`results/replays/<replay-id>/`. Replay v1 uses the currently selected evaluation
backend and does not claim to reconstruct the complete historical execution
environment.
