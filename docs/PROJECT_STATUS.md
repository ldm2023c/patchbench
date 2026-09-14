# PatchBench Project Status

Canonical current handoff. Source code, accepted tests, artifacts and Git state
outrank implementation summaries and this document when they disagree.

## Current state and next action

- **Integration branch:** `v1.2`; accepted D1–D5 tip `3e4af7d`.
- **Documentation slice:** `docs/v1.2-diagnosis-sync` synchronizes the current contract.
- **Implemented and code-reviewed:** V1.2 Diagnosis D1–D5, merged and pushed to `v1.2`.
- **Historical release:** V1.1 frozen evidence is COMPLETE; V1 M0–M6 is also complete.
- **External blocker:** D4-P live OpenAI Blind prototype and D6-R real provider
  validation lack funded API billing/credits. This is an access/billing blocker,
  not evidence of technical failure or a successful Diagnosis request.
- **Next implementation slice:** D6.1 Human Gold Contract + deterministic per-case
  scoring. D6 is designed/next, not implemented or empirically validated here.
- **Empirical boundary:** no Diagnosis-accuracy claim. The V1.1 frozen reliability
  release is the current empirical model evidence.

This documentation slice authorizes no D6 implementation or new experiments.
After documentation review, the owner can supply the D6.1 scope lock. Offline
contract/scoring work and billing-dependent real validation are separate gates.
Do not describe all of V1.2 as complete.

## Accepted Diagnosis history

These commits are in repository history on `v1.2`; PASS/acceptance is the owner's
external review status, not a Git-generated verdict.

| Slice | Status | Accepted implementation / focused fix |
|---|---|---|
| D1 — domain and routing | PASS / merged | `bed6ab9a17ad832599f135e4c285da8e3b06eb7c`; invariants `017778b4136c8ba6fb0ccdaedaf5e6036dc98377` |
| D2 — complete deterministic evidence | PASS / merged | `95e9df353258cc33b10663a1b03214f31e07a2ba`; locators `ba60792e2a8091cb1fe18bb59df52a08994e744f` |
| D3 — Auditor and immutable persistence | PASS / merged | `b911e4efba08ad4c58356a46e8490cc1fb3c077e` |
| D4 — Blind provider execution | Code PASS / merged | `af9eb7534cd40cef3430ea9e7dc3e3401b71afd7` |
| D4-P — real OpenAI Blind prototype | BLOCKED_BY_API_BILLING | No successful real OpenAI Diagnosis result |
| D5 — deterministic Contrastive Diagnosis | PASS / merged | `3b8e69cc48c141dc2dd58b9986e01de3e0f0d7b7`; execution trust boundary `3e4af7dd78fe1f7268b142e6b2e44db74d277c23` |
| D6 — human-gold validation and metrics | Designed / next | D6.1 contract and deterministic per-case scoring not yet implemented |
| D6-R — real provider validation | Externally blocked | Requires funded API billing/credits and the validation prerequisites |

## Implemented boundary

D1 routes official PASS to unavailable, official FAIL + command failure/timeout
to operational-only, and official FAIL + COMPLETED to semantic diagnosis.
Routing alone does not prove compilation readiness.

D2 verifies historical raw patch/log/task identity and compiles complete bounded
base/candidate production source plus frozen baseline tests. D3 audits only
hashes, linkage, ownership and citation ranges. D4 accepts a compiled Blind
Bundle, applies permission/integrity/byte gates, makes one provider SDK call,
parses semantic output and persists the completed typed attempt. D5 appends one
same-cell PASS peer selected by persisted Experiment order.

D5 peer provenance includes Experiment ID and zero-based Run index. Execution
re-verifies that canonical selection before rendering or provider invocation;
a locally valid Contrastive Bundle plus recomputed SHA is not proof of same-cell
selection. There is no fallback to a later PASS after the selected peer fails.

These are programmatic APIs. Existing CLI commands remain `validate-task`,
`run`, `experiment`, `replay`, and `analyze`; there is no Diagnosis CLI.
See [Diagnosis](DIAGNOSIS.md) for contracts and [Architecture](../ARCHITECTURE.md)
for dependency boundaries.

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
- Do not move `v1.1-evidence-freeze` from
  `94cd2873c42af7f5c697e6316316c9cb59fc6d8b`, rewrite frozen evidence, replace failed
  Runs, or silently add new experiments.
- No human-gold metrics, retrieval, automatic repair, multiple peers or cross-agent
  Contrastive work is implemented. Optional V2 remains deferred.

## Historical empirical evidence

V1.1 final evidence was accepted at `7a99c2ca580ac34a2ca9cc248ec2f8977656c495`;
COMPLETE documentation followed at `39fb119`. Four tasks × eight Runs yielded
32 Runs: 30 PASS, two external Codex quota command failures, zero timeouts and
no replacement Runs. All 30 normally completed Agent executions passed frozen
evaluation. This is not unconditional 100% reliability or Diagnosis accuracy.

The [final report](../evidence/v1.1/FINAL_REPORT.md),
[freeze manifest](../evidence/v1.1/freeze-manifest.json) and
[final results](../evidence/v1.1/final-results.json) remain unchanged.
The [archived V1/V1.1 handoff](history/V1_1_STATUS.md) preserves the entire old
status document, including pilot/calibration exclusions, M0–M6 milestones,
validation history, Run/Replay IDs and cleanup observations. Its “current” and
“next” statements are historical, not instructions for V1.2.

## Handoff maintenance

After accepted slices, update current status and accepted commit IDs. At a
version or architecture boundary, perform an explicit documentation sync across
[README](../README.md), [Project Spec](../PROJECT_SPEC.md),
[Architecture](../ARCHITECTURE.md), [Diagnosis](DIAGNOSIS.md),
[Development](DEVELOPMENT.md) and [Interview Notes](interview_notes.md).
A documentation-only slice checks changed links, stale claims, `git diff --check`
and `git status --short`; it does not require unrelated full pytest or live runs.
