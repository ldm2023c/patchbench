# PatchBench Project Status

Canonical current handoff. Source code, accepted tests, frozen artifacts,
runtime validation artifacts and Git state outrank implementation summaries and
this document when they disagree.

## Current state and next action

- **Integration branch:** `v1.2`; current checked integration head is `8507dbd`
  (`fix: tighten diagnosis shard ledger compatibility`).
- **Implemented and code-reviewed:** V1.2 Diagnosis D1–D6-R2 is merged into
  `v1.2`.
- **Historical release:** V1.1 frozen evidence is COMPLETE; V1 M0–M6 is also
  complete.
- **Frozen Diagnosis Validation V1:** 15 cases, consisting of 13 semantic cases
  and two operational routing cases. Freeze manifest byte SHA is
  `81147642b9d39cc265c69151d470e03a8c01ed53b6a629a922e0106b4a216d14`; frozen
  suite SHA is `ee724d3825c97f583bbbe13addd3aa0cd61b6ba3265680153486e7274c08643a`.
- **Real-provider acquisition:** in progress, not complete. One formal sharded
  acquisition has completed through a third-party OpenAI-compatible gateway
  (`https://ai.ailink1.com/v1`):
  `diag-v1-semantic-01-gpt55-none-20260916-133614`, selected case
  `semantic-01`, Blind completed and Contrastive completed.
- **External blocker:** current acquisition is blocked by provider/gateway
  availability / timeout instability under the locked request configuration. Do
  not attribute the timeout specifically to the gateway, gateway-to-upstream
  link, or upstream model; that has not been proven.
- **Empirical boundary:** no final Diagnosis accuracy, family accuracy,
  abstention-quality, or Blind-vs-Contrastive empirical conclusion is published.
  Only complete successful shards may enter the final validation dataset.

The next work is to wait for provider/gateway health to recover, acquire the
remaining semantic cases under the same frozen configuration, implement a
successful-shard collector/selection step if still absent from source, run the
already implemented D6.1 scoring, perform required human overclaim review, run
D6.2 aggregate and paired metrics, score the two operational routing cases, and
produce the final V1.2 empirical validation report.

## Accepted Diagnosis history

These commits are in repository history on `v1.2`; PASS/acceptance is the
owner's external review status, not a Git-generated verdict.

| Slice | Status | Accepted implementation / focused fix |
|---|---|---|
| D1 — domain and routing | PASS / merged | `bed6ab9a17ad832599f135e4c285da8e3b06eb7c`; invariants `017778b4136c8ba6fb0ccdaedaf5e6036dc98377` |
| D2 — complete deterministic evidence | PASS / merged | `95e9df353258cc33b10663a1b03214f31e07a2ba`; locators `ba60792e2a8091cb1fe18bb59df52a08994e744f` |
| D3 — Auditor and immutable persistence | PASS / merged | `b911e4efba08ad4c58356a46e8490cc1fb3c077e` |
| D4 — Blind provider execution | PASS / merged | `af9eb7534cd40cef3430ea9e7dc3e3401b71afd7` plus later adapter compatibility on current `v1.2` |
| D5 — deterministic Contrastive Diagnosis | PASS / merged | `3b8e69cc48c141dc2dd58b9986e01de3e0f0d7b7`; execution trust boundary `3e4af7dd78fe1f7268b142e6b2e44db74d277c23` |
| D6.1 — Human Gold + per-case scoring | PASS / merged | implemented in `diagnosis_validation.py`; binds exact Gold SHA and scores route/semantic cases |
| D6.2 — aggregate + paired metrics | PASS / merged | implemented in `diagnosis_metrics.py`; exact Blind/Contrastive pairing, no composite winner score |
| D6.3 — frozen Validation V1 | PASS / merged | gold lock `d3b105c`; Phase A/B/final freeze through `e044842` |
| D6-R1 — frozen provider-run harness | PASS / merged | `3daa725`; hardening `8f5a059` |
| D6-R2 — sharded acquisition | PASS / merged | `ad28043`; ledger compatibility fix `8507dbd` |

## Frozen Validation V1 suite

The suite contains exactly 15 cases:

- 13 semantic cases:
  `semantic-01`, `semantic-02`, `semantic-05`, `semantic-06`, `semantic-07`,
  `semantic-08`, `semantic-09`, `semantic-11`, `semantic-16`, `semantic-17`,
  `semantic-22`, `semantic-24`, `semantic-25`.
- Two operational routing cases:
  - `operational-01`: `agent_command_failed`.
  - `operational-02`: `agent_timed_out`.

Semantic Human Gold composition:

- 2 × `incorrect_local_logic`
- 2 × `incomplete_cross_file_repair`
- 2 × `partial_contract_handling`
- 2 × `state_consistency_violation`
- 2 × `regression_introduced`
- 3 × `should_abstain` cases: `semantic-22`, `semantic-24`, `semantic-25`

The freeze artifacts live under `validation/diagnosis/v1`. Candidate support
artifacts for Contrastive verification live under
`fixtures/diagnosis_validation/v1_candidates/_support` and are not copied into
the frozen validation tree.

## Real-provider acquisition status

The locked acquisition configuration is:

- model: `gpt-5.5`
- reasoning effort: `none`
- max output tokens: `2048`
- timeout seconds: `110`
- max provider input bytes: `1000000`
- SDK/application retries: `0`
- Responses API-compatible request
- `store=false`
- `tools=[]`
- `tool_choice="none"`
- `truncation="disabled"`
- `stream=false`

