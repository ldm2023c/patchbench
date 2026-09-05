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

## Future ADR Topics

Potential architecture decisions to record during development:

- Why Docker is used for isolated execution.
- Why MVP uses filesystem storage instead of PostgreSQL.
- Why Runs execute sequentially before introducing concurrency.
- Why Agent implementations use adapters.
- Why evaluator results, rather than agent self-reports, determine PASS/FAIL.
- Why raw artifacts are persisted before building dashboards.
- Why failure classification begins manually before adding LLM automation.
