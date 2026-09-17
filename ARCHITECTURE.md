# PatchBench Architecture

## 1. Architecture Goals

PatchBench should be designed around four properties:

- reproducibility;
- inspectability;
- replaceable infrastructure adapters;
- incremental implementation.

The architecture must remain simple enough for a local MVP while preserving clear boundaries for future extensions.

---

## 2. High-level Architecture

```text
CLI
 ↓
Application: Run / Experiment / Replay / Analyze
 ├─ GitRepositoryManager
 ├─ Agent (host)
 ├─ Evaluator → optional DockerSandbox
 └─ FilesystemArtifactStore → results/
```

The CLI should contain almost no business logic.

The application layer owns single-Run, sequential-Experiment, and Replay
orchestration, plus read-only Analyze composition. A Run remains the atomic execution unit.

Infrastructure-specific logic belongs in adapters.

---

### V1.2 Diagnosis layers and trust boundaries

D1–D6-R5 infrastructure is implemented and externally reviewed. Diagnosis is an
application API alongside the existing CLI flow; real-provider validation uses a
separate script harness.

```text
L0 deterministic official evaluation (fixed PASS/FAIL)
 ↓ persisted Run + patch + evaluation output
L1 verified evidence ← historical Git + pinned task/benchmark + source policy
 ↓ route_run_diagnosis: completed Agent + official FAIL → semantic eligibility
L2 DiagnosisEvidenceBundle (Blind, or verified same-cell PASS augmentation)
 ↓ explicit external permission + integrity + provider byte gates
   deterministic prompt → DiagnosisProvider → semantic payload only
L3 FailureDiagnosis (PatchBench-owned identity/linkage)
 ↓ audit_failure_diagnosis
L4 deterministic structural/citation Auditor → immutable artifacts
 ↓ completed real-provider acquisition shards feed validation data
L5 Human Gold deterministic scoring
 ↓ exact Blind/Contrastive pairing and aggregate metrics
L6 aggregate + paired validation metrics
 ↓ immutable collection, finalized semantic scores, operational scoring
L7 final frozen-suite validation result artifact
```

Routing itself reads recorded outcomes, not source bytes. Evidence verification
and compilation are separate readiness gates. Official PASS is unavailable for
semantic diagnosis; command failure/timeout with FAIL is operational only.

`DiagnosisSourcePolicy` bounds complete production snapshots. `SubjectProvenance`
binds raw task/patch/log, historical base/candidate snapshots, frozen tests, and
benchmark identity. D2 reconstructs from Run provenance, preserves untouched
source and exact raw content, and fails closed rather than truncating or retrieving.
Compiler-generated paths are canonical repo-relative identities; historical host
path strings inside raw evidence are preserved as data.

D5 selects the first eligible same-cell PASS from persisted Experiment run order.
`PeerProvenance` binds Experiment ID, Run ID, zero-based position, and peer artifact
hashes. Selection has no fallback. Contrastive compilation preserves every Blind
`E` item exactly and appends complete `P` evidence. Execution re-verifies persisted
selection before rendering/provider invocation: a locally valid Bundle/hash alone
is insufficient. A PASS peer is comparison evidence, not a reference fix or causal
oracle. Blind is the headline mode; Contrastive is a secondary ablation.

`DiagnosisProvider` is separate from coding `Agent` and receives textual/schema
input only, with no filesystem, repository, workspace, or shell handles. The
built-in OpenAI Responses adapter explicitly requests no tools, `store=False`,
no truncation, and zero SDK retries. The protocol does not sandbox arbitrary
third-party implementations or prevent their external actions.

PatchBench owns facts and source selection; the provider emits hypotheses only.
Versioned prompts render all evidence in order, preserving artifact-relative LF
line semantics and zero-line evidence. Candidate content is untrusted data, not
an instruction source. Strict semantic output excludes system-owned IDs/linkage;
invalid output is rejected without repair. External permission defaults closed.
There is no secret scanning/redaction or claim of arbitrary-private-repository
safety, adversarial prompt-injection security, or immutable model weights.

`FailureDiagnosis` holds ranked hypotheses or abstention. `DiagnosisAuditResult`
checks structure/citations, not semantic truth. Audit FAIL can be a completed
persisted inference attempt. `DiagnosisExecutionRecord` binds provider provenance,
prompt/schema/payload identity, Diagnosis linkage, and an integrity hash.

D3 storage remains three files; D4/D5 execution storage adds `execution.json`
through distinct four-file APIs. Both are create-only, validate on save/load,
and clean up newly created partial directories. Provider failure creates no
completed Diagnosis artifact.

