# V1.1.0 pilot discovery (NON-FINAL)

These are purpose-built, realistic small repositories, not upstream bug reports
or a frozen benchmark suite. Their role is to discover evidence shapes. All
pilot Runs must remain excluded from the final V1.1 dataset forever, including
if these task definitions are later reused unchanged.

Configuration precedence has a CLI, TOML/environment resolution, and validated
settings (192 Python lines including 16 tests). Bookmark exchange separates
record validation, field encoding/decoding, and document handling (147 Python
lines including 14 tests). Each has its own format/behavior README. They use
only Python's standard library, with no dependency provisioning or network I/O.

## Prepare and validate

From the PatchBench root:

```bash
source .venv/bin/activate
python -m scripts.prepare_pilot_fixtures
patchbench validate-task tasks/pilot/config_precedence/task.yaml
patchbench validate-task tasks/pilot/roundtrip/task.yaml
pytest -q tests/test_prepare_pilot_fixtures.py
```

The script copies ordinary tracked source templates to ignored repositories:
`fixtures/pilot/.prepared/config_precedence` and `.prepared/roundtrip`. The fixed
commits in TaskSpecs are created with fixed identity, timestamp, message, file
modes, and raw blob bytes. Pilot Git commands clear inherited Git overrides
and disable user/system Git configuration. Re-preparation verifies existing state without
resetting owner edits. It refuses dirty repositories, unexpected HEADs, and
template drift. Do not stage `.prepared/` or any embedded Git metadata.

Focused tests prepare independent copies, run the exact configured evaluator
at each base, apply a reference repair only inside a temporary worktree, and
require the complete evaluator to pass. Reference repairs live in the parent
preparation test, outside the fixture and task prompt. Canonical bases retain
the bugs. Tests also verify worktree cleanup and repeatable preparation.

Both evaluators are `python -B -m unittest -v` with a 120-second evaluator
limit. Activate the virtual environment so `python` is on PATH. Cache ignores
are part of each fixture base. No real Codex invocation occurs in validation.

## Human executions after review

Replace `<MODEL>` with one explicit model and use the same choice in all four
commands, with Docker evaluation for all four. Docker must be available.
A 600-second Agent timeout is a generous operational bound, separate
from the evaluator timeout; do not tune it to manufacture failures. If it proves
insufficient, retain and annotate that observation before planning more pilots.

```bash
# Pilot A — real Codex Run #1 (NON-FINAL)
patchbench run --task tasks/pilot/config_precedence/task.yaml --agent codex --model '<MODEL>' --agent-timeout 600 --docker
# Pilot A — real Codex Run #2 (NON-FINAL)
patchbench run --task tasks/pilot/config_precedence/task.yaml --agent codex --model '<MODEL>' --agent-timeout 600 --docker
# Pilot B — real Codex Run #1 (NON-FINAL)
patchbench run --task tasks/pilot/roundtrip/task.yaml --agent codex --model '<MODEL>' --agent-timeout 600 --docker
# Pilot B — real Codex Run #2 (NON-FINAL)
patchbench run --task tasks/pilot/roundtrip/task.yaml --agent codex --model '<MODEL>' --agent-timeout 600 --docker
```

Before running, create a manual ledger at `results/pilot-v110-ledger.md` with
an explicit NON-FINAL heading. After each command, record its printed Run ID,
task, repetition, command/model, and artifact directory. Preserve the ledger
with the pilot artifacts; the current v1 metadata has no dataset-membership
field. Keep it separate from any future final dataset manifest. These commands
use Docker evaluation and preserve artifacts under `results/<run-id>/`.

## Evidence gate checklist (not a schema)

- Run outcome; Agent status, exit code, duration, stdout and stderr.
- Patch size, actual changed paths, source/test edits, text/binary changes,
  additions/deletions, new/deleted files, and naturally occurring generated noise.
- Evaluator exit code, stdout/stderr, failing test names, assertion/traceback
  structure, and where the existing `test.log` retains useful information.
- Current metadata contents and missing information needed for provenance audits.
- Across repeats: patch strategies, PASS/PASS differences, and PASS/FAIL
  differences only if naturally observed; which deterministic signals help.

Do not infer cross-run variation from reference repairs. They establish only
solvability. Inspect real artifacts before designing provenance, PatchSummary,
EvaluationEvidence, or Analyze. Stop at the evidence/schema design gate;
V1.1.1 and Optional V2 are not authorized by this slice.
