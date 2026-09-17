# PatchBench Project Specification

## 1. Project Overview

V1.1 is COMPLETE. V1.2 Diagnosis infrastructure and validation machinery are
implemented through D6-R5, including the frozen Validation V1 result artifact.
See [Project Status](docs/PROJECT_STATUS.md).

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

The current workflow retains the completed foundation and adds optional Diagnosis:

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
11. For eligible semantic failures, compile complete bounded evidence and optionally
    infer Blind or same-cell PASS Contrastive hypotheses without revising truth.
12. Audit citations and preserve completed Diagnosis execution artifacts.
13. Score typed Diagnoses against Human Gold, aggregate Blind/Contrastive metrics,
    collect frozen real-provider validation shards, and publish bounded frozen-suite
    Diagnosis results with explicit limitations.

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

## 5. Implemented foundation and V1.2 scope

The completed V1/V1.1 foundation remains implemented:

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

V1.2 Evidence-Grounded Diagnosis infrastructure and validation machinery through
D6-R5 are complete, externally reviewed, and merged into `v1.2`. Official evaluator truth is deterministic and
immutable within Diagnosis. Diagnosis is optional evidence-grounded inference:
it may be uncertain, wrong, or abstain, and never changes official PASS/FAIL.

The programmatic subsystem adds semantic FAIL routing, complete bounded evidence,
Blind Diagnosis, same-cell PASS Contrastive Diagnosis, a deterministic citation
Auditor, and immutable execution artifacts. Blind Diagnosis is the headline mode;
Contrastive Diagnosis is a secondary same-cell PASS ablation. A PASS peer is
comparison evidence, not a reference fix. External inference is opt-in and closed
by default; untrusted evidence framing does not establish prompt-injection
security or private-repository safety. See [Diagnosis](docs/DIAGNOSIS.md).

D6 Human-Gold Validation & Metrics is implemented as deterministic
infrastructure: typed Human Gold contracts, exact Gold identity, route and
semantic scoring, aggregate metrics, exact Blind/Contrastive pairing, paired
transition/delta metrics, and a frozen Diagnosis Validation V1 suite. The suite
contains 15 cases: 13 semantic cases and two operational routing cases. D6-R1/R2
provide a real-provider acquisition runner and deterministic semantic-case
sharding; D6-R3 freezes the selected successful acquisition collection; D6-R4
finalizes semantic scores with human forbidden-claim review; D6-R5 publishes the
final deterministic result artifact.

Frozen real-provider validation completed through a third-party OpenAI-compatible
gateway using the `gpt-6-astra` Pro route label. On the frozen 13 semantic cases,
Blind achieved 9/10 preferred Top-1 and 9/10 acceptable Top-k on non-abstention
cases; Contrastive achieved 8/10 for both. Both modes had 0/3 abstention recall.
The paired comparison showed no family improvement from Contrastive, one family
regression (`semantic-09`), one required-evidence improvement, one
required-evidence regression and one Audit regression. The operational routing
cases were 2/2 correct. These are bounded Validation V1 results, not broad model
reliability or production-diagnosis claims. The
[V1.1 frozen release](evidence/v1.1/FINAL_REPORT.md) remains the completed
empirical coding-agent reliability release: 32 Runs, 30 PASS, two external
Codex quota failures, and 30/30 normally completed executions passing.

Current CLI commands are `validate-task`, `run`, `experiment`, `replay`, and
`analyze`. Diagnosis is an application API with no CLI command.

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

## 8. Foundation reliability metrics

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

Current non-goals are:

- LLM as primary evaluator or changing official PASS/FAIL;
- guaranteed root-cause oracle or causal certainty from a PASS peer;
- automatic reference-fix inference or hidden retrieval/oracle context;
- automatic citation repair or automatic patch repair;
- cross-agent Contrastive peers or multiple-peer selection;
- Diagnosis CLI, production multi-tenant security, distributed execution;
- repository-aware context engine, RAG, and advanced model routing.

Deterministic observable FailureAnalysis and Experiment-wide descriptive Analyze
remain available. V1.2 adds optional semantic hypotheses and canonical same-cell
peer selection; neither makes comparison a causal proof.

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

## 13. Historical definition of V1 success (completed)

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
