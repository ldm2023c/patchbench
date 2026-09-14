# Historical V1 / V1.1 Handoff Snapshot

Archived verbatim from `docs/PROJECT_STATUS.md` at `3e4af7d` during the V1.2
documentation sync. All branch, current/next, test-count, and capability statements
below describe the earlier V1/V1.1 handoff, not current V1.2 status.
See [current Project Status](../PROJECT_STATUS.md). Historical artifacts remain unchanged.

---

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

PatchBench v1 and the current job-search completion line are **COMPLETE**.
Optional V2 work has not started and remains outside this completion line.

## Active Post-v1 Milestone

The owner has reopened development for **PatchBench V1.1 — Evidence Release**.
V1 remains historically complete. V1.1 seeks real, reproducible, inspectable
reliability evidence, not platform expansion. Optional V2 remains deferred.

V1.1.0 — Pilot Task Discovery: **complete**.
Pilot Evidence Review + Schema Design Gate: **complete**, as confirmed by the owner.
V1.1.1 — Minimal Provenance: **externally accepted** at
`f2b7020 feat: add minimal run provenance`.
V1.1.2 — Deterministic Patch + Evaluation Evidence: **externally accepted** at
`7222535 feat: add deterministic run evidence`.
V1.1.3 — Analyze Workflow: **externally accepted** at
`c9a9d2e feat: add experiment analysis workflow`.
V1.1.4 — Real Task Suite A: **externally accepted** at
`9af2d28 feat: add v1.1 reliability suite A`.
V1.1.5a — Real Task Suite B Candidates: **externally accepted** at
`2440af2 feat: add v1.1 reliability suite B candidates`.
V1.1.5b1 — Frozen Evaluator Contract: **externally accepted** at
`802c4d3 feat: add frozen evaluator contract`
(`802c4d3dcc09d89400ca306eae253b5ef585d442`).
V1.1.5b2 — Suite Freeze + Manifest: **externally accepted** at
`94cd287 feat: freeze v1.1 evidence suite`.
Freeze tag: `v1.1-evidence-freeze`, commit
`94cd2873c42af7f5c697e6316316c9cb59fc6d8b`.
Strict preflight passed before final execution and again on the clean freeze
checkout before release edits.
V1.1.6 — Final Evidence Release: **externally accepted** at
`7a99c2c docs: publish v1.1 final evidence`
(`7a99c2ca580ac34a2ca9cc248ec2f8977656c495`).
**PatchBench V1.1: COMPLETE.**
Current slice: **none — V1.1 is complete**.
The 32 final Runs are complete; no replacement Runs or new Agent executions
are part of this release slice. Optional V2 remains deferred.

Locked sequence:

```text
V1.1.0 Pilot Task Discovery
→ Pilot Evidence Review + Schema Design Gate
→ V1.1.1 Minimal Provenance
→ V1.1.2 Deterministic Patch + Evaluation Evidence
→ V1.1.3 Analyze Workflow
→ V1.1.4 Real Task Suite A
→ V1.1.5a Real Task Suite B Candidates
→ NON-FINAL Suite B calibration (complete)
→ V1.1.5b1 Frozen Evaluator Contract
→ V1.1.5b2 Suite Freeze + Manifest
→ V1.1.6 Final Experiments + Evidence Release
```

Two standard-library pilot candidates are available under `tasks/pilot/`:

- Configuration precedence: 16 tests; buggy base has 9 assertion failures;
  temporary reference repair passes all 16 tests.
- Bookmark parsing/serialization: 14 tests; buggy base has 2 assertion failures
  and 5 errors; temporary reference repair passes all 14 tests.

Tracked fixture templates live under `fixtures/pilot/`. Preparation copies them
into ignored `.prepared/` repositories with fixed commits declared by TaskSpecs;
no nested Git metadata enters the parent repository. Focused tests cover
independent deterministic preparations, repeat preparation, unsafe-state refusal,
base failures, reference solvability, and worktree cleanup. Both canonical
runtime fixtures end clean at their configured buggy bases.

