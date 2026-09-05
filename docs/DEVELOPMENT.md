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
Verification
  ↓
Review
  ↓
Commit
```

Large milestones should be divided into reviewable slices rather than implemented in one large change.

A slice should ideally be small enough for its behavior and diff to be understood independently.

## 3. Standard Workflow

For each reviewable slice:

```text
1. Start from an up-to-date main branch.

2. Create or switch to the milestone feature branch.

3. Give the coding agent a narrowly scoped implementation prompt.

4. Coding agent implements the slice and runs tests.

5. Coding agent performs a critical self-review.

6. Human independently runs important verification commands.

7. Inspect:

   git status --short

8. Stage the intended implementation files.

9. Generate a review diff.

10. Perform architecture and implementation review.

11. When a possible correctness bug is identified, prefer adding a
    regression test instead of resolving the disagreement by opinion.

12. Coding agent performs focused fixes only.

13. Review the incremental fix diff.

14. Perform a final full-diff sanity check.

15. Human commits the accepted slice.

16. After the milestone is complete, push the feature branch and open a PR.

17. Merge only after milestone acceptance.
```

## 4. Review Packet

A code-review packet should normally contain:

- current milestone / slice goal;
- `git status --short`;
- `git diff --stat` or `git diff --cached --stat`;
- review diff;
- pytest result;
- important runtime evidence or artifacts.

The coding agent's summary is useful for navigation but is not treated as evidence by itself.

Source code, tests, Git state, and runtime artifacts are the primary evidence.

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

### Feature branch compared with main

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
pytest
git diff --cached --check
git status
```

Additional runtime verification depends on the current milestone.

A commit is created only after:

- required tests pass;
- important runtime behavior is independently verified;
- code review is complete;
- no unintended file is staged.

## 10. Git and PR Policy

Feature development should not occur directly on `main`.

Typical flow:

```text
main
  ↓
feature branch
  ↓
implementation commits
  ↓
Pull Request
  ↓
review
  ↓
merge
  ↓
main
```

The coding agent does not decide when work is committed, pushed, or merged.

## 11. Scope Discipline

Before adding functionality, ask:

1. Is it required by the current slice?
2. Is it required by the current milestone?
3. Does it improve correctness, reproducibility, or experiment quality now?
4. Can it safely be deferred?
git status
Features outside the current scope should be deferred rather than implemented
speculatively.

## 12. PatchBench Development Principle

AI may generate most implementation code, but project ownership remains human.

Architecture, experimental validity, review, acceptance, and engineering
trade-offs must remain understandable and defensible without relying on the
coding agent's explanation.