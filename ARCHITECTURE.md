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
                          │
                          ▼
                 Experiment Runner
                          │
          ┌───────────────┼────────────────┐
          │               │                │
          ▼               ▼                ▼
 Repository Manager   Agent Adapter     Evaluator
          │               │                │
          │               ▼                │
          │           Sandbox API          │
          │               │                │
          │               ▼                │
          │         Docker Sandbox         │
          │                                │
          └───────────────┬────────────────┘
                          │
                          ▼
                   Artifact Store
                          │
                          ▼
                       results/
```

The CLI should contain almost no business logic.

The Experiment Runner owns orchestration.

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
```

The domain layer must not depend directly on:

- Docker;
- Codex;
- Git subprocesses;
- CLI libraries;
- databases.

---

## 4. Repository Manager

Responsibilities:

- locate or clone a repository;
- verify the configured base commit;
- create an independent Run workspace;
- restore the workspace to the base commit;
- verify that the working tree begins clean;
- capture the resulting Git patch.

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

Conceptually it should support operations such as:

```text
create()
exec()
copy_in()
copy_out()
destroy()
```

Snapshot support may be added later but is not required for the first version.

Initial implementation:

```text
DockerSandbox
```

Potential future implementations may use other sandbox providers.

PatchBench core logic must not depend directly on Docker-specific behavior.

---

## 6. Agent Adapter

The Agent Adapter encapsulates how a specific coding agent is invoked.

Initial real implementation:

```text
CodexAdapter
```

Before Codex integration, a deterministic:

```text
FakeAgent
```

will be used to validate the orchestration pipeline.

The adapter should eventually:

- construct the agent invocation;
- execute the agent non-interactively;
- provide the task prompt;
- capture stdout/stderr or structured events;
- record execution metadata;
- return a normalized `AgentResult`.

The experiment system must not parse Codex-specific behavior outside `CodexAdapter`.

Future agents should therefore be addable without rewriting the experiment engine.

---

## 7. Codex Execution Model

PatchBench should use Codex's non-interactive execution interface rather than attempting to automate the interactive terminal UI.

Conceptually:

```text
codex exec <prompt>
```

The exact invocation flags and authentication strategy must be implemented and tested separately.

Authentication secrets must never be committed into the PatchBench repository or persisted into Run artifacts.

---

## 8. Evaluator

The Evaluator determines whether the resulting repository satisfies the task.

Initial implementation:

```text
PytestEvaluator
```

The evaluator executes the Task's configured command, for example:

```text
pytest -q
```

and returns normalized information such as:

```text
exit_code
passed
duration
stdout
stderr
```

A Run's PASS/FAIL must be determined by explicit evaluator behavior rather than by the coding agent claiming success.

---

## 9. Artifact Store

The first storage backend should be filesystem-based.

Initial implementation:

```text
FilesystemArtifactStore
```

Conceptual layout:

```text
results/
└── <experiment-id>/
    ├── experiment.json
    ├── run-001/
    │   ├── metadata.json
    │   ├── agent.log
    │   ├── test.log
    │   └── patch.diff
    ├── run-002/
    │   ├── metadata.json
    │   ├── agent.log
    │   ├── test.log
    │   └── patch.diff
    └── ...
```

Artifacts should be treated as immutable after a Run completes.

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

## 11. Proposed Package Structure

```text
patchbench/
├── pyproject.toml
├── README.md
├── PROJECT_SPEC.md
├── ARCHITECTURE.md
├── .gitignore
│
├── docs/
│   └── interview_notes.md
│
├── src/
│   └── patchbench/
│       ├── __init__.py
│       ├── cli.py
│       │
│       ├── domain/
│       │   ├── __init__.py
│       │   └── models.py
│       │
│       ├── config/
│       │   ├── __init__.py
│       │   └── task_loader.py
│       │
│       ├── application/
│       │   ├── __init__.py
│       │   └── experiment_runner.py
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
│       │   ├── base.py
│       │   └── pytest_evaluator.py
│       │
│       └── storage/
│           ├── __init__.py
│           └── filesystem.py
│
├── tests/
├── tasks/
├── experiments/
└── results/
```

Not every module should be created or implemented immediately.

Directories and abstractions should only be added when required by the current milestone.

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

The target MVP Run lifecycle is:

```text
1. Create run_id

2. Load TaskSpec

3. Create isolated workspace

4. Restore workspace to base_commit

5. Verify clean Git state

6. Create Sandbox

7. Execute Agent

8. Capture agent output

9. Capture git diff

10. Execute Evaluator

11. Determine PASS / FAIL

12. Persist:
      metadata.json
      agent.log
      test.log
      patch.diff

13. Destroy Sandbox

14. Delete temporary workspace

15. Return RunRecord
```

Cleanup must execute even when the Agent or Evaluator fails.

---

## 14. Experiment Lifecycle

For:

```bash
patchbench experiment \
    --task bug_001 \
    --agent codex \
    --repeat 5
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

Experiment persistence and CLI composition remain M4.3 work.

An aborted Experiment does not fabricate a Run or partial Experiment record;
already-completed standalone child Run artifacts remain.

---

## 15. Error Handling

Infrastructure errors and coding-task failures must be distinguishable.

Potential statuses include:

```text
CONFIG_ERROR
REPOSITORY_ERROR
SANDBOX_ERROR
AGENT_ERROR
AGENT_TIMEOUT
EVALUATION_ERROR
TASK_FAILED
INTERNAL_ERROR
```

A failed Run should still attempt to persist useful logs and metadata.

Errors must not destroy evidence required for later failure analysis.

---

## 16. Security Boundaries

Initial rules:

- never commit API keys or authentication files;
- never mount the host Docker socket into an untrusted task container;
- never use privileged containers for normal experiments;
- avoid mounting arbitrary host directories;
- use dedicated temporary workspaces;
- destroy containers after execution;
- define CPU, memory, and timeout limits when Docker execution is implemented;
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

After Milestone 4, PatchBench reaches MVP v0.1.

---

## 18. Architecture Decision Rule

Whenever a new feature is proposed, answer these questions first:

1. Is it required for the current milestone?
2. Does it improve reproducibility, reliability analysis, or experiment quality?
3. Can it be implemented after MVP without redesigning the core?
4. Will it create more complexity than evidence?

If the feature is not required now, defer it.