D6 validation is deterministic infrastructure, not an LLM judge. Human Gold
scoring checks route correctness, abstention, family matches, required evidence,
Auditor issues, and human-reviewed overclaims. D6.2 aggregates exact counts and
paired Blind/Contrastive transitions without a composite winner score. The frozen
Validation V1 suite has 13 semantic cases and two operational routing cases.
D6-R acquisition writes run ledgers under `results/diagnosis-validation-v1/<run-id>/`;
D6-R2 can shard by semantic case while preserving frozen suite order. D6-R3
collects exactly one successful Blind+Contrastive pair per frozen semantic case.
D6-R4 finalizes semantic scores after human forbidden-claim review. D6-R5 writes
the final deterministic result under `results/diagnosis-validation-v1/final-results/`.
See [Diagnosis technical reference](docs/DIAGNOSIS.md) and
[current handoff](docs/PROJECT_STATUS.md). The published Diagnosis metrics are
bounded to the frozen Validation V1 suite and do not establish broad benchmark or
production reliability.

---

## 3. Domain Layer

The domain layer contains data structures and invariants describing PatchBench itself.

Current core domain objects:

```text
TaskSpec
RunRecord
RunStatus
EvaluationResult
AgentExecutionMetadata
ArtifactPaths
ExperimentConfiguration
ExperimentAggregate
ExperimentRecord
FailureCategory
FailureAnalysis
PassFailComparison
ReplayRecord
```

The domain layer must not depend directly on:

- Docker;
- Codex;
- Git subprocesses;
- CLI libraries;
- databases.

### Deterministic Failure Classification

M5.1 classifies directly observable failure conditions through a pure domain
boundary:

```text
RunRecord + already-loaded patch text
                  ↓
       classify_run_failure()
                  ↓
          FailureAnalysis
```

The classifier does not read artifacts or invoke Git, Agents, evaluators,
Sandboxes, network services, or LLMs. Agent outcomes and Evaluation outcomes
remain independent labels. Optional V1.2 Diagnosis adds semantic hypotheses
after routing; it does not change this observable classification.

M5.2 adds an explicit descriptive comparison boundary:

```text
PASS RunRecord + FAIL RunRecord + already-loaded patch text
                           ↓
              compare_pass_fail_runs()
                           ↓
                 PassFailComparison
```

The comparison reuses M5.1 as its sole failure-taxonomy source. Patch presence
uses stripped text while patch equality preserves exact artifact text.
Descriptive comparison records observed differences; it does not establish
causal attribution. Pair selection and filesystem I/O remain outside the
domain function.

M5.3 adds historical-patch Replay as an application lifecycle:

```text
historical RunRecord + canonical patch.diff
                         ↓
fresh worktree at caller-supplied TaskSpec base commit
                         ↓
              apply patch or skip if empty
                         ↓
              existing host/Docker evaluator
                         ↓
                    ReplayRecord
```

Replay invokes no Agent. Evaluation failure and a source/replay outcome
mismatch are completed observations, not infrastructure errors. Replay v1 uses
the caller-supplied TaskSpec and currently selected evaluator backend; it does
not claim to reconstruct the complete historical execution environment.

---

## 4. Repository Manager

Responsibilities:

- verify an existing local repository;
- verify the configured base commit;
- create an independent Run workspace;
- restore the workspace to the base commit;
- verify that the working tree begins clean;
- capture the resulting Git patch.
- apply a canonical historical patch to a fresh Replay workspace.

The original repository must never be directly modified by an experiment.

Each Run must operate on its own workspace.

Temporary workspaces may live under:

```text
.workspaces/<run-id>/
```

This directory must not be committed to Git.

---

## 5. Sandbox

The Sandbox interface represents an execution environment.

The current contract supports:

```text
create()
exec()
destroy()
```

The current implementation is `DockerSandbox`. It bind-mounts at most one Run
workspace at `/workspace` and is used by `SandboxCommandEvaluator`; Agents
remain host-side. It supports bounded argv-style execution, optional CPU and
memory limits, and force-removes the disposable container after an execution
timeout.

PatchBench application logic depends on the Sandbox protocol rather than
Docker-specific behavior. This boundary provides practical evaluator isolation,
not a production-grade hostile multi-tenant security boundary.

---

## 6. Agent Adapter

The Agent Adapter encapsulates how a specific coding agent is invoked.

Initial real implementation:

