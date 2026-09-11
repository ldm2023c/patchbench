# V1.1.4 Real Task Suite A candidates

These are purpose-built realistic software repositories. They are not imported
upstream bug reports or observed production bugs and claim no external provenance.
They are candidate reliability tasks, not yet frozen final V1.1 evidence.
V1.1.4 calibration Runs are **NON-FINAL forever**, even if a candidate is later
selected unchanged. Final selection and freeze happen only after calibration
and the V1.1.5 Real Task Suite B + Freeze gate.

`streaming_events` models an NDJSON event-log importer: incremental byte-stream
state, record framing, UTF-8 boundaries, byte limits, error reporting and reader
integration. `request_signing` models webhook HMAC signing: lossless request
representation, deterministic query/header canonicalization and shared signing
and verification. Each repository has a public contract and a complete visible
unittest suite. Both use only the Python 3.12 standard library.

## Prepare and validate

From the PatchBench root:

```bash
source .venv/bin/activate
python -m scripts.prepare_reliability_fixtures
patchbench validate-task tasks/reliability/streaming_events/task.yaml
patchbench validate-task tasks/reliability/request_signing/task.yaml
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

Both evaluators run `python -B -m unittest -v` with a 120-second timeout. Execute
that command inside a prepared repository to inspect its mixed PASS/FAIL
baseline. A nonzero result from relevant behavioral regressions is expected.
The same command works in the existing `python:3.12-slim` Docker environment;
no dependencies, network access or cache generation are needed.

Parent tests verify deterministic preparation, safe repetition/refusal,
TaskSpec consistency, named baseline FAIL/ERROR results, legacy PASS cases,
and temporary worktree cleanup. They contain no complete Suite A reference
repair. Temporary repairs used to prove solvability are created outside the
project and deleted after complete evaluator checks; no repair is shipped in
templates, scripts, tests, documentation or prepared Git history.

No real Codex execution is part of preparation or parent validation. Difficulty
and final suitability remain unmeasured until separately authorized calibration.
Keep calibration artifacts excluded from final evidence; do not create final
manifests or final eight-run Experiments for these candidate definitions.