Local V1.1.0 regression: **201 passed, 7 skipped** (Docker integration remains
opt-in); this includes 9 new pilot preparation/solvability cases. Both TaskSpecs
validate, and `git diff --check` passes. No real-Agent benchmark claims follow
from these checks.

The owner's completed NON-FINAL pilot review reported 6/6 valid Runs completed
and passed. Exact successful patches and test edits varied across repeats,
including different successful implementations of the same task. These are
pilot design observations, not final V1.1 benchmark results. Pilot artifacts
remain unchanged and excluded from the final dataset.

Locked evidence-driven provenance decisions:

- Evaluator backend is independent of `agent.backend`, which remains `host`.
- Task fingerprints exclude machine-specific `repository.path` and use the
  actual resolved workspace base commit, exact validated prompt, evaluation
  command/timeout, schema version, task ID, repository type, and task metadata.
- Canonical serialization is sorted compact JSON with `ensure_ascii=False`,
  encoded as UTF-8 and hashed with SHA-256.
- Historical v1 Runs may omit provenance or have null provenance.
- Every newly executed V1.1 Run persists `RunProvenance`: resolved base commit,
  task fingerprint, evaluation command, timeout, and host/Docker backend.
- Experiment children reuse single-Run construction; storage layout and Replay
  semantics are unchanged. No old artifacts are migrated.

V1.1.1 validation: focused provenance/Run/Experiment/Replay checks **69 passed**;
full regression **226 passed, 7 skipped** (Docker integration opt-in). Compile
check and `git diff --check` passed. Ordinary tests use a stub sandbox for Docker
provenance; no real Codex execution or pilot-artifact migration occurred.

V1.1.2 adds deterministic evidence to new Run metadata:

- Whole-patch identity alone was insufficient in the pilot. PatchSummary now
  captures exact UTF-8 whole-patch and complete per-file diff hashes, affected
  paths, change types, binary status, and textual hunk line counts.
- Path-based roles distinguish generated, test, and non-test files, in that
  precedence order. These are descriptive signals, not semantic solution IDs.
- EvaluationEvidence hashes the exact shared-renderer test log, records wrapper
  exit code/duration, extracts recognizable unittest summaries and failure/error
  identifiers from stdout/stderr, and keeps at most 20 non-empty trailing lines.
  Unrecognized frameworks remain unknown; malformed evidence raises a narrow
  parsing error.
- Raw `patch.diff` and `test.log` remain canonical, with unchanged formatting and
  artifact layout. Historical records may omit both evidence fields; no
  artifacts are migrated. Experiment children reuse single-Run integration,
  and Replay gains no new evidence fields.

V1.1.2 validation: **68 evidence tests passed**; combined evidence/provenance/
Run/Experiment/Replay checks **137 passed**; full regression **294 passed,
7 skipped** (Docker integration opt-in). Compile and `git diff --check` passed.
Tests verify hashes against persisted artifact bytes, real temporary Git binary
patches, stub-sandbox integration, and historical load/Replay compatibility.
No real Codex runs or pilot-artifact changes were made.

V1.1.3 adds `patchbench analyze --experiment <ID> [--json]`: read-only loading,
raw patch/log re-summarization, cached evidence checks, outcome/configuration/
provenance/aggregate verification, exact patch variant counts, existing failure
observations, and the deterministic first PASS/first FAIL example pair. Child
order is preserved. Historical missing summaries are reconstructed in memory;
missing provenance remains unavailable. No artifacts are written or migrated.
Suite freeze and final experiments remain deferred.

V1.1.3 validation: analysis/storage focused **45 passed**, CLI **49 passed**;
combined **94 passed**. Full regression **357 passed, 7 skipped**; compile and
`git diff --check` passed. Tests verify results-tree directories and file bytes
remain unchanged, reject input inconsistencies, and cover clean JSON plus both
installed-command composition and the Python module entry point. No real Codex
or Docker execution was required.

