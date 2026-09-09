# PatchBench Project Specification

## 1. Project Overview

**Project Name:** PatchBench

**Positioning:** Coding Agent Reliability & Failure Analysis Platform

**One-line Description:**

> A reproducible experimentation platform for evaluating, diagnosing and improving coding-agent reliability on real software repositories.

PatchBench is not primarily a leaderboard for comparing coding agents.

Its goal is to study and engineer around a more practical reliability problem:

> Why can the same coding agent succeed on the same task in one Run and fail in
> another, which directly observable failure conditions occur, and whether the
> same frozen configuration behaves reliably across repeated Runs.

---

## 2. Core Problem

A single successful coding-agent run does not establish reliability.

For a repository-level coding task, an agent may:

- succeed in some runs and fail in others;
- inspect different files across runs;
- exhibit different directly observable failure conditions;
- produce incomplete or regressive patches;
- spend very different amounts of time or tokens;
- fail because of the environment rather than reasoning.

The core experimental unit is:

> Task × Agent Configuration × Repeated Runs

---

## 3. Project Goals

PatchBench v1 supports the following workflow:

1. Define a reproducible repository-level coding task.
2. Restore the repository to a known base commit.
3. Execute a FakeAgent or CodexAdapter on the host in a fresh Git worktree.
4. Capture Agent stdout/stderr and a canonical Git patch.
5. Automatically evaluate the resulting repository.
6. Persist all artifacts and metadata from the run.
7. Repeat the same experiment multiple times.
8. Aggregate Evaluation pass/fail, Agent command-failure/timeout, and duration
   metrics.
9. Classify directly observable failure conditions.
10. Descriptively compare an explicit PASS/FAIL pair or Replay a historical
    patch without rerunning an Agent.

---

## 4. Core Concepts

### 4.1 Task

A Task describes what problem must be solved.

A Task contains:

- unique task ID;
- repository source;
- base commit;
- task prompt;
- evaluation command;
- timeout configuration;
- optional metadata.

A Task must not contain a specific agent implementation.

### 4.2 Experiment

An Experiment is an ordered collection of completed independent Runs under one
frozen execution configuration.

An Experiment combines:

- one task ID;
- one frozen Agent/evaluation configuration;
- N sequential independent Runs;
- aggregate metrics and child `run_ids`.

A hard setup or infrastructure exception aborts the Experiment and propagates;
PatchBench v1 does not fabricate or persist a partial Experiment record.

### 4.3 Run

A Run is the atomic execution unit. It may be executed alone or as one child of
an Experiment.

Every Run must have a unique identifier and its own artifacts.

Each completed Run persists:

```text
metadata.json
prompt.txt
agent.log
agent.stderr.log
test.log
patch.diff
```

### 4.4 Artifact

Artifacts are persisted evidence owned by a Run, Experiment, or Replay.

Examples include:

- agent logs;
- generated patches;
- evaluator logs;
- metadata;
- Experiment or Replay metadata.

Each Run owns its execution evidence and patch. An Experiment owns aggregate
metadata and child `run_ids`; a Replay owns new metadata/evaluation log and
references, rather than duplicates, the source Run patch.

---

## 5. Current V1 / Job-search Scope

The implemented local v1 scope is:

- Task specification;
- task configuration validation;
- fresh detached Git worktree creation at a known base commit;
- host-side deterministic FakeAgent and CodexAdapter execution;
- optional Docker-backed evaluator isolation;
- automatic configured evaluation-command execution;
- patch capture;
- run metadata collection;
- N sequential independent Runs per Experiment;
- pass-rate calculation;
- Run and aggregate duration measurement;
- filesystem-based result persistence;
- deterministic directly-observable FailureAnalysis;
- descriptive explicit PASS-vs-FAIL comparison;
- historical patch Replay with zero Agent executions.

The current CLI form is:

```bash
patchbench experiment \
    --task <task-yaml-path> \
    --agent codex \
    --model <model> \
    --runs <N>
```

Example output:

```text
Experiment ID: <experiment-id>
Task ID:       cache_bug_001
Runs:          5

Evaluation:
  PASS:      3
  FAIL:      2
  Pass rate: 60.0%

Agent:
  Command failed: 1
  Timed out:      0
```

---

## 6. Reproducibility Requirements

Every repeated Run should begin from an equivalent state.

At minimum:

- the same repository base commit;
- a clean working tree;
- the same Task specification;
- the same frozen Agent configuration and evaluator choice;
- an independent workspace for every Run;
- immutable persisted artifacts after completion.

PatchBench records structured evidence for inspection and patch Replay. It does
not claim to freeze external model behavior, every host dependency, or the
complete historical execution environment.

