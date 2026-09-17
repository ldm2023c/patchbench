# PatchBench Project Status

Canonical current handoff. Source code, accepted tests, frozen artifacts,
runtime validation artifacts and Git state outrank implementation summaries and
this document when they disagree.

## Current state and next action

- **Integration branch:** `v1.2`; accepted D6-R5 implementation head is
  `929f44f4cdd43cd8eb5262a62853767c9a002c20`. The current feature branch is a
  documentation-only sync on top of that implementation baseline.
- **Implemented and code-reviewed:** V1.2 Diagnosis D1–D6-R5 is merged into
  `v1.2`.
- **Historical release:** V1.1 frozen evidence is COMPLETE; V1 M0–M6 is also
  complete.
- **Frozen Diagnosis Validation V1:** 15 cases, consisting of 13 semantic cases
  and two operational routing cases. Freeze manifest byte SHA is
  `81147642b9d39cc265c69151d470e03a8c01ed53b6a629a922e0106b4a216d14`; frozen
  suite SHA is `ee724d3825c97f583bbbe13addd3aa0cd61b6ba3265680153486e7274c08643a`.
- **Real-provider acquisition:** complete for the frozen 13 semantic cases through
  collection `gpt6astra-pro-v1`; collection SHA is
  `592bdf99f36afcbd3d54d770a7bf12a484a1e42ca2c1b08867712d174b36a738`.
- **Final semantic scores:** `gpt6astra-pro-v1-semantic-scores-v1`; score SHA is
  `5c3a74133ae9653d1e7d7906cd45e91810daea9964d35334e57ca65e5aa86e19`. Human
  forbidden-claim review is complete for all applicable diagnoses.
- **Final Validation V1 result:** `gpt6astra-pro-v1-final-v1`; result SHA is
  `cc5ffa71a418d622dcf904963870e447e04cab956d117724f06c0b810e300fa4`.
- **Empirical boundary:** the reported Diagnosis metrics apply only to the frozen
  Validation V1 suite. They do not establish broad model reliability, production
  diagnosis quality, statistical significance, or a general claim that PASS peers
  help or harm Diagnosis.

The next work is human review/publication or a separate future milestone. Optional
V2 context-engine/service work remains deferred and is not authorized by the V1.2
Diagnosis result.

## Accepted Diagnosis history

These commits are in repository history on `v1.2`; PASS/acceptance is the
owner's external review status, not a Git-generated verdict.

| Slice | Status | Accepted implementation / focused fix |
|---|---|---|
| D1 — domain and routing | PASS / merged | `bed6ab9a17ad832599f135e4c285da8e3b06eb7c`; invariants `017778b4136c8ba6fb0ccdaedaf5e6036dc98377` |
| D2 — complete deterministic evidence | PASS / merged | `95e9df353258cc33b10663a1b03214f31e07a2ba`; locators `ba60792e2a8091cb1fe18bb59df52a08994e744f` |
| D3 — Auditor and immutable persistence | PASS / merged | `b911e4efba08ad4c58356a46e8490cc1fb3c077e` |
| D4 — Blind provider execution | PASS / merged | `af9eb7534cd40cef3430ea9e7dc3e3401b71afd7` |
| D5 — deterministic Contrastive Diagnosis | PASS / merged | `3b8e69cc48c141dc2dd58b9986e01de3e0f0d7b7`; execution trust boundary `3e4af7dd78fe1f7268b142e6b2e44db74d277c23` |
| D6.1 — Human Gold + per-case scoring | PASS / merged | `26b04955c63b322aaf6d9781c5b4e6ab1858a730` |
| D6.2 — aggregate + paired metrics | PASS / merged | implementation `52a2dd2e90e7623e19f03e94f669ce37f213334b`; Gold identity fix `93ab6a75a8e3d08271f8f9604c0e16cbf0675681` |
| D6.3 — frozen Validation V1 | PASS / merged | gold lock `d3b105c`; Phase A/B/final freeze through `e044842` |
| D6-R1 — frozen provider-run harness | PASS / merged | `3daa7250a39f80125f65dc2be6340c21dfcfb0c8`; hardening `8f5a05951df4bd43c63ad48bcc9e3ec67e8062b4`; includes removal of explicit `background=False` for OpenAI-compatible gateway compatibility |
| D6-R2 — sharded acquisition | PASS / merged | `ad280432e3dd1f991bfbca3520a1d2a603b8eabe`; ledger compatibility fix `8507dbda5704f52d0712501a79844d0d34a5a4b5` |
| D6-R3 — immutable acquisition collection | PASS / merged | `bd1de8874cf9ddd5707f0c962552e17a3ccb8d83` |
| D6-R4 — semantic scoring finalization | PASS / merged | `ea902b55347c4a9611ec7507f7c3d61786cc7f35` |
| D6-R5 — operational scoring + final result | PASS / merged | implementation `204007fe99b509cab6e6f14b49675e92fba4fbcc`; provenance fixes `33f4209b193e17629917685079ebe9311f074cd9` and `929f44f4cdd43cd8eb5262a62853767c9a002c20` |

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

