# Frozen V1.1 reliability suite — Suites A and B

These are purpose-built realistic software repositories. They are not imported
upstream bug reports or observed production bugs and claim no external provenance.
The four tasks were frozen at `v1.1-evidence-freeze`, commit
`94cd2873c42af7f5c697e6316316c9cb59fc6d8b`, after V1.1.5b2 acceptance.
All Suite A/B calibration Runs remain **NON-FINAL forever**, even where the
fixture definitions were selected unchanged. Pilot/calibration Runs are excluded
from the final 32-Run sample.

`streaming_events` models an NDJSON event-log importer: incremental byte-stream
state, record framing, UTF-8 boundaries, byte limits, error reporting and reader
integration. `request_signing` models webhook HMAC signing: lossless request
representation, deterministic query/header canonicalization and shared signing
and verification. Each repository has a public contract and a complete visible
unittest suite. Both use only the Python 3.12 standard library.

Suite A was externally accepted at `9af2d28`. Its completed NON-FINAL calibration
reported `streaming_events` 2/2 PASS and `request_signing` 2/2 PASS. Each produced
two exact patch variants with different production-module diffs. This shows
successful implementation variation, with no PASS/FAIL outcome variation in
these runs. Two runs per task do not establish statistical reliability. Suite A
templates and base commits remain unchanged. V1.1.5b1 changes their TaskSpec
evaluation protocol as described below; historical calibration remains unchanged.

V1.1.5a adds two Suite B candidates: `atomic_batch` models ordered balance
transactions with committed journals and idempotent request replay;
`cache_revalidation` models conditional refresh, validator preservation and
bounded stale fallback using an injected clock/backend. These are purpose-built
standard-library repositories with visible tests and no real network or timing
races. Their difficulty comes from consistency across public abstractions.
Suite B was externally accepted at `2440af2`. Its completed NON-FINAL calibration
reported `atomic_batch` 2/2 PASS and `cache_revalidation` 2/2 PASS. Atomic batch's
two whole-patch variants differed only in test edits; production diffs matched.
Cache revalidation showed variation in client.py while cache.py repairs matched.
All four candidates passed two calibration Runs each (8/8 total), all with
visible test edits. This does not prove test weakening or statistical reliability.
Those calibration observations remain historical; final suite results are below.

## Prepare and validate

From the PatchBench root:

```bash
source .venv/bin/activate
python -m scripts.prepare_reliability_fixtures
patchbench validate-task tasks/reliability/streaming_events/task.yaml
patchbench validate-task tasks/reliability/request_signing/task.yaml
patchbench validate-task tasks/reliability/atomic_batch/task.yaml
patchbench validate-task tasks/reliability/cache_revalidation/task.yaml
pytest -q tests/test_prepare_reliability_fixtures.py
```

Templates live under `fixtures/reliability/<task-id>/`. Disposable Git copies
live only under ignored `fixtures/reliability/.prepared/<task-id>/`; TaskSpecs
resolve to those directories and pin full deterministic buggy-base commits.
The script reuses the established hardened Pilot preparation helper, including
fixed commit inputs, raw blob bytes and modes, isolated Git environment, and
clean HEAD/manifest/template verification. Repeat preparation refuses dirty,
unexpected or divergent state without overwriting it. It does not prepare or
change Pilot repositories. Never stage `.prepared/` or nested Git metadata.

The fixture README command, `python -B -m unittest -v`, runs the developer-visible
raw suite inside a prepared repository. It is useful for inspecting the buggy
baseline, where behavioral failures are expected. Preparation tests run this raw
command explicitly; it is no longer the official TaskSpec evaluator command.

All four TaskSpecs now use the frozen unittest protocol with a 120-second limit:

```yaml
evaluation:
  command: "python -I -S -B .patchbench-eval/runner.py"
  timeout_seconds: 120
  frozen_unittest:
    version: 1
    test_files:
      - test_batchstore.py
```

Each task lists its own top-level test filename. Protocol 1 permits only unique,
root-level Python filenames, with no support-file or discovery feature. The
runner is injected by PatchBench during official evaluation and is deliberately
absent from prepared fixture templates; the official command cannot be run
directly in an unprepared fixture workspace.