V1.1.4 adds two purpose-built realistic candidate repositories, `streaming_events`
and `request_signing`, under `fixtures/reliability/`, with TaskSpecs under
`tasks/reliability/`. They model incremental NDJSON import and webhook request
canonicalization respectively; they are not imported upstream or observed
production bugs. Preparation reuses the hardened Pilot helper and creates only
ignored `.prepared/` repositories, with deterministic commits and safe existing
state verification. Pilot fixtures and platform source remain unchanged.

Host and `python:3.12-slim` Docker baseline checks agree: streaming_events has
33 tests, 8 failures and 6 errors; request_signing has 35 tests and 17 assertion
failures (including subtests). Both retain meaningful passing legacy coverage.
Temporary repairs outside the project passed all 33 and 35 tests respectively
and were deleted; no complete Suite A repair is shipped or added to Git history.
Focused preparation checks: **9 passed**. Full regression: **366 passed,
7 skipped** (platform Docker integration opt-in). Compile and `git diff --check`
passed. Both canonical prepared repositories remain clean at TaskSpec bases.

No real Codex calibration ran during V1.1.4 implementation. Candidates may change
after calibration; final selection/freeze requires the V1.1.5b2 gate. V1.1.4 calibration
Runs are **NON-FINAL forever**. The older V1.1.0 Pilot remains discovery-only
and can never become final evidence. These checks establish baseline quality
and solvability, not coding-agent benchmark pass rates.

The owner's completed Suite A NON-FINAL calibration reported streaming_events
**2/2 PASS, 2 exact patch variants** and request_signing **2/2 PASS, 2 exact
patch variants**. Both pairs differed in their production-module diffs. Both
candidates showed successful implementation variation; neither produced PASS/FAIL
outcome variation in two Runs. Do not infer statistical reliability from n=2.
Suite A templates and prepared base commits remain unchanged; V1.1.5b1 updates
TaskSpec evaluation semantics without modifying historical artifacts.

V1.1.5a adds `atomic_batch` and `cache_revalidation` as purpose-built Suite B
candidates, initially uncalibrated and still not frozen. Their visible standard-library
tests exercise store/journal/idempotency transaction consistency and cached
representation/freshness/backend-error consistency. The existing reliability
preparation script now covers all four candidates using the same hardened helper.
No platform source, Pilot definitions or existing Run artifacts changed.

Suite B host and `python:3.12-slim` Docker baselines agree: atomic_batch has
36 tests with 10 failures; cache_revalidation has 39 tests with 19 failures and
1 error. Both retain meaningful PASS coverage and fail behavioral contracts,
without import/setup failures. Temporary repairs outside the project passed
all 36 and 39 tests and were deleted; no complete repair is shipped or added
to prepared Git history. Focused preparation checks: **17 passed**. Full
regression: **374 passed, 7 skipped** (platform Docker integration opt-in).
Compile and tracked/untracked whitespace checks passed. All four prepared
repositories remain clean at their TaskSpec bases with no extra worktrees.
No real Codex execution occurred in V1.1.5a. All later Suite B calibration Runs
remain **NON-FINAL forever**.

The owner's completed Suite B calibration reported atomic_batch **2/2 PASS**
and cache_revalidation **2/2 PASS**. All four tasks passed 2/2 each, for **8/8
NON-FINAL calibration Runs**. Every Run edited its visible test file; this does
not prove cheating or weakened tests. Production-level variation was observed
for streaming_events and request_signing. Atomic batch's two whole-patch variants
were caused only by different test edits; production diffs were identical.
Cache revalidation varied in client.py while cache.py repairs matched. No
statistical reliability claim follows from n=2 per task.

V1.1.5b1 adds optional schema-version-1 `evaluation.frozen_unittest` configuration
with protocol version 1 and an ordered, unique, nonempty list of root-level Python
test filenames. Its command is fixed to
`python -I -S -B .patchbench-eval/runner.py`. After capturing the complete Agent
patch, shared Run/Replay evaluation creates another exact-base worktree, retains
its pristine test bytes, applies the full patch, restores declared tests safely,
and replaces the reserved runner directory with platform-owned content. Only
declared tests execute; zero-test success is rejected. Host/Docker use the same
view, with unchanged Docker mounts. Experiments inherit the Run path.

