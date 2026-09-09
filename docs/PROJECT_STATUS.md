# PatchBench Project Status

This is the canonical source for the current PatchBench milestone, accepted
slice, development handoff, and exact next action.

## Project Identity

PatchBench is a Coding Agent Reliability & Failure Analysis Platform: a
reproducible experimentation platform for evaluating, diagnosing, and improving
coding-agent reliability on real software repositories.

The job-search completion line is:

```text
M4 — Repeated Experiments
M5 — Minimal Failure Analysis & Replay
M6 — Demo / README / Documentation / Resume polish
```

Optional V2 work is outside this completion line.

## Git / Development State

- Current development branch: `feat/m5-failure-analysis-replay`
- Latest accepted slice: M5.3 — Replay + CLI + E2E
- Exact current feature-branch commit: obtain from
  `git log -1 --oneline --decorate`
- Historical accepted commits: `068b585` (status checkpoint) and `f9a09a9`
  (M4.1 implementation)
- `main` and `origin/main`: `9ae4375`, the merge of completed M4

M4 — Repeated Experiments is complete and merged to `main`. M5.1 —
Deterministic Failure Classification is accepted on the current M5 feature
branch and is not yet merged to `main`. M5.2 — PASS-vs-FAIL Comparison is also
accepted on the current M5 feature branch and is not yet merged to `main`.
M5.3 — Replay + CLI + E2E is also accepted on the current M5 feature branch and
is not yet merged to `main`. All three M5 slices require whole-branch milestone
review before M5 is merged.

## Completed Milestones

```text
M0 — Foundation                         complete
M1 — Reproducible Local Run             complete
M2 — Docker Evaluation                  complete
M3 — Real Agent Execution               complete
M4 — Repeated Experiments                complete and merged to main
```

## Current Capabilities

- Validated TaskSpec loading with unknown fields forbidden and schema version 1.
- Repository and configured base-commit verification.
- Clean, isolated detached Git worktree creation and cleanup for each Run.
- Binary-capable Git patch capture, including modifications, deletions, and new
  files.
- Host command evaluation and optional Docker-backed evaluation.
- A deterministic FakeAgent for orchestration verification.
- A real host-side CodexAdapter with explicit model selection and preflight.
- Safe Codex timeout handling, process-group termination, and cleanup.
- Independent agent execution and evaluator outcomes.
- Per-Run `metadata.json`, `prompt.txt`, `agent.log`, `agent.stderr.log`,
  `test.log`, and `patch.diff` artifacts.
- Completed-Experiment `ExperimentConfiguration`, `ExperimentAggregate`, and
  `ExperimentRecord` domain models.
- Pure aggregation from completed RunRecords into ExperimentAggregate metrics.
- `patchbench experiment` execution of N sequential independent Runs using
  repeated FakeAgent or real Codex execution with host or Docker evaluation.
- Completed Experiment metadata persistence at
  `results/experiments/<experiment-id>/metadata.json`, referencing standalone
  child Run artifacts by `run_ids`.
- Pure deterministic multi-label classification from a completed `RunRecord`
  plus already-loaded patch evidence into `FailureAnalysis`, using the directly
  observable `AGENT_COMMAND_FAILED`, `AGENT_TIMED_OUT`, `NO_PATCH`, and
  `TEST_FAILED` categories.
- Pure deterministic descriptive comparison of one explicit PASS `RunRecord`
  and one explicit FAIL `RunRecord` from the same task plus already-loaded
  patch evidence into `PassFailComparison`.
- Historical-patch Replay from one persisted Run artifact into a fresh
  TaskSpec-base worktree, using the existing host or Docker evaluator without
  invoking an Agent, with completed metadata under
  `results/replays/<replay-id>/metadata.json`.

### Not Yet Implemented

- Failure-analysis or comparison CLI and persistence.
- Automatic pair selection or Experiment-wide comparison.

## Current M4 State

- **M4.1 — Experiment Domain + Aggregation:** accepted on the current M4
  feature branch and merged through M4.
- **M4.2 — Sequential Experiment Orchestration:** accepted on the current M4
  feature branch and merged through M4.
- **M4.3 — Experiment CLI + Persistence + E2E:** accepted on the current M4
  feature branch and merged through M4.

M4 — Repeated Experiments passed whole-branch review and is complete and merged
to `main` at `9ae4375`.

M4.1 implemented domain surface:

```text
ExperimentConfiguration
ExperimentAggregate
ExperimentRecord
ExperimentAggregationError
aggregate_runs()
```

Aggregate metrics:

