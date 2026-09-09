# PatchBench

**Coding Agent Reliability & Failure Analysis Platform**

A reproducible experimentation platform for evaluating, diagnosing, and
improving coding-agent reliability on real software repositories.

A coding agent succeeding once does not mean it is reliable. The same task and
configuration can produce different patches, outcomes, and durations across
repeated executions. PatchBench preserves the execution evidence needed to
study that variation:

```text
Run → Repeat → Classify → Compare → Replay
```

## Why PatchBench?

PatchBench separates five practical reliability questions:

- **Run:** Did this individual execution pass its evaluator?
- **Experiment:** How reliable was the same frozen setup across repeated Runs?
- **FailureAnalysis:** Which directly observable failure conditions occurred?
- **PassFailComparison:** What evidence differs between one PASS and one FAIL?
- **Replay:** Does a saved historical patch reproduce its observed outcome on a
  fresh base worktree?

The included calculator task is a small deterministic demonstration fixture,
not the project's core contribution.

## What PatchBench Does

- Loads and validates TaskSpec YAML.
- Creates a clean detached Git worktree at the configured base commit for every
  Run.
- Executes either the deterministic FakeAgent or a real host-side CodexAdapter.
- Captures a binary-capable canonical Git patch before evaluation.
- Evaluates through the host or an optional Docker sandbox.
- Persists independent Run evidence and aggregates repeated Runs into an
  Experiment.
- Classifies directly observable failure conditions and descriptively compares
  an explicit PASS/FAIL pair through programmatic APIs.
- Replays a historical patch from a fresh TaskSpec base without invoking an
  Agent.

## Workflow

One execution remains the atomic unit:

```text
TaskSpec
   ↓
fresh Git worktree
   ↓
Agent (host)
   ↓
canonical patch capture
   ↓
host / Docker evaluation
   ↓
RunRecord
```

Repeated reliability and M5 analysis build on completed Runs:

```text
Run × N                        Run + patch
   ↓                               ↓
Experiment                   FailureAnalysis
   ↓
reliability aggregate

PASS Run + patch  ↔  FAIL Run + patch
                 ↓
        PassFailComparison

historical Run + canonical patch
                 ↓
fresh worktree at caller-supplied TaskSpec base
                 ↓
       existing host / Docker evaluator
                 ↓
             ReplayRecord
```

## Quickstart

### Prerequisites and installation

PatchBench requires Python 3.12 or later and Git. Docker is optional and used
only for task evaluation. Real-agent execution additionally requires an
installed and authenticated Codex CLI; the Agent still runs on the host.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Prepare and validate the built-in example:

```bash
python scripts/prepare_example_fixture.py
patchbench validate-task tasks/example/task.yaml
```

The task is `example_bug`, starts from its declared fixture commit, and uses
`python -B -m unittest -q` as its evaluator.

### Run one task

```bash
patchbench run \
  --task tasks/example/task.yaml \
  --agent fake
```

To keep the Agent host-side while evaluating inside Docker:

```bash
patchbench run \
  --task tasks/example/task.yaml \
  --agent fake \
  --docker
```

Real Codex execution uses `--agent codex` and requires an explicit `--model`.

### Run a repeated Experiment

```bash
patchbench experiment \
  --task tasks/example/task.yaml \
  --agent fake \
  --runs 3
```

The Runs execute sequentially from independent clean worktrees. The summary
reports Evaluation PASS/FAIL separately from Agent command failures/timeouts,
along with aggregate duration metrics. Add `--docker` to evaluate each Run in
Docker.

### Inspect failure and comparison APIs

Failure classification and PASS-vs-FAIL comparison are programmatic APIs; no
classification or comparison CLI is currently provided.

```python
from patchbench.domain import classify_run_failure, compare_pass_fail_runs

analysis = classify_run_failure(
    run,
    patch_text=patch_text,
)

comparison = compare_pass_fail_runs(
    pass_run,
    fail_run,
    pass_patch_text=pass_patch_text,
    fail_patch_text=fail_patch_text,
)
```

