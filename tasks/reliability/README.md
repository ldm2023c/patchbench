# Reliability task candidates — Suites A and B

These are purpose-built realistic software repositories. They are not imported
upstream bug reports or observed production bugs and claim no external provenance.
They are candidate reliability tasks, not yet frozen final V1.1 evidence.
All Suite A and Suite B calibration Runs are **NON-FINAL forever**, even if a candidate is later
selected unchanged. Final selection and freeze happen only after calibration
and the V1.1.5b2 Suite Freeze + Manifest gate. No final V1.1 TaskSpec has been frozen yet.

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
The tasks remain candidates pending V1.1.5b2, not a frozen final suite.

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

## V1.1.5b2 freeze readiness (pending external acceptance)

`evidence/v1.1/freeze-manifest.json` pins the four ordered TaskSpecs and their
exact byte hashes/fingerprints, repository bases, official test Git blob bytes,
frozen evaluator protocol, Codex CLI version and current Docker image identity.
Evaluator semantics are the accepted `802c4d3dcc09d89400ca306eae253b5ef585d442`.
Fixture templates and the four TaskSpecs are unchanged in this freeze slice.

The locked execution configuration is agent `codex`, model `gpt-6-astra`,
Agent timeout 600 seconds, Docker evaluation, and 8 independent Runs for each
task, in order: streaming_events, request_signing, atomic_batch, cache_revalidation.
That is 32 planned final Runs. Use `python -m patchbench.cli` from the verified
Python environment so the package comes from this checkout. The manifest records
the model identifier and CLI version; it cannot freeze remote model/service
implementation. No final Runs or final result summaries exist from this slice.

For pre-commit review, after preparing repositories:

```bash
python -m scripts.verify_v11_freeze --static
```

This read-only check validates the manifest, accepted protected paths, task/base
identities, clean prepared repositories, local Docker reference/image ID and
optional RepoDigest, Codex version, PatchBench import origin, empty `.workspaces`
and absence of running PatchBench sandbox containers. It permits uncommitted
review files and requires no freeze tag. Missing prepared repositories must be
prepared explicitly; residues are reported, never removed by the verifier.

After external acceptance, the human owner creates
`refs/tags/v1.1-evidence-freeze` pointing to the accepted V1.1.5b2 commit.
The manifest pins the earlier evaluator commit separately: putting the manifest's
own future commit SHA inside itself would change that SHA. The post-review tag
instead identifies the complete accepted manifest/verifier/docs checkout.

Immediately before final execution, run the strict preflight:

```bash
python -m scripts.verify_v11_freeze
```

It adds a clean root, an existing freeze ref, HEAD equal to the tag's resolved
commit, and unchanged protected semantics since the evaluator checkpoint. The
current `python:3.12-slim` tag must still resolve to the pinned image ID; do not
pull/update it to bypass a mismatch. No verifier mode creates or moves tags.
Before that tag exists, strict mode must fail explicitly for the missing ref.

V1.1.5b2 is not accepted/finally frozen yet. Final experiments require that gate
and separate execution authorization. A completed FAIL is final evidence, not
a reason to retry; genuine infrastructure failures require separate review.