Patch evidence remains the pre-evaluation Agent patch. Official Run outcome,
test.log and EvaluationEvidence derive from the frozen evaluator. No RunRecord
fields changed. Frozen fingerprints include protocol version and ordered files;
legacy fingerprints and evaluation remain unchanged. Replay preserves caller-
provided TaskSpec semantics without strict source fingerprint rejection. Capture
now rejects moved workspace HEAD before staging. All four reliability TaskSpecs
use the new protocol; fixture templates and all four base commits are unchanged.

This protects official test selection from Agent test edits, deletion, skip and
discovery manipulation, not arbitrary hostile production Python in its own test
process. Historical v1/Pilot/calibration artifacts remain untouched. No real
Codex execution, final manifest, final freeze or final experiments occurred in
this slice.

V1.1.5b1 validation: focused frozen-contract/Run/Replay/repository/provenance/
preparation checks **128 passed, 2 Docker cases skipped**; explicit frozen
Host/Docker parity **2 passed**. Full regression **421 passed, 9 skipped**
(Docker opt-in). All four official frozen buggy baselines retain their original
test/failure/error counts. Compile and `git diff --check` passed; prepared
repositories remain clean at unchanged bases. Integrity checks cover weakened,
deleted, skipped, added and structurally replaced tests, runner collisions,
zero tests, moved HEAD, patch preservation and exception cleanup.

V1.1.5b2 adds the static `evidence/v1.1/freeze-manifest.json` and read-only
`scripts/verify_v11_freeze.py`. The manifest pins the four ordered tasks, exact
TaskSpec bytes and semantic fingerprints, unchanged base commits, official test
blob hashes, accepted evaluator commit/protocol, final execution configuration,
Codex CLI version and the existing Docker image ID/RepoDigest. No accepted source,
fixture or frozen TaskSpec semantics changed from `802c4d3`.

The final configuration is locked to `python -m patchbench.cli`, agent codex,
model gpt-6-astra, 600-second Agent timeout, Docker evaluation and 8 independent
Runs per task: 4 tasks, 32 planned final Runs. Completed FAILs are final evidence;
no retry is authorized merely for FAIL. Genuine infrastructure failures require
separate review rather than silent retry. No final execution occurred during V1.1.5b2 implementation.

`patchbench_evaluator_commit` pins the already accepted implementation. The
separate `freeze_ref`, `refs/tags/v1.1-evidence-freeze`, will identify the accepted
V1.1.5b2 checkout after external review. Embedding that future commit's own SHA
inside its manifest would change its bytes and commit ID recursively; the tag
avoids that self-reference. It was subsequently created by the owner after acceptance.

Static verification permits review-document changes and an absent tag while
checking semantic identities, prepared bases, package import origin, Docker and
Codex identity, and absence of workspace/container residue. Strict preflight adds
a clean root, available freeze tag, HEAD equal to its resolved commit, and no
protected semantic changes since the evaluator checkpoint. It never prepares,
cleans, pulls, modifies artifacts, or creates/moves tags. The model identifier
and CLI version are pinned; remote service implementation is not immutable.

V1.1.5b2 validation: focused verifier checks **34 passed**; full regression
**455 passed, 9 skipped** (Docker opt-in); `compileall` and `git diff --check`
passed. Real `--static` verification passed, while strict preflight correctly
reported the missing `refs/tags/v1.1-evidence-freeze`. Protected semantic diff
against `802c4d3` is empty. Prepared HEADs remain clean and unchanged, with no
`.workspaces` children or running PatchBench sandbox containers.

V1.1.6 final evidence uses exactly four canonical Experiments:

