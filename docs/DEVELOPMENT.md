# PatchBench Development Workflow

This document defines the development and code-review workflow used for PatchBench.

The goal is to keep AI-assisted development reviewable, reproducible, and under explicit human control.

## 1. Roles

### Human owner

The human owner is responsible for:

- project direction;
- architecture decisions;
- milestone scope;
- code review;
- acceptance criteria;
- commits;
- pushes;
- pull requests;
- merges.

### Coding agent

The coding agent may:

- inspect the repository;
- implement explicitly scoped work;
- add or update tests;
- run local verification commands;
- perform self-review.

The coding agent must not, unless explicitly requested:

- change project direction;
- expand milestone scope;
- commit;
- push;
- merge;
- modify Git remotes;
- begin a later milestone.

## 2. Development Unit

Development is organized as:

```text
Milestone
  ↓
Reviewable Slice
  ↓
Implementation
  ↓
Self-review
  ↓
Human runtime verification
  ↓
Git evidence and full-diff review
  ↓
Focused blocker fix and incremental review (when needed)
  ↓
Human commit
```

Large milestones should be divided into reviewable slices rather than implemented in one large change.

A slice should ideally be small enough for its behavior and diff to be understood independently.

## 3. Standard Workflow

For each reviewable slice:

1. Lock design, scope, non-goals, and acceptance checks.
2. Start a short-lived feature branch from the accepted integration branch
   (`main` after the V1.3 finalization line).
3. Codex implements the authorized slice, verifies it, and self-reviews.
4. Codex returns an implementation report with exact status and limitations.
5. The human inspects changes, then stages, commits, and pushes for review.
6. External GitHub review examines the cumulative diff against the version branch.
7. Address findings with focused fixes and regression tests where appropriate;
   the human submits focused fix commits for incremental review.
8. Perform a final cumulative review, not only a review of the latest fix.
9. After acceptance, the human performs an ff-only merge into the version branch,
   pushes it, and optionally cleans up the feature branch.

A commit submitted for review is not acceptance of the slice. The coding agent
does not infer permission to stage, commit, push, or merge from implementation
authorization. Source code + tests + runtime/Git evidence outrank implementation
summaries. Preserve unrelated work and report any mismatch in expected branch.

## 4. Review Packet

A code-review packet should normally contain:

- current milestone / slice goal;
- `git status --short`;
- `git diff --stat` or `git diff --cached --stat`;
- review diff;
- pytest result;
- important runtime evidence or artifacts.

The coding agent's summary is useful for navigation but is not treated as evidence by itself.

Evidence priority is:

```text
source code, tests, runtime evidence, and Git state
> implementation summaries
```

Summaries help navigation but do not override repository or runtime evidence.

## 5. Diff Rules

### Unstaged tracked changes

Use:

```bash
git diff
```

### Staged changes

Use:

```bash
git diff --cached
```

### Feature branch compared with the version branch

After commits exist on the feature branch, use:

```bash
git diff main...HEAD
```

### Important: untracked files

`git diff` does not include untracked files.

Always inspect:

```bash
git status --short
```

before generating a review packet.

Lines beginning with:

```text
??
```

represent untracked files that may otherwise be omitted from review.

## 6. Incremental Review

When an earlier version has already been reviewed and staged, and the coding
agent makes focused fixes:

```text
staging area
= previously reviewed version

working tree
= new incremental fixes
```

In that case:

```bash
git diff
```

can be used to inspect only the incremental modifications to already tracked
files.

Untracked files must still be checked separately with:

```bash
git status --short
```

After incremental review succeeds, stage the latest version and perform a
final full-diff sanity check.

## 7. Regression Tests

When review identifies a possible correctness problem:

```text
suspected bug
  ↓
regression test
  ↓
old behavior fails
  ↓
implementation fix
  ↓
test passes
```

Whenever practical, correctness decisions should become executable tests
rather than remaining only in review discussion.

## 8. Review Artifacts

Temporary files such as:

```text
m1.diff
m1-fix.diff
review.diff
```

are review artifacts only.

They must not be committed to the repository.

Before committing, verify:

```bash
git status --short
```

and remove accidental review files.

## 9. Verification Before Commit

At minimum:

```bash
git diff --check
git status --short
```

Tests, compile checks, and runtime verification depend on the current slice. A
documentation-only slice does not require unrelated implementation tests.

Before the human creates a review commit, required slice checks must pass,
material runtime behavior must be verified where applicable, and staged files
must match scope. External review may then request fix commits. Final cumulative
review and acceptance are required before integration into the version branch.

## 10. Git and PR Policy

Feature development uses short-lived branches off the accepted integration
branch. The human owns staging, commits, pushes, acceptance, ff-only integration,
and branch cleanup. Explicit session authorization governs any exception;
implementation permission alone does not authorize Git publication.

## 11. Scope Discipline

Before adding functionality, ask:

1. Is it required by the current slice?
2. Is it required by the current milestone?
3. Does it improve correctness, reproducibility, or experiment quality now?
4. Can it safely be deferred?

Features outside the current scope should be deferred rather than implemented
speculatively.

## 12. PatchBench Development Principle

AI may generate most implementation code, but project ownership remains human.

Architecture, experimental validity, review, acceptance, and engineering
trade-offs must remain understandable and defensible without relying on the
coding agent's explanation.

## 13. Documentation synchronization checkpoints

After a major version boundary or architecture-changing milestone, explicitly
schedule a documentation synchronization checkpoint. Reconcile public, contract,
architecture, handoff, subsystem, and interview documentation with current exports,
code, tests, runtime artifacts, and Git. Separate implemented/reviewed infrastructure,
planned validation, external blockers, and measured results. Preserve useful
historical status in an explicitly historical archive.

For documentation-only changes, inspect changed Markdown links, search for stale
claims, run `git diff --check` and `git status --short`, and verify permitted file
scope. Full unrelated pytest runs and live experiments are not required solely
for prose edits. Report tests as not run rather than recycling old counts.

## 14. V1.3 formal-study workflow lessons

V1.3 separated design, admission, execution, evidence, and interpretation into
reviewable boundaries:

1. Freeze TaskSpec design and candidate identity before calibration or formal
   execution.
2. Freeze Agent semantics, provider route options, timeout, and exact CLI runtime
   identities before provider calls.
3. Freeze the formal preregistration and reviewed execution sources before
   initializing a production namespace.
4. Admit the actual host runtime before execution. Runtime drift is a stop
   condition; it is not fixed by changing frozen versions to match the host.
5. Execute one slot per state-machine command and persist each attempt before
   continuing.
6. Preserve the fixed denominator. Do not replace failures or select a more
   favorable Run after observing outcomes.
7. Inspect raw incident evidence before interpreting comparative metrics.
8. Correct taxonomy prospectively, preserve historical evidence, and use a
   preregistered full replication instead of rewriting the first study.
9. Freeze compact evidence and derive metrics deterministically only after the
   production ledger is terminal.

Git operations remained human-owned throughout this workflow. Report-level
review verified claims and artifact identities; source-level review verified
contracts, state transitions, and fail-closed behavior. Neither review level
substitutes for the other.

PatchBench V1.3 is final after M20. Additional experiments or features require
a separately scoped future version rather than another V1.3 milestone.