```text
CodexAdapter
```

The deterministic orchestration test double is:

```text
FakeAgent
```

It validates the orchestration pipeline without external model behavior.

The current application-facing contract is:

```text
Agent.run(AgentRunRequest) -> AgentRunResult

AgentRunRequest:
  workspace, prompt, timeout_seconds

AgentRunResult:
  status, exit_code, stdout, stderr, duration_seconds
```

Only executions that genuinely start return `COMPLETED`, `COMMAND_FAILED`, or
`TIMED_OUT`. Setup, startup, and unsafe process-management failures remain
exceptions. Agent execution is host-side; Docker is not an Agent runtime.

The experiment system must not parse Codex-specific behavior outside `CodexAdapter`.

Future agents should therefore be addable without rewriting the experiment engine.

---

## 7. Codex Execution Model

`CodexAdapter` uses Codex's non-interactive host-side execution interface rather
than automating the interactive terminal UI.

Current invocation shape:

```text
codex exec -C <workspace> --sandbox workspace-write --ephemeral \
  --ignore-user-config --json -m <model> -
```

The model is explicit. A version and login-status preflight runs before Agent
execution, while prompt text is supplied on stdin. Timeout cleanup terminates
and reaps the entire host process group.

Authentication secrets must never be committed into the PatchBench repository or persisted into Run artifacts.

---

## 8. Evaluator

The Evaluator determines whether the resulting repository satisfies the task.

Current implementations:

```text
CommandEvaluator
SandboxCommandEvaluator
```

Both execute the Task's configured argv-style command, for example:

```text
pytest -q
```

and returns normalized information such as:

```text
exit_code
passed
duration_seconds
stdout
stderr
```

A Run's PASS/FAIL is determined by evaluator exit code rather than by the coding
agent claiming success.

---

### Frozen official evaluation (V1.1)

Frozen evaluation uses a separate evaluation worktree and restores baseline tests
before evaluation. Agent-edited tests remain canonical patch evidence but do not
replace frozen test truth. This controls the benchmark's evaluator boundary; it
is not a security guarantee against arbitrary hostile Python execution.

## 9. Artifact Store

The current storage backend is filesystem-based.

Implementation:

```text
FilesystemArtifactStore
```

Conceptual layout:

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

Completed Experiment metadata references its standalone child Run artifact
directories by `run_ids`; it does not duplicate child RunRecord bodies.

Completed Replay metadata references its source Run by `source_run_id`; the
source patch remains canonical in the Run directory and is not duplicated.

Artifacts should be treated as immutable after a Run, Experiment, or Replay
completes.

A database is intentionally unnecessary for the first local MVP.

---

### Diagnosis artifacts (V1.2)

```text
results/diagnoses/<diagnosis-id>/
    bundle.json
    diagnosis.json
    audit.json
    execution.json   # distinct D4/D5 execution API only
```

D3's existing save/load API writes exactly the first three files. The execution
API writes all four as one create-only attempt, with partial-write cleanup and
recomputed hashes/audit/linkage on load. Run/Experiment/Replay artifacts remain
separate. Audit FAIL is persistable; failed provider inference is not a Diagnosis.

## 10. Task Configuration

Task definitions live under:

```text
tasks/
```

Suggested structure:

```text
tasks/
└── example/
    └── task.yaml
```

Task loading should remain separate from CLI parsing.

Proposed data flow:

```text
YAML
 ↓
TaskLoader
 ↓
schema validation
 ↓
TaskSpec
```

Invalid configuration should fail early with a readable error message.

---

## 11. Package Structure