- streaming_events: `f5eb757a1caf466d8d49be3a55dbcb58`, 8 PASS / 0 FAIL;
- request_signing: `71c041b4bc554269b371fdbf98406b50`, 8 PASS / 0 FAIL;
- atomic_batch: `e8ace47d9fef4fae8214ee47c1a8679e`, 8 PASS / 0 FAIL;
- cache_revalidation: `51d9c031f8344db0a64bd8cfddc9c6aa`, 6 PASS / 2 FAIL.

Aggregate: 30/32 end-to-end PASS (93.75%), 30 normally completed Agent executions,
2 COMMAND_FAILED, zero timeouts. All 30 completed executions passed frozen
assessment (100.00% conditional repair success, not unconditional reliability).
The two failed cache Runs, `31f0bc3b57304e6abadcd2136db81592` and
`d741c88639084cdfaba06d27f39cc833`, reported Codex usage limits in persisted
agent.log, produced empty patches and reproduced the unchanged 39-test baseline
(19 failures, 1 error). The quota explanation is release-level interpretation;
platform labels remain agent_command_failed/no_patch/test_failed, overlapping
on the same two Runs. No semantic repair failure or bad patch is claimed.

Exact whole-patch variants are 8/8/8/7; successful production signatures are
8/8/4/1, totaling 21 task-scoped signatures across 30 successful Runs. Exact
hash differences are not semantic algorithm distinctions. Pilot/calibration
Runs remain excluded forever. All final provenance matches the freeze manifest.
The tracked artifacts are `evidence/v1.1/final-results.json` and
`evidence/v1.1/FINAL_REPORT.md`; raw results, frozen semantics and tag are unchanged.

V1.1.6 self-review: **455 passed, 9 skipped**; compileall, JSON parsing and
`git diff --check` passed. Independent canonical-artifact recomputation confirms
32 Runs, 30 PASS, 2 FAIL, 30 completed, 2 command_failed, zero timed_out, and
production diversity 8/8/4/1. All results-tree file hashes remained unchanged;
protected semantic diff against the freeze commit is empty. Strict preflight
passed before edits; release-file changes intentionally make that checkout dirty.

## Git / Development State

- Current branch: `feat/v1.1-evidence-release` (observed during V1.1.0 validation)
- Latest accepted slice: V1.1.6 — Final Evidence Release
- V1.1.6 commit: `7a99c2c docs: publish v1.1 final evidence`
- V1.1.5b2 commit: `94cd287 feat: freeze v1.1 evidence suite`
- V1.1.5b1 commit: `802c4d3 feat: add frozen evaluator contract`
- V1.1.5a commit: `2440af2 feat: add v1.1 reliability suite B candidates`
- V1.1.4 commit: `9af2d28 feat: add v1.1 reliability suite A`
- V1.1.3 commit: `c9a9d2e feat: add experiment analysis workflow`
- V1.1.2 commit: `7222535 feat: add deterministic run evidence`
- V1.1.1 commit: `f2b7020 feat: add minimal run provenance`
- V1.1.0 commit: `51f92a5 feat: add v1.1.0 pilot task discovery`
- M6.1 commit: `974ba5a docs: complete M6.1 public demo`
- M6.2 commit: `fd17c92 docs: complete M6.2 project materials`
- M6 whole-milestone review: accepted before merge
- M5 whole-branch review: accepted before merge
- Exact current commit: obtain from
  `git log -1 --oneline --decorate`
- Last observed `main` and local `origin/main`: `c92db34 — docs: mark PatchBench v1 complete`
  (before the uncommitted V1.1.0 slice; recheck Git for current state).
- M6 merge: `e9cdc76 Merge pull request #8 from
  ldm2023c/feat/m6-demo-docs-polish`
- M5 merge: `223e5de Merge pull request #7 from
  ldm2023c/feat/m5-failure-analysis-replay`