The live experiment uses a third-party OpenAI-compatible gateway at
`https://ai.ailink1.com/v1`. The PatchBench adapter and persisted provider
provenance use `provider_name="openai"` because the implementation uses the
OpenAI-compatible SDK/Responses adapter. Do not describe the successful shard as
an official OpenAI API result.

The successful formal shard is:

```text
run_id: diag-v1-semantic-01-gpt55-none-20260916-133614
selected_case_ids: [semantic-01]
Blind: completed
Contrastive: completed
```

Earlier full-run attempts stopped after transient provider failures at slot 4
and slot 10. A separate early failed run was caused by missing local credentials
and is not evidence about model/gateway reliability. Later exact-request
diagnostics with credentials and base URL confirmed observed `APITimeoutError`
near the locked 110-second timeout; a generic padded non-benchmark provider
health check also timed out near the same timeout. The conservative current
blocker is provider/gateway timeout instability under the locked configuration.

Failed acquisition attempts are retained and never overwritten, resumed, or
stitched. A failed shard must be rerun under a new run ID. Only one complete
successful Blind+Contrastive shard per semantic case may feed the final
validation dataset.

## Implemented boundary

D1 routes official PASS to unavailable, official FAIL + command failure/timeout
to operational-only, and official FAIL + COMPLETED to semantic diagnosis.
Routing alone does not prove compilation readiness.

D2 verifies historical raw patch/log/task identity and compiles complete bounded
base/candidate production source plus frozen baseline tests. D3 audits only
hashes, linkage, ownership and citation ranges. D4 accepts a compiled Blind
Bundle, applies permission/integrity/byte gates, makes one provider inference
call, parses semantic output and persists the completed typed attempt. D5
appends one same-cell PASS peer selected by persisted Experiment order.

D6.1 scores typed route and semantic Diagnosis outputs against Human Gold. It
uses complete Gold identity (`gold_sha256`), subject evidence identity, family
and abstention applicability, required evidence coverage, Auditor results, and
human-reviewed forbidden overclaim fields. D6.2 aggregates deterministic counts
and exact paired Blind/Contrastive deltas; it intentionally has no global
composite winner score. D6.3 freezes the 15-case validation suite. D6-R1/R2 run
real-provider acquisition with immutable ledgers and optional semantic-case
shards.

These are programmatic APIs and scripts. Existing `patchbench` CLI commands
remain `validate-task`, `run`, `experiment`, `replay`, and `analyze`; there is
no public Diagnosis CLI command. See [Diagnosis](DIAGNOSIS.md) for contracts and
[Architecture](../ARCHITECTURE.md) for dependency boundaries.

## Preserve these invariants

- Official evaluation, Run/Replay/Experiment records and historical raw artifacts
  remain truth; hypotheses never revise them.
- D2 Blind bytes/IDs/order, exact source content and bounded completeness remain
  stable. Reject unsupported locators; do not sanitize raw evidence.
- Blind is the headline mode; Contrastive is a secondary ablation. PASS peer is
  comparison evidence, not a gold repair or causal oracle.
- Auditor PASS is structural only. Audit FAIL can be a completed persisted attempt.
- External inference is opt-in; built-in OpenAI tests use mocks. No arbitrary
  private-repository safety or prompt-injection security claim follows.
- D6 scoring is deterministic validation against Human Gold; it is not an LLM
  judge and does not change official truth.
- D6-R acquisition has no retry, resume, hidden collector, or failed-run stitching.
- Do not move `v1.1-evidence-freeze` from
  `94cd2873c42af7f5c697e6316316c9cb59fc6d8b`, rewrite frozen evidence, replace
  failed Runs, or silently add new experiments.
- No retrieval, automatic repair, multiple peers, cross-agent Contrastive work,
  final Diagnosis accuracy, or Optional V2 context/service expansion is present.

## Historical empirical evidence

V1.1 final evidence was accepted at `7a99c2ca580ac34a2ca9cc248ec2f8977656c495`;
COMPLETE documentation followed at `39fb119`. Four tasks × eight Runs yielded
32 Runs: 30 PASS, two external Codex quota command failures, zero timeouts and
no replacement Runs. All 30 normally completed Agent executions passed frozen
evaluation. This is not unconditional 100% reliability or Diagnosis accuracy.

The [final report](../evidence/v1.1/FINAL_REPORT.md),
[freeze manifest](../evidence/v1.1/freeze-manifest.json) and
[final results](../evidence/v1.1/final-results.json) remain unchanged. The
[archived V1/V1.1 handoff](history/V1_1_STATUS.md) preserves the entire old
status document, including pilot/calibration exclusions, M0–M6 milestones,
validation history, Run/Replay IDs and cleanup observations. Its “current” and
“next” statements are historical, not instructions for V1.2.

## Handoff maintenance

After accepted slices, update current status and accepted commit IDs. At a
version or architecture boundary, perform an explicit documentation sync across
[README](../README.md), [Project Spec](../PROJECT_SPEC.md),
[Architecture](../ARCHITECTURE.md), [Diagnosis](DIAGNOSIS.md),
[Development](DEVELOPMENT.md) and [Interview Notes](interview_notes.md). A
documentation-only slice checks changed links, stale claims, `git diff --check`
and `git status --short`; it does not require unrelated full pytest or live runs.