## Real-provider acquisition and final result

The final collection uses protocol label `gpt6astra-pro-v1`, requested model
`gpt-6-astra`, reasoning effort `none`, and the OpenAI-compatible adapter through
a third-party OpenAI-compatible gateway. This is not an official OpenAI API
result, does not prove the gateway/base URL cryptographically, and does not claim
that `gpt-6-astra` is an official OpenAI model name. Earlier `gpt-5.5` gateway
attempts are historical acquisition attempts and are not the final Validation V1
result.

Final artifacts under `results/diagnosis-validation-v1/`:

- `collections/gpt6astra-pro-v1/collection.json`
  - collection SHA: `592bdf99f36afcbd3d54d770a7bf12a484a1e42ca2c1b08867712d174b36a738`
  - 13/13 semantic cases selected with successful Blind and Contrastive slots.
- `scoring-preparations/gpt6astra-pro-v1-scoring-v1/preparation.json` and
  `overclaim-review-packet.json`
  - D6-R4 preparation for human forbidden-claim review.
- `semantic-scores/gpt6astra-pro-v1-semantic-scores-v1/scores.json`
  - score SHA: `5c3a74133ae9653d1e7d7906cd45e91810daea9964d35334e57ca65e5aa86e19`
  - 26 finalized semantic scores.
- `final-results/gpt6astra-pro-v1-final-v1/result.json`
  - result SHA: `cc5ffa71a418d622dcf904963870e447e04cab956d117724f06c0b810e300fa4`
  - operational routing: 2/2 correct.

Final semantic aggregate on the 13-case frozen suite:

| Metric | Blind | Contrastive |
|---|---:|---:|
| Preferred Top-1 over non-abstention cases | 9/10 | 8/10 |
| Acceptable Top-1 over non-abstention cases | 9/10 | 8/10 |
| Acceptable Top-k over non-abstention cases | 9/10 | 8/10 |
| Required evidence micro coverage | 30/35 (85.7%) | 28/35 (80.0%) |
| Required evidence macro coverage | 87.5% | 82.5% |
| Auditor pass rate | 13/13 | 12/13 |
| Invalid citation cases / issues | 0/13 / 0 | 1/13 / 2 |
| Abstention recall | 0/3 | 0/3 |
| Unnecessary abstention | 0/10 | 0/10 |
| Overclaim review coverage | 13/13 | 13/13 |
| Frozen forbidden-claim violations | 0/13 | 0/13 |

Paired Blind-vs-Contrastive deltas:

- Failure-family transitions over 10 non-abstention cases: improved 0, unchanged
  9, regressed 1. The sole family regression is `semantic-09`.
- Required-evidence transitions over 10 non-abstention cases: improved 1,
  unchanged 8, regressed 1, total satisfied delta -2. `semantic-07` improved by
  +1 required evidence item with unchanged family/audit; `semantic-09` regressed
  from 4/4 to 1/4 required evidence, with family regression and Audit PASS→FAIL.
- Audit transitions over all 13 semantic cases: improved 0, unchanged 12,
  regressed 1. The sole Audit regression is `semantic-09`, with two invalid
  citation issues.
- Abstention correctness was unchanged for all 13 pairs; both modes failed to
  abstain on all three `should_abstain` cases.

Interpretation: on this frozen suite, Contrastive did not improve failure-family
accuracy and introduced one family/audit regression. This is a bounded
observation, not a claim that Contrastive is generally worse or that PASS peers
harm Diagnosis. The 0/13 frozen forbidden-claim violation count means no
violations were marked in the human review for this frozen suite; it is not proof
that the model never overclaims.

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
shards. D6-R3 collects selected successful shards, D6-R4 finalizes semantic
scores after human overclaim review, and D6-R5 emits the final result artifact.

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
- D6-R acquisition has no retry, resume, or failed-run stitching. The D6-R3
  collector accepts only complete selected successful shards and records immutable
  collection identity.
- Do not move `v1.1-evidence-freeze` from
  `94cd2873c42af7f5c697e6316316c9cb59fc6d8b`, rewrite frozen evidence, replace
  failed Runs, or silently add new experiments.
- No retrieval, automatic repair, multiple peers, cross-agent Contrastive work,
  statistical significance claim, broad production Diagnosis claim, or Optional
  V2 context/service expansion is present.

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