```text
run_count
evaluation_pass_count
evaluation_fail_count
evaluation_pass_rate
agent_command_failure_count
agent_timeout_count
total_duration_seconds
mean_duration_seconds
min_duration_seconds
max_duration_seconds
```

### M4 Whole-Branch Review

The accepted milestone-level review covered Experiment domain consistency, the
Run/Experiment relationship, sequential independence, Agent outcome versus
Evaluation outcome, hard-failure semantics, CLI one-source-of-truth composition,
Experiment persistence and artifact ownership, runtime cleanup and
reproducibility, documentation consistency, and scope boundaries.

Two blockers were found, fixed, and incrementally reviewed:

1. README contained stale M4.3 review status.
2. A whitespace-padded Codex `--model` could make actual execution and recorded
   metadata disagree.

The resulting CLI invariant is that the selected Codex model is normalized once
before both Agent construction and Run/Experiment metadata composition. No M4
whole-branch blockers remain.

## Current M5 State

- **M5.1 — Deterministic Failure Classification:** accepted on the current M5
  feature branch; not yet merged to `main`.
- **M5.2 — PASS-vs-FAIL Comparison:** accepted on the current M5 feature branch;
  not yet merged to `main`.
- **M5.3 — Replay + CLI + E2E:** accepted on the current M5 feature branch; not
  yet merged to `main`.

All three M5 slices are accepted on the feature branch. M5 still requires
whole-branch review and milestone documentation finalization before merge.

M5.1 introduces `FailureCategory`, `FailureAnalysis`, and the pure
`classify_run_failure()` boundary. It reports only ordered, directly observable
conditions and does not infer semantic root causes.

M5.2 introduces `PassFailComparison`, `PassFailComparisonError`, and the pure
`compare_pass_fail_runs()` boundary. Callers explicitly supply PASS and FAIL
roles plus already-loaded patch evidence; the result is descriptive and does
not claim causal attribution.

Valid pairs use the same task and different Run IDs. M5.1 remains the sole
failure-taxonomy source; patch presence uses stripped semantic presence, patch
equality uses exact artifact text, and duration is recorded as FAIL minus PASS.

M5.3 adds `ReplayRecord` and `patchbench replay --task ... --run-id ...
[--docker]`. Replay loads the canonical historical patch, creates a fresh
worktree at the caller-supplied TaskSpec base commit, applies or skips that
patch, and invokes the existing evaluator with zero Agent executions. Outcome
mismatch and replay evaluation FAIL are normal completed observations. Replay
v1 does not claim complete historical environment reconstruction.

## Architecture Invariants

- Run is the atomic execution unit.
- An Agent edits the workspace; GitRepositoryManager owns patch capture.
- Agent outcome is independent from evaluation outcome.
- `COMPLETED`, `COMMAND_FAILED`, and `TIMED_OUT` are normal agent execution
  outcomes. A returned result continues through patch capture and evaluation.
- Hard setup and infrastructure failures remain exceptions and must not be
  fabricated into normal reliability RunRecords.
- Application code depends on abstractions rather than CodexAdapter or
  DockerSandbox concrete implementations.
- M4 repeated execution is sequential-first.
- A completed Experiment satisfies
  `requested_runs == len(run_ids) == aggregate.run_count`.
- `requested_runs` is a strict positive integer.
- Pure aggregation rejects an empty RunRecord collection.
- M4 v1 has no PARTIAL, ABORTED, or INTERRUPTED Experiment record.

Accepted hard-failure tradeoff:

```text
hard setup/infrastructure exception
→ abort Experiment
→ propagate exception
→ do not fabricate RunRecord
→ completed standalone child Run artifacts may remain
```

M4 intentionally does not persist interrupted Experiment records. Completed
child Runs left by an aborted Experiment may therefore lack durable Experiment
membership.

## Locked Roadmap

```text
M4 — Repeated Experiments
M5 — Minimal Failure Analysis & Replay
M6 — Demo / README / Documentation / Resume polish
```

After M6, the job-search version should stop expanding scope. Optional V2 work
remains separate.

## Deferred Work

- M5 whole-branch review and milestone documentation finalization.
- Later M5 work: failure/comparison CLI and persistence.
- Later comparison work: automatic pair selection, Experiment-wide comparison,
  and structural or semantic patch analysis.
- Later failure-analysis work: semantic categories, evaluator timeout
  classification, and infrastructure-abort evidence.
- M6: realistic demo tasks, an experiment dataset, README polish, architecture
  diagram, resume bullets, and interview-note consolidation.