M4 — Repeated Experiments, M5 — Minimal Failure Analysis & Replay, and M6 —
Demo / README / Documentation / Resume polish are complete and merged to
`main`. M6.1 and M6.2 are complete and accepted, and the M6 whole-milestone
review was accepted before merge. PatchBench v1 and the current job-search
completion line are complete. Optional V2 has not started and remains outside
this completion line.

## Completed Milestones

```text
M0 — Foundation                         complete
M1 — Reproducible Local Run             complete
M2 — Docker Evaluation                  complete
M3 — Real Agent Execution               complete
M4 — Repeated Experiments                complete and merged to main
M5 — Minimal Failure Analysis & Replay   complete and merged to main
M6 — Demo / README / Documentation / Resume polish
                                          complete and merged to main
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

- Standalone per-Run failure/comparison CLI and analysis persistence.
- Pair ranking and comparisons beyond Analyze's first PASS/first FAIL example.

## Current M4 State

- **M4.1 — Experiment Domain + Aggregation:** accepted and merged through M4.
- **M4.2 — Sequential Experiment Orchestration:** accepted and merged through
  M4.
- **M4.3 — Experiment CLI + Persistence + E2E:** accepted and merged through
  M4.

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

- **M5.1 — Deterministic Failure Classification:** accepted and merged through
  M5.
- **M5.2 — PASS-vs-FAIL Comparison:** accepted and merged through M5.
- **M5.3 — Replay + CLI + E2E:** accepted and merged through M5.

All three M5 slices and the M5 whole-branch review were accepted before merge.
M5 is complete and merged to `main` at `223e5de` through pull request #7.

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

## Completed M6 State

- **M6.1 — Public Demo & README:** complete and accepted at
  `974ba5a docs: complete M6.1 public demo`.
- **M6.2 — Documentation / Interview / Resume Polish:** complete and accepted
  at `fd17c92 docs: complete M6.2 project materials`.

M6.1 provides the reviewed public README entry point for the reliability
problem, Run-to-Replay workflow, verified Quickstart, programmatic analysis
APIs, artifact ownership, semantic boundaries, and current project scope. M6 as
a whole is complete, its whole-milestone review was accepted before merge, and
M6 was merged to `main` through `e9cdc76`. PatchBench v1 and the current
job-search version are complete. Optional V2 has not started.

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

- Post-M5 deferred work: standalone failure/comparison CLI and analysis persistence.
- Later comparison work: pair ranking, exhaustive Experiment-wide comparison,
  and structural or semantic patch analysis.
- Later failure-analysis work: semantic categories, evaluator timeout
  classification, and infrastructure-abort evidence.
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

Accepted M6.1 review and human copy-paste verification evidence:

```text
README implementation:        complete
CLI/API claims:                verified
staged full-diff review:       complete
wording blocker:               unsupported "versioned TaskSpec" claim removed
incremental blocker review:    accepted
human copy-paste demo:          PASS

Run ID:                        bc6eec282c7647a7a904d049cc45b177
Run agent/evaluation:          COMPLETED / PASS
Experiment ID:                 7671f3fbec42421aa527f9deffa004f4
Experiment results:            3 PASS, 0 FAIL, 100.0% pass rate
Replay ID:                     ab4a46c6559e43c98ffd314558c571b0
Replay source/result/match:    PASS / PASS / YES
Replay evaluation backend:     host
fixture after verification:    clean at expected base commit
temporary workspaces:          cleaned
```

M6.2 documentation evidence:

```text
canonical docs:               reviewed and synchronized
interview notes:              reviewed and consolidated
resume bullets:               reviewed without unsupported claims
production/test changes:      none
Git diff validation:          PASS
M6.2 review state:             accepted
M6 whole review:              accepted before merge
```

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

PatchBench V1.1 is complete and ready to merge into `main` by the human owner.
No further V1.1 implementation or experiment work is required.
Do not move the freeze tag, rerun Agents/experiments, replace failed Runs, or
include raw results/pilot/calibration artifacts in the checkpoint. Strict freeze
preflight intentionally rejects the dirty release checkout; protected semantics
must still match the freeze commit. Optional V2 remains deferred.