```text
src/patchbench/
├── __init__.py
├── agents/
│   ├── __init__.py
│   ├── base.py
│   ├── codex.py
│   ├── fake.py
├── application/
│   ├── __init__.py
│   ├── analysis.py
│   ├── diagnosis_contrastive.py
│   ├── diagnosis_evidence.py
│   ├── diagnosis_execution.py
│   ├── diagnosis_gold_lock.py
│   ├── diagnosis_metrics.py
│   ├── diagnosis_peer.py
│   ├── diagnosis_prompt.py
│   ├── diagnosis_suite.py
│   ├── diagnosis_validation.py
│   ├── diagnosis_validation_collection.py
│   ├── diagnosis_validation_results.py
│   ├── diagnosis_validation_run.py
│   ├── diagnosis_validation_scoring.py
│   ├── evaluation.py
│   ├── experiment.py
│   ├── local_run.py
│   ├── replay.py
├── cli.py
├── config/
│   ├── __init__.py
│   ├── task_loader.py
├── domain/
│   ├── __init__.py
│   ├── aggregation.py
│   ├── analysis.py
│   ├── comparison.py
│   ├── diagnosis.py
│   ├── diagnosis_audit.py
│   ├── diagnosis_execution.py
│   ├── diagnosis_gold_lock.py
│   ├── diagnosis_integrity.py
│   ├── diagnosis_metrics.py
│   ├── diagnosis_suite.py
│   ├── diagnosis_validation.py
│   ├── diagnosis_validation_collection.py
│   ├── diagnosis_validation_results.py
│   ├── diagnosis_validation_run.py
│   ├── diagnosis_validation_scoring.py
│   ├── evaluation_evidence.py
│   ├── evidence_errors.py
│   ├── failure.py
│   ├── models.py
│   ├── patch_evidence.py
│   ├── provenance.py
├── evaluators/
│   ├── __init__.py
│   ├── command.py
│   ├── frozen_runner.py
│   ├── sandbox.py
├── providers/
│   ├── __init__.py
│   ├── base.py
│   ├── openai.py
├── repository/
│   ├── __init__.py
│   ├── git_repository.py
├── sandbox/
│   ├── __init__.py
│   ├── base.py
│   ├── docker.py
├── storage/
│   ├── __init__.py
│   ├── filesystem.py
```

Documentation includes the current handoff, this architecture, and
[DIAGNOSIS.md](docs/DIAGNOSIS.md). Tests, tasks, fixtures, scripts, frozen evidence,
and runtime results remain separate top-level directories.

---

## 12. Dependency Direction

Preferred dependency direction:

```text
CLI
 ↓
Application
 ↓
Domain + Interfaces
 ↑
Infrastructure Adapters
```

The core domain model should know nothing about:

```text
Docker
Codex
Typer
Git CLI
pytest CLI
PostgreSQL
Redis
```

This boundary keeps infrastructure replaceable and the system understandable.

---

## 13. Run Lifecycle

The implemented Run lifecycle is:

```text
1. Create run_id

2. Load TaskSpec

3. Create isolated workspace

4. Restore workspace to base_commit

5. Verify clean Git state

6. Execute Agent on the host

7. Capture agent stdout/stderr

8. Stage workspace changes and capture a binary-capable canonical Git patch

9. Execute the Evaluator on the host or in a disposable Docker sandbox

10. Determine PASS / FAIL independently from Agent status

11. Destroy an optional evaluation Sandbox

12. Persist:
      metadata.json
      prompt.txt
      agent.log
      agent.stderr.log
      test.log
      patch.diff

13. Delete the temporary workspace

14. Return RunRecord
```

Cleanup executes across normal failure outcomes and hard exceptions. Agent
setup/infrastructure exceptions propagate and do not fabricate a RunRecord.

---

## 14. Experiment Lifecycle

For:

```bash
patchbench experiment \
    --task tasks/example/task.yaml \
    --agent codex \
    --model <model> \
    --runs 5
```

the application layer conceptually performs:

```text
Experiment
 │
 ├── Run #1
 ├── Run #2
 ├── Run #3
 ├── Run #4
 └── Run #5
       │
       ▼
 Aggregate Metrics
       │
       ▼
 Experiment Report
```

Completed-Experiment aggregation:

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

M4.1 defines the completed-Experiment domain and pure aggregation from a
non-empty sequence of `RunRecord` values. Evaluation metrics come from
`RunRecord.evaluation_passed`; agent failure and timeout counts come
independently from `RunRecord.agent.status`.

M4.2 loads one TaskSpec for the Experiment, freezes one ExperimentConfiguration,
and executes child Runs sequentially through the existing single-Run lifecycle.
A minimal Agent factory callable supplies a fresh Agent for each child Run.

M4.3 adds CLI composition for the selected Agent, model, agent timeout, and
host-or-Docker evaluation backend. After M4.2 returns a fully completed
ExperimentRecord, the filesystem artifact store persists that record at
`results/experiments/<experiment-id>/metadata.json` and the CLI prints separate
Evaluation, Agent, Duration, and Artifacts summary sections.

An aborted Experiment does not fabricate a Run or partial Experiment record;
already-completed standalone child Run artifacts remain and no completed
Experiment metadata is written. A metadata persistence failure remains a
storage failure and may likewise leave completed child Run artifacts.

### Replay Lifecycle

