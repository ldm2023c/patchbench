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
Application: Run / Experiment / Replay
 ├─ GitRepositoryManager
 ├─ Agent (host)
 ├─ Evaluator → optional DockerSandbox
 └─ FilesystemArtifactStore → results/
```

The CLI should contain almost no business logic.

The application layer owns single-Run, sequential-Experiment, and Replay
orchestration. A Run remains the atomic execution unit.

Infrastructure-specific logic belongs in adapters.

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
remain independent labels, and semantic root-cause inference is deferred.

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
patchbench/
├── pyproject.toml
├── README.md
├── PROJECT_SPEC.md
├── ARCHITECTURE.md
├── .gitignore
│
├── docs/
│   ├── DEVELOPMENT.md
│   ├── PROJECT_STATUS.md
│   └── interview_notes.md
│
├── src/
│   └── patchbench/
│       ├── __init__.py
│       ├── cli.py
│       │
│       ├── domain/
│       │   ├── __init__.py
│       │   ├── models.py
│       │   ├── aggregation.py
│       │   ├── failure.py
│       │   └── comparison.py
│       │
│       ├── config/
│       │   ├── __init__.py
│       │   └── task_loader.py
│       │
│       ├── application/
│       │   ├── __init__.py
│       │   ├── local_run.py
│       │   ├── experiment.py
│       │   └── replay.py
│       │
│       ├── repository/
│       │   ├── __init__.py
│       │   └── git_repository.py
│       │
│       ├── sandbox/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── docker.py
│       │
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── codex.py
│       │
│       ├── evaluators/
│       │   ├── __init__.py
│       │   ├── command.py
│       │   └── sandbox.py
│       │
│       └── storage/
│           ├── __init__.py
│           └── filesystem.py
│
├── tests/
├── tasks/
├── fixtures/
├── scripts/
└── results/
```

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

## 17. Milestone Strategy

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