---

## 7. Current Task Format

The current task configuration format is YAML.

Conceptual example:

```yaml
schema_version: 1

id: example_bug

repository:
  type: local
  path: fixtures/example_repo
  base_commit: "<git-commit>"

task:
  prompt: |
    Fix the bug described in the repository.

evaluation:
  command: "pytest -q"
  timeout_seconds: 120

metadata:
  language: python
```

The current schema accepts exactly `schema_version: 1` and rejects unknown
fields.

---

## 8. Current V1 Metrics

Required v1 metrics:

- run status;
- pass / fail;
- total duration;
- experiment run count;
- experiment pass count;
- experiment pass rate;
- total, mean, minimum, and maximum child-Run duration;
- Agent command-failure and timeout counts.

Optional metrics, when reliably exposed by the agent:

- token usage;
- model name;
- agent step count.

Optional metrics remain outside the v1 completion requirements.

---

## 9. Failure Analysis, Comparison, and Replay

PatchBench v1 implements a deliberately narrow, deterministic failure-analysis
boundary. `FailureAnalysis` reports only these directly observable labels:

```text
AGENT_COMMAND_FAILED
AGENT_TIMED_OUT
NO_PATCH
TEST_FAILED
```

These categories are not semantic root causes. Infrastructure/setup failures
remain exceptions and are not added to a completed Run's failure taxonomy.

`PassFailComparison` accepts one explicit PASS Run and one explicit FAIL Run
from the same task with different Run IDs. It compares already-loaded evidence
deterministically and descriptively; it does not select pairs or infer causes.

Replay loads a completed historical Run and canonical patch, creates a fresh
worktree at the base commit from a caller-supplied TaskSpec, applies or skips
the patch, and uses the existing host or Docker evaluator. Replay invokes zero
Agents and does not claim full historical environment reconstruction.

---

## 10. Explicit Non-goals and Deferred Work

The following are explicitly outside PatchBench v1:

- Kubernetes;
- distributed execution clusters;
- Firecracker or custom microVM implementation;
- custom container runtime;
- complicated frontend;
- supporting many coding agents;
- large-scale SWE-bench integration;
- semantic root-cause inference or an automatic LLM diagnosis oracle;
- automatic PASS/FAIL pair selection or Experiment-wide comparison;
- parallel or distributed Experiment execution;
- a complete historical environment snapshot system;
- repository-aware context engine;
- RAG system;
- advanced model routing;
- production multi-tenant security.

V1 remains local, small, inspectable, and reproducible.

---

## 11. Optional V2 Directions

### Repository-aware Context Engine

Potential techniques:

- AST analysis;
- symbol dependency graph;
- import/call graph;
- git history;
- context ranking.

The effectiveness of context optimization must be evaluated using downstream coding-agent success rather than subjective demonstrations.

### Service Architecture

Potential additions:

- FastAPI;
- PostgreSQL;
- Redis;
- worker queue;
- simple dashboard;
- OpenTelemetry.

These are not required until the local experiment engine is stable.

---

## 12. Engineering Principles

PatchBench follows several strict engineering principles:

1. **CLI first.**  
   The core system must work without a web frontend.

2. **Reproducibility before scale.**  
   Five trustworthy runs are more valuable than five hundred uncontrolled runs.

3. **Explicit interfaces.**  
   Agent, sandbox, evaluator, repository, and artifact-storage implementations should be replaceable.

4. **Artifacts before dashboards.**  
   Raw evidence must always be preserved.

5. **Small milestones.**  
   Every milestone must have executable acceptance criteria.

6. **No fabricated metrics.**  
   Resume and project claims must use real measured results.

7. **AI-generated code must remain explainable.**  
   Implementation may be heavily assisted by coding agents, but architecture and engineering decisions must remain understandable and defensible by the project owner.

---

## 13. Definition of V1 Success

The local job-search v1 completion line is satisfied when the real CLI can run
an Experiment such as:

```bash
patchbench experiment \
    --task tasks/example/task.yaml \
    --agent codex \
    --model <model> \
    --runs 5
```

and produces:

- five independent Runs;
- the same initial repository state for every Run;
- host-side Agent execution with optional Docker-backed evaluation;
- automatic evaluation;
- PASS/FAIL for every Run;
- aggregate Pass Rate;
- Agent command-failure/timeout and duration aggregates;
- persistent per-run artifacts containing at least:

```text
metadata.json
prompt.txt
agent.log
agent.stderr.log
test.log
patch.diff
```

The v1 completion line also includes deterministic observable failure
classification, descriptive explicit PASS-vs-FAIL comparison, and historical
patch Replay. Optional V2 work is not required for v1 completion.