Their exact signatures are:

```python
classify_run_failure(run: RunRecord, *, patch_text: str) -> FailureAnalysis

compare_pass_fail_runs(
    pass_run: RunRecord,
    fail_run: RunRecord,
    *,
    pass_patch_text: str,
    fail_patch_text: str,
) -> PassFailComparison
```

`FailureCategory` contains exactly `AGENT_COMMAND_FAILED`, `AGENT_TIMED_OUT`,
`NO_PATCH`, and `TEST_FAILED`. These are directly observable conditions, not
semantic root causes. Comparison requires explicit PASS and FAIL roles from the
same task with different Run IDs; its result is descriptive rather than causal.

### Replay a historical patch

```bash
patchbench replay \
  --task tasks/example/task.yaml \
  --run-id <historical-run-id>
```

Add `--docker` for Docker-backed Replay evaluation. Replay loads the historical
RunRecord and canonical patch, creates a fresh detached worktree at the base
commit from the caller-supplied TaskSpec, applies the patch (or skips an empty
patch), invokes zero Agents, and persists separate Replay evidence.

Replay v1 uses the caller-supplied TaskSpec base commit and the currently
selected evaluator backend. It does not claim to reconstruct the complete
original historical execution environment.

## Artifacts

```text
results/
├── <run-id>/
│   ├── metadata.json
│   ├── prompt.txt
│   ├── agent.log
│   ├── agent.stderr.log
│   ├── test.log
│   └── patch.diff
├── experiments/
│   └── <experiment-id>/
│       └── metadata.json
└── replays/
    └── <replay-id>/
        ├── metadata.json
        └── test.log
```

A Run owns its execution artifacts and canonical historical patch. An
Experiment owns aggregate metadata and references standalone child Runs by
`run_ids`. A Replay references one `source_run_id`, owns its new metadata and
evaluation log, and does not duplicate the source patch.

## Reliability Semantics

- **Agent outcome is independent from Evaluation outcome.** An Agent command
  failure does not necessarily imply that evaluation fails.
- Evaluation FAIL is an observed task result, not automatically a PatchBench
  infrastructure failure.
- Replay evaluation FAIL is still a completed Replay.
- A source/Replay outcome mismatch is a completed observation, not Replay
  infrastructure failure.
- Patch-application, repository, sandbox, and storage failures remain hard
  infrastructure failures rather than fabricated evaluation results.

## Scope and Non-goals

PatchBench is a local, inspectable reliability experimentation tool. It is not
a generic coding-agent framework, benchmark leaderboard, web dashboard,
multi-agent orchestrator, semantic root-cause oracle, or complete historical
environment snapshot system. Its Docker sandbox provides practical evaluation
isolation, not a production-grade hostile multi-tenant security boundary.

## Project Status

Milestones 0–5 are complete and merged to `main`. M6 is the current
demo/documentation/presentation milestone. M6.1 — Public Demo & README is
complete and committed on `feat/m6-demo-docs-polish`. M6.2 — Documentation /
Interview / Resume Polish is complete and accepted on the same feature branch.
M6 whole-milestone review is still pending. M6 has not yet been merged to
`main`. See [Project Status](docs/PROJECT_STATUS.md) for canonical milestone
evidence and the exact next action.

Historical patch Replay has been validated end to end with both a FakeAgent
source Run and a real Codex source Run using Docker evaluation. The real
Codex-generated canonical Git patch included binary patch content and was
successfully persisted and replayed. Detailed Run IDs, Replay IDs, and cleanup
evidence remain in the canonical project-status record; ephemeral hash values
and temporary paths are intentionally omitted here.

## Development and Tests

Run the ordinary regression suite:

```bash
pytest
```

Docker integration tests are explicitly opt-in:

```bash
PATCHBENCH_RUN_DOCKER_TESTS=1 pytest -m docker
```

See [Development Workflow](docs/DEVELOPMENT.md) for the human-owned review,
Git, and milestone process. PatchBench does not claim CI behavior that is not
configured in this repository.