- Optional V2: repository-aware context, large benchmark ingestion,
  parallel/distributed execution, multi-agent support, and database/dashboard
  work.

## Latest Validation Evidence

Accepted M4.1 verification at commit
`f9a09a9 feat: add experiment domain and aggregation`:

```text
focused:         24 passed
full regression: 113 passed, 7 skipped
```

Accepted M4.2 verification evidence:

```text
focused:         44 passed
full regression: 123 passed, 7 skipped
```

Accepted M4.3 automated verification evidence:

```text
focused:         33 passed
full regression: 138 passed, 7 skipped
```

Accepted M4.3 human runtime evidence:

```text
FakeAgent E2E:
  runs:            3
  evaluation PASS: 3
  evaluation FAIL: 0

Real Codex + Docker E2E:
  agent:                     codex
  model:                     gpt-6-astra
  runs:                      3
  agent timeout:             120 seconds
  evaluation backend:        docker
  evaluation pass count:     3
  evaluation fail count:     0
  evaluation pass rate:      1.0
  agent command failures:    0
  agent timeouts:             0
  total child duration:      approximately 137.328 seconds
  mean run duration:         approximately 45.776 seconds
  experiment duration:       approximately 137.352 seconds
```

The Experiment consistency checker passed. The source fixture was clean, only
its source Git worktree remained, temporary Experiment workspaces were empty,
and no PatchBench sandbox containers remained.

Accepted M4 whole-branch blocker-fix regression evidence:

```text
focused CLI:    23 passed
full regression: 138 passed, 7 skipped
compileall:     PASS
git diff --check: PASS
```

Accepted M5.1 verification evidence:

```text
focused:         8 passed
full regression: 146 passed, 7 skipped
```

M5.1 required no networked, Codex, or Docker end-to-end execution.

Accepted M5.2 verification evidence:

```text
focused:         12 passed
full regression: 158 passed, 7 skipped
```

M5.2 required no networked, Codex, or Docker end-to-end execution.

Accepted M5.3 automated verification evidence:

```text
focused:         60 passed
full regression: 192 passed, 7 skipped
compileall:      PASS
git diff --check: PASS
```

Accepted M5.3 human runtime evidence:

```text
FakeAgent source → Docker Replay:
  source Run ID:       f196f4f0235f40268bfaffd2eeab8d97
  Replay ID:           d1c4c2480c534fa6ad0872352ce41e1e
  source evaluation:   PASS
  Replay evaluation:   PASS
  outcome match:       true
  evaluation backend:  docker
  source patch:         243 bytes, non-empty
  base commit used:     4ed891e6144bdb78941160726ada95fa7a710f3c

Real Codex source → Docker Replay:
  source Run ID:       de1717bc5b5f4420850e5f79e7350835
  Replay ID:           567ee76acce241fcbbcf52e3ab654bff
  source agent:        codex
  requested model:     gpt-6-astra
  agent status:        COMPLETED
  source evaluation:   PASS
  Replay evaluation:   PASS
  outcome match:       true
  evaluation backend:  docker
  source patch:         1906 bytes
  base commit used:     4ed891e6144bdb78941160726ada95fa7a710f3c
```

The real Codex patch included the calculator source fix and canonical Git
binary patch content for Python `__pycache__` files; Replay applied it and
passed Docker evaluation. This is known artifact-cleanliness debt, not a new
M5.3 feature.

For both E2Es, source metadata and patch hashes remained unchanged, Replay
directories contained only `metadata.json` and `test.log`, the fixture remained
clean, temporary workspaces were removed, and no PatchBench sandbox containers
remained. Replay invoked no second Codex execution.

## Documentation Map

- `docs/PROJECT_STATUS.md`: canonical current truth, handoff, and exact next
  action.
- `ARCHITECTURE.md`: architecture and design boundaries.
- `docs/DEVELOPMENT.md`: development, review, and Git workflow.
- `PROJECT_SPEC.md`: product goals and MVP intent.
- `README.md`: public-facing project introduction and usage.
- `docs/interview_notes.md`: interview-oriented reasoning and historical
  decisions.

If another document disagrees with current status, Git and source evidence win;
report the stale documentation.

### Continuity Maintenance

After each accepted slice, update this document if the current slice, accepted
commit, implemented capabilities, architecture invariants, validation evidence,
or exact next action changes.

Update `ARCHITECTURE.md` only for material architecture, domain, or lifecycle
changes. Update `README.md` only for material user-visible capability or major
status changes. Do not document every small implementation detail.

## Exact Next Action

Perform M5 whole-branch review and milestone documentation finalization.
