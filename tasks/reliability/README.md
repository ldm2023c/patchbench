# Reliability task candidates — Suites A and B

These are purpose-built realistic software repositories. They are not imported
upstream bug reports or observed production bugs and claim no external provenance.
They are candidate reliability tasks, not yet frozen final V1.1 evidence.
All Suite A and Suite B calibration Runs are **NON-FINAL forever**, even if a candidate is later
selected unchanged. Final selection and freeze happen only after calibration
and the V1.1.5b Suite Freeze gate. No final V1.1 TaskSpec has been frozen yet.

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
templates and TaskSpecs remain unchanged after calibration.

V1.1.5a adds two Suite B candidates: `atomic_batch` models ordered balance
transactions with committed journals and idempotent request replay;
`cache_revalidation` models conditional refresh, validator preservation and
bounded stale fallback using an injected clock/backend. These are purpose-built
standard-library repositories with visible tests and no real network or timing
races. Their difficulty comes from consistency across public abstractions.
Suite B is **not calibrated and not frozen**. After external review, separately
authorized NON-FINAL Suite B calibration precedes the V1.1.5b freeze gate.

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

All four evaluators run `python -B -m unittest -v` with a 120-second timeout. Execute
that command inside a prepared repository to inspect its mixed PASS/FAIL
baseline. A nonzero result from relevant behavioral regressions is expected.
The same command works in the existing `python:3.12-slim` Docker environment;
no dependencies, network access or cache generation are needed.

Parent tests verify deterministic preparation, safe repetition/refusal,
TaskSpec consistency, named baseline FAIL/ERROR results, legacy PASS cases,
and temporary worktree cleanup. They contain no complete reliability-task reference
repair. Temporary repairs used to prove solvability are created outside the
project and deleted after complete evaluator checks; no repair is shipped in
templates, scripts, tests, documentation or prepared Git history.

No real Codex execution is part of preparation or parent validation. Suite B
difficulty remains unmeasured until separately authorized calibration, and final
suitability for all candidates remains subject to the freeze gate.
Keep calibration artifacts excluded from final evidence; do not create final
manifests or final eight-run Experiments for these candidate definitions.