Visible tests remain visible and editable by the Agent. PatchBench first captures
the complete Agent patch, then applies it to a separate worktree at the exact
base commit. It restores declared test files from that pristine base, replaces
the reserved `.patchbench-eval` path, and injects its trusted runner. Only the
declared frozen tests determine the official verdict; Agent-added tests are not
discovered. A zero-test suite fails. Host and Docker evaluate this same prepared
view; Docker mounts it at the existing `/workspace` path.

The full Agent patch, including test edits, remains canonical patch evidence;
platform restoration and runner injection do not contaminate it. Official
test.log and EvaluationEvidence describe the frozen evaluation. Run and Replay
share preparation; Experiments inherit it. Replay still uses the caller's
TaskSpec and historical full patch when task IDs match, so replaying an old
calibration with a new TaskSpec is not a claim to reproduce its old evaluator.

This protects evaluator selection against visible-test edits/deletions/skips
and added tests. It is not adversarial sandbox security: arbitrary hostile
production Python can interfere with its own test process. Legacy TaskSpecs
without frozen configuration retain their evaluator and fingerprint semantics;
historical artifacts are not migrated.

Parent tests verify deterministic preparation, safe repetition/refusal,
TaskSpec consistency, named baseline FAIL/ERROR results, legacy PASS cases,
and temporary worktree cleanup. They contain no complete reliability-task reference
repair. Temporary repairs used to prove solvability are created outside the
project and deleted after complete evaluator checks; no repair is shipped in
templates, scripts, tests, documentation or prepared Git history.

No real Codex execution is part of preparation or parent validation. Keep all
calibration artifacts excluded from final evidence.

## Accepted freeze and completed final sample

The [freeze manifest](../../evidence/v1.1/freeze-manifest.json) pins four ordered
TaskSpecs, exact byte hashes/fingerprints, repository bases, official test Git
blob hashes, evaluator protocol, Codex CLI version and Docker image identity.
Evaluator semantics are accepted at `802c4d3dcc09d89400ca306eae253b5ef585d442`;
the separate freeze tag identifies the accepted manifest/verifier checkout,
avoiding a commit SHA embedded recursively inside its own manifest.

Final configuration: agent codex, model gpt-6-astra, Codex CLI 0.153.4,
600-second Agent timeout, Docker evaluation and eight independent Runs per task.
Strict preflight passed on the clean tagged checkout before final execution.
The model identifier/CLI version are pinned, not remote service implementation.

| Task | Final Experiment | PASS / FAIL | Whole-patch variants | Successful production signatures |
|---|---|---|---|---|
| streaming_events | f5eb757a1caf466d8d49be3a55dbcb58 | 8 / 0 | 8 | 8 |
| request_signing | 71c041b4bc554269b371fdbf98406b50 | 8 / 0 | 8 | 8 |
| atomic_batch | e8ace47d9fef4fae8214ee47c1a8679e | 8 / 0 | 8 | 4 |
| cache_revalidation | 51d9c031f8344db0a64bd8cfddc9c6aa | 6 / 2 | 7 | 1 |

The immutable final sample is 32 Runs: 30 PASS, 2 FAIL (93.75% end-to-end).
All 30 normally completed Agent executions passed frozen evaluation; the two
command failures reported Codex usage quota limits before producing patches.
They remain in the sample with no replacements. Conditional 30/30 success is
not unconditional reliability, and cache_revalidation's 6/8 is not a semantic
repair success rate. Production counts are exact task-local non_test diff
signatures, not semantic algorithm equivalence.

See [final-results.json](../../evidence/v1.1/final-results.json) for canonical
Run order and compact evidence, and [FINAL_REPORT.md](../../evidence/v1.1/FINAL_REPORT.md)
for interpretation and limitations. Release evidence is complete and pending
final external review. Raw results and the freeze manifest/tag remain unchanged.

For read-only audit, use `python -m patchbench.cli analyze --experiment <ID> --json`
on the four existing Experiments. Do not rerun them. Strict
`python -m scripts.verify_v11_freeze` requires a clean checkout at the freeze tag;
it intentionally fails after release-documentation edits. Verify protected-path
diffs against the freeze commit when reviewing this release. The verifier never
cleans residues, pulls images, creates tags or prepares missing repositories.