M5.3 safely loads one historical RunRecord and canonical patch, checks that its
task matches a caller-supplied TaskSpec, creates a fresh detached worktree at
that TaskSpec's base commit, applies the exact non-empty Git patch (or evaluates
the clean base for an empty patch), and uses the existing host or Docker
evaluation path. It then persists only completed Replay metadata and evaluator
output under `results/replays/<replay-id>/`.

Patch-application and infrastructure failures propagate without a completed
ReplayRecord. A replayed test failure or outcome mismatch is a valid completed
Replay and remains CLI success. Worktree and optional Sandbox cleanup use the
existing lifecycle boundaries.

---

### Analyze Lifecycle

```text
persisted Experiment + ordered child raw Run evidence
                         ↓
              read-only integrity checks
                         ↓
                 ExperimentAnalysis
```

The filesystem store loads Experiment metadata and child metadata, patches,
and test logs through safe ID namespaces. Analyze recomputes evidence from raw
artifacts and cross-checks cached summaries when present. It verifies Run
outcomes, child configuration, common provenance, and the recomputed aggregate.
Historical records may lack summaries or provenance; evidence is reconstructed
in memory and missing provenance remains unavailable. Mixed or conflicting
provenance is rejected.

The result preserves child order, counts exact patch hashes, reuses the existing
failure classifier, and compares the first PASS and first FAIL when both exist.
CLI renders text or JSON. Analyze does not invoke execution infrastructure or
persist results; the raw artifacts remain unchanged and canonical.

---

## 15. Failure and Error Semantics

Infrastructure errors and completed reliability observations are distinct.

Agent executions that genuinely start return exactly:

```text
COMPLETED
COMMAND_FAILED
TIMED_OUT
```

All returned Agent outcomes continue through patch capture and evaluation;
therefore `COMMAND_FAILED` or `TIMED_OUT` does not imply Evaluation FAIL.
Evaluation PASS/FAIL is recorded separately from Agent status.

Task loading, repository, Agent setup/infrastructure, Sandbox lifecycle, patch
application, and artifact-storage failures remain exceptions. They abort the
active lifecycle rather than becoming a synthetic Run failure category.

---

## 16. Security Boundaries

Initial rules:

- never commit API keys or authentication files;
- never mount the host Docker socket into an untrusted task container;
- never use privileged containers for normal experiments;
- avoid mounting arbitrary host directories;
- use dedicated temporary workspaces;
- destroy containers after execution;
- apply bounded evaluator execution and optional Docker CPU/memory limits;
- do not assume Docker provides a production-grade hostile multi-tenant security boundary.

PatchBench MVP focuses on reproducibility and practical isolation, not production multi-tenant sandbox security.

---

## 17. Historical V1 milestone strategy (completed)

### Milestone 0 — Project Skeleton

Implement only:

- Python package;
- CLI;
- domain models;
- YAML Task loader and validation;
- example task configuration;
- unit tests.

No real Docker execution.

No real Codex execution.

Acceptance criteria:

```bash
pytest
patchbench --help
patchbench validate-task tasks/example/task.yaml
```

must all succeed.

### Milestone 1 — Deterministic Local Run

Implement:

- Git workspace management;
- evaluator;
- Run lifecycle;
- patch capture;
- artifact persistence;
- deterministic FakeAgent.

This validates the orchestration pipeline without depending on Codex.

### Milestone 2 — Docker Execution

Implement:

- Sandbox interface;
- DockerSandbox;
- resource/time limits;
- reliable cleanup.

### Milestone 3 — Codex Integration

Implement:

- CodexAdapter;
- non-interactive Codex execution;
- agent logs;
- authentication boundary;
- end-to-end coding task.

### Milestone 4 — Repeat Experiment

Implement:

- repeated independent Runs;
- experiment aggregation;
- Pass Rate;
- average duration;
- experiment report.

### Milestone 5 — Minimal Failure Analysis & Replay

Implemented:

- deterministic directly-observable failure classification;
- explicit descriptive PASS-vs-FAIL comparison;
- historical patch Replay with zero Agent executions.

### Milestone 6 — Demo and Documentation

Public README/demo work and implementation-grounded documentation polish form
the final job-search presentation milestone. Optional V2 features remain
outside this completion line.

---

## 18. Architecture Decision Rule

Whenever a new feature is proposed, answer these questions first:

1. Is it required for the current milestone?
2. Does it improve reproducibility, reliability analysis, or experiment quality?
3. Can it be implemented after MVP without redesigning the core?
4. Will it create more complexity than evidence?

If the feature is not required now, defer it.
