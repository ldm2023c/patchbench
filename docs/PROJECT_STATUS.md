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

- Current development branch: `feat/m4-repeated-experiments`
- Latest accepted slice: M4.1 — Experiment Domain + Aggregation
- Latest accepted commit: `f9a09a9 feat: add experiment domain and aggregation`
- `main` and `origin/main`: `bdeaec6`, the merge of completed M3

M4.1 is accepted on the current feature branch. It is not yet merged to `main`.

## Completed Milestones

```text
M0 — Foundation                         complete
M1 — Reproducible Local Run             complete
M2 — Docker Evaluation                  complete
M3 — Real Agent Execution               complete
M4.1 — Experiment Domain + Aggregation  accepted on current M4 branch
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
- Completed-Experiment domain models.
- Pure aggregation from completed RunRecords into ExperimentAggregate metrics.

### Not Yet Implemented

- Independent N-run Experiment orchestration.
- Experiment CLI commands.
- Experiment metadata or artifact persistence.
- Failure classification.
- PASS-vs-FAIL comparison.
- Replay.

## Current M4 State

- **M4.1 — Experiment Domain + Aggregation:** accepted on the current M4
  feature branch.
- **M4.2 — Sequential Experiment Orchestration:** next; not implemented.
- **M4.3 — Experiment CLI + Persistence + E2E:** not implemented.

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

- M4.2: sequential independent N-run orchestration, a fresh Agent and worktree
  per Run, and one frozen TaskSpec and execution configuration.
- M4.3: Experiment CLI, Experiment metadata persistence, and real repeated
  Codex end-to-end verification.
- M5: PASS-vs-FAIL comparison, deterministic failure classification, and replay.
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

This evidence validates M4.1, not M4.2 or M4.3.

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

Design and scope-lock M4.2 — Sequential Experiment Orchestration.

Do not begin M4.2 implementation before exact-slice confirmation.
