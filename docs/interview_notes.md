# PatchBench Interview Notes

This file records architecture decisions, trade-offs, experiments, failures and lessons learned during development.

---

## ADR-001: Why CLI-first?

### Decision

Start PatchBench as a local CLI tool instead of building a web application.

### Reason

The core value of PatchBench is reproducible coding-agent experimentation and failure analysis, not frontend presentation.

CLI-first reduces unrelated engineering work and lets the project validate its core experiment loop earlier.

### Trade-off

The project is initially less visually impressive, but a dashboard can be added after the experiment engine becomes stable.

---

## ADR-002: Why FakeAgent before CodexAdapter?

### Decision

Validate the complete experiment pipeline using a deterministic fake agent before integrating Codex.

### Reason

This isolates PatchBench orchestration bugs from:

- Codex authentication;
- external network behavior;
- model nondeterminism;
- sandbox problems;
- agent-specific failures.

The FakeAgent allows the system to verify:

```text
Task
 ↓
Workspace
 ↓
Agent
 ↓
Patch
 ↓
Evaluator
 ↓
Artifact persistence
```

without relying on an external AI system.

### Trade-off

It adds a small amount of temporary implementation, but substantially improves debuggability and makes failures easier to attribute.

---

## ADR-003: Why detached Git worktrees for local Runs?

### Decision

Create a separate detached Git worktree at the configured base commit for every local Run.

### Reason

A detached worktree gives the Run an independent filesystem while preserving an exact, Git-verified starting commit. Agent edits and evaluator byproducts remain outside the source repository, and Git can capture the resulting patch directly.

### Trade-off

The source must be an existing local Git repository, and worktree registration must be cleaned up even when execution fails. Milestone 1 handles this with a context-managed lifecycle and does not clone remote repositories.

---

## ADR-004: Why use the Docker CLI before adding an SDK?

### Decision

Use explicit Docker CLI subprocess calls for the initial sandbox lifecycle.

### Reason

Milestone 2.1 needs only container creation and destruction. The installed Docker CLI already exposes those operations, keeps the dependency set small, and makes the exact lifecycle commands inspectable.

### Trade-off

CLI failures require explicit return-code and stderr handling. If later sandbox behavior becomes substantially more complex, the implementation choice can be reevaluated using evidence from those requirements.

---

## ADR-005: Why one fixed workspace mount and argv-style commands?

### Decision

Milestone 2.2 accepts at most one host workspace, mounts it read-write at `/workspace`, and represents container commands as explicit argument sequences.

### Reason

A single fixed mount makes host exposure easy to inspect and avoids introducing a general volume policy before it is needed. Argument sequences preserve command boundaries without shell parsing or `shell=True`.

### Trade-off

The container path and working directory are intentionally fixed, and ownership of files created through the bind mount follows Docker's host/container UID behavior. Broader mount and identity policies are deferred.

---

## Future ADR Topics

Potential architecture decisions to record during development:

- Why Docker is used for isolated execution.
- Why MVP uses filesystem storage instead of PostgreSQL.
- Why Runs execute sequentially before introducing concurrency.
- Why Agent implementations use adapters.
- Why evaluator results, rather than agent self-reports, determine PASS/FAIL.
- Why raw artifacts are persisted before building dashboards.
- Why failure classification begins manually before adding LLM automation.
