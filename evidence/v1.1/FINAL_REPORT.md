# PatchBench V1.1 Evidence Release

## Executive Summary

The fixed final sample contains 32 Runs across four purpose-built realistic
repository tasks. Frozen evaluation passed for 30/32 Runs (93.75% end-to-end).
All 30 normally completed Codex executions passed frozen evaluation (30/30,
100.00% conditional repair success). Two executions ended in external Codex
usage-quota command failures before producing patches. There were zero timeouts.
V1.1 implementation/evidence is complete, pending final external review.

## Frozen Protocol

The accepted freeze is `refs/tags/v1.1-evidence-freeze`, resolving to
`94cd2873c42af7f5c697e6316316c9cb59fc6d8b`. The evaluator checkpoint is
`802c4d3dcc09d89400ca306eae253b5ef585d442`. The [freeze manifest](freeze-manifest.json)
pins TaskSpec bytes/fingerprints, base commits and official test blob hashes.

Execution was locked to `python -m patchbench.cli`, agent `codex`, model identifier
`gpt-6-astra`, Codex CLI `codex-cli 0.153.4`, a 600-second Agent timeout, Docker
evaluation, and eight independent Runs per task. The manifest pins the existing
`python:3.12-slim` image ID and RepoDigest; evaluation timeout is 120 seconds.
Strict preflight was required before final execution and passed again on the
clean freeze checkout before these release edits. Per-Run provenance matches
manifest task/base/command/backend/model settings; CLI/image identity is pinned
by the manifest and environment preflight, not separate per-Run runtime fields.

Agent-visible tests remained inspectable and editable. PatchBench captured the
complete Agent patch, applied it to a second exact-base worktree, restored the
frozen baseline test bytes and injected its trusted runner. Official evaluation
used `python -I -S -B .patchbench-eval/runner.py`, loading only declared tests.
Agent test edits remain patch evidence but cannot replace the official tests.
This is evaluator immutability, not security against arbitrary hostile production
Python interfering with its own test process.

Pilot and calibration Runs are permanently excluded. No new executions or
replacement Runs were made for this release. A completed FAIL remains part of
the predefined sample; replacing either failed Run would change the protocol.

## Final Results

| Task | Experiment ID | PASS / FAIL | End-to-end rate | Frozen tests per Run |
|---|---|---|---|---|
| streaming_events | f5eb757a1caf466d8d49be3a55dbcb58 | 8 / 0 | 100.00% | 33 |
| request_signing | 71c041b4bc554269b371fdbf98406b50 | 8 / 0 | 100.00% | 35 |
| atomic_batch | e8ace47d9fef4fae8214ee47c1a8679e | 8 / 0 | 100.00% | 36 |
| cache_revalidation | 51d9c031f8344db0a64bd8cfddc9c6aa | 6 / 2 | 75.00% | 39 |
| Total | Four Experiments, 32 Runs | 30 / 2 | 93.75% | Task-specific |

End-to-end pass rate includes Agent-service availability/quota behavior.
Conditional repair success is 30/30 among normally completed Agent executions;
it is not an unconditional 100% reliability claim. Cache revalidation's 6/8 is
not a 75% semantic repair success estimate: neither failed execution produced a
candidate repair.

## Failure Interpretation

Both failed Runs belong to cache_revalidation:

- `31f0bc3b57304e6abadcd2136db81592`: Codex started, inspected repository files
  and ran the raw baseline suite, then reported `You've hit your usage limit.`
  before producing a patch.
- `d741c88639084cdfaba06d27f39cc833`: Codex started and almost immediately
  reported the same usage-limit error, without producing a patch.

Each persisted Run has agent status `command_failed` (COMMAND_FAILED), exit code
1 and zero patch bytes. The frozen evaluator therefore tested the unchanged
buggy base: 39 tests, 19 failures and 1 error. Both retain the overlapping
platform labels `agent_command_failed`, `no_patch`, `test_failed`. Those labels
refer to two Runs, not six independent failures.

The release-level interpretation `external_codex_usage_quota` is grounded in
persisted `agent.log`, whose paths and hashes are recorded in
[final-results.json](final-results.json). It is not a new domain category or an
automatically inferred causal classification. These are external service/account
quota failures, not semantic repair failures or model-generated bad patches.
No retry or failed-Run replacement was performed.

## Patch / Implementation Diversity

| Task | Exact whole-patch variants, all Runs | Successful Runs | Successful production signatures |
|---|---:|---:|---:|
| streaming_events | 8 | 8 | 8 |
| request_signing | 8 | 8 | 8 |
| atomic_batch | 8 | 8 | 4 |
| cache_revalidation | 7 | 6 | 1 |

A production signature is the exact sorted tuple of `(file.path,
file.diff_sha256)` for PatchSummary files with `role == "non_test"`. Counts use
successful Runs only and are grouped within each task. The sum is 21 task-scoped
successful production signatures across 30 successful Runs; it is not a
cross-task semantic equivalence metric. Roles are PatchBench's descriptive path
classification, and different diff hashes do not prove different algorithms.

Streaming events and request signing showed high exact production variation
despite identical successful outcomes. Atomic batch's eight whole patches
collapse to four production signatures, so whole-patch diversity overstates
implementation diversity. Cache revalidation shows the strongest convergence:
all six successful Runs share one production signature, while Agent-authored
test edits account for differing successful whole patches. Its seventh
whole-patch variant is the empty patch shared by the two quota failures.

**Exact whole-patch variants are not semantic or production implementation
variants.** This distinction is an observed V1.1 result.

## What the Evidence Supports

- A fixed 32-Run sample was executed and retained without replacing failures.
- All 30 normally completed executions produced patches passing the frozen
  evaluator, with task-dependent degrees of exact implementation convergence.
- PatchBench separates Agent execution outcomes from evaluator outcomes and
  preserves raw patches/logs plus verifiable task/evaluation provenance.
- Persisted logs support a quota explanation for the two command failures;
  platform failure labels alone do not establish that explanation.

## What the Evidence Does Not Support

The sample is four purpose-built realistic tasks, one model identifier, one
Codex CLI version, one frozen Docker environment and eight Runs per task.
External quota affected 2/32 Runs. It is not statistically representative of
all repositories, tasks or coding agents and does not establish general coding
reliability. Remote model weights/service implementation were not immutable.
No result demonstrates that PatchBench automatically identifies causal root
causes or that every distinct production signature is semantically distinct.

## Reproduction / Audit References

- [Freeze manifest](freeze-manifest.json): task/base/test identities and execution
  configuration. Keep the freeze tag and manifest unchanged.
- [Final results](final-results.json): canonical Experiment-order Run IDs,
  per-Run verdict/status/patch signatures/test counts/failure labels, aggregates
  and external-failure evidence references.
- Canonical private artifacts: `results/experiments/<experiment-id>/metadata.json`
  and `results/<run-id>/{metadata.json,patch.diff,test.log,agent.log}`. These raw
  artifacts remain local and unchanged; the tracked report is an audited summary,
  not a substitute for access to those artifacts.
- Existing read-only audit: `python -m patchbench.cli analyze --experiment <ID> --json`
  for each of the four IDs above. The analyzer recomputes raw patch/log summaries
  and cross-checks stored evidence and aggregates; release checks additionally
  compare provenance with the freeze manifest and count production signatures.
- `python -m scripts.verify_v11_freeze` requires the clean tagged execution
  checkout. It intentionally fails on the dirty release-documentation checkout;
  protected-semantic diff checks remain applicable here. Do not rerun experiments
  to audit the existing sample.
