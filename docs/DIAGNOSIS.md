# Evidence-Grounded Diagnosis

## 1. Purpose and current state

V1.2 Diagnosis infrastructure and validation machinery are implemented through
D6-R5 and merged into `v1.2`. This is a programmatic subsystem, not a
`patchbench` Diagnosis CLI. See [Project Status](PROJECT_STATUS.md) for accepted
commits, frozen suite identities, final artifact identities, and interpretation
boundaries.

Blind Diagnosis is the headline mode. Contrastive Diagnosis is a secondary
same-cell PASS ablation. Both produce hypotheses, not a root-cause oracle.
Neither changes official evaluation, repairs patches, retrieves hidden context,
or infers a reference fix. The frozen Validation V1 result reports bounded
13-case semantic Diagnosis metrics plus two operational routing scores; it does
not establish broad model reliability, production Diagnosis quality, statistical
significance, or a general claim that PASS peers help or harm Diagnosis.

## 2. Official truth vs inference

PatchBench owns Run identity, official PASS/FAIL, historical provenance,
evidence selection, and Diagnosis linkage. Provider output may be uncertain,
wrong, or abstain. Official evaluation remains fixed throughout Diagnosis.
Deterministic repository/evaluator/evidence boundaries do not imply immutable
external model weights or bit-for-bit reproducible provider output.

## 3. Routing (D1)

[`route_run_diagnosis`](../src/patchbench/domain/diagnosis.py) routes by recorded
outcomes, without reading or compiling evidence:

| Official evaluation | Agent status | Route |
| --- | --- | --- |
| PASS | Any | Unavailable: official PASS |
| FAIL | Command failed or timed out | Operational only |
| FAIL | Completed | Semantic diagnosis |

Semantic eligibility does not guarantee evidence readiness. Compilation can
still fail closed on missing, inconsistent, or unsupported evidence.

## 4. Evidence boundary (D2)

[`compile_diagnosis_evidence`](../src/patchbench/application/diagnosis_evidence.py)
verifies persisted raw patch/evaluation log against their summaries, pins raw
TaskSpec identity, and checks historical semantic task identity. Reconstruction
uses `Run.provenance.base_commit_used`, not current HEAD or a mutable task ref.
It applies the canonical patch and requires an exact patch round-trip. It runs
neither the coding Agent nor the evaluator.

`DiagnosisSourcePolicy` explicitly bounds production roots and exclusions.
Within that boundary, complete base and candidate source snapshots include
untouched cross-file evidence. Frozen tests come from the baseline and remain
separate from candidate production source. Technical exclusions cover Git,
evaluator staging, and known Python cache directories; this is not implicit
vendor/build filtering or LLM-selected context.

Included symlinks, nonregular files, binary/NUL content, non-UTF-8 content, and
noncanonical source locators fail closed. Locators are exact repo-relative
POSIX identities: no absolute paths, backslashes, colons, ASCII controls/DEL,
empty/dot/parent components, or boundary whitespace. Valid Unicode filenames
remain exact. Malformed locators are rejected, never normalized.

Raw task text, source, frozen tests, canonical patch, and evaluation output
remain exact evidence. Historical `/home/...` or `/tmp/...` strings inside raw
evidence remain intact. Compiler-generated structured locators/identity material
must not introduce host paths. There is no redaction or content normalization.
Agent logs, a gold diagnosis, reference fixes, and unseen repository content
are outside this evidence boundary.

Subject `E` IDs and snapshot hashes are deterministic. `SubjectProvenance`
binds task, patch, log, base/candidate source, frozen tests, and benchmark hashes.
`source_snapshot_policy` identifies the explicit policy. Given identical frozen
input bytes, benchmark identities, historical Git state, and source policy,
compilation is host-independent and deterministic. The final canonical Bundle
JSON byte gate either accepts the complete Bundle or fails; no truncation or
retrieval fallback exists.

## 5. Blind Diagnosis

A Blind `DiagnosisEvidenceBundle` contains only subject evidence, with no PASS
peer. [`execute_blind_diagnosis`](../src/patchbench/application/diagnosis_execution.py)
consumes an already compiled Bundle; it does not invoke D2 internally. Mode and
Bundle SHA are checked before rendering or provider invocation.

## 6. Contrastive Diagnosis (D5)

[`diagnosis_peer.py`](../src/patchbench/application/diagnosis_peer.py) selects
from one persisted Experiment's `run_ids`, in persisted order. The canonical
peer is the first eligible completed official PASS in the same cell, excluding
the subject. The subject need not itself belong to that Experiment. Eligibility
requires provenance and evidence summaries. Matching checks task identity,
Agent name/backend/requested model/timeout, historical base and task fingerprint,
evaluation command/timeout/backend, and consistency with Experiment configuration.
There is no cross-agent matching, semantic ranking, multiple-peer selection,
or arbitrary results-directory scan.

`PeerProvenance` durably records `peer_experiment_id`, `peer_run_id`, and the
zero-based `peer_run_index`, plus peer patch/candidate snapshot/log hashes.
After selection, compilation failure does not fall back to a later peer.
[`diagnosis_contrastive.py`](../src/patchbench/application/diagnosis_contrastive.py)
preserves the exact Blind `E` evidence prefix, fields and order. It verifies
selected peer raw artifacts, reconstructs historical candidate source, checks
shared base/frozen-test truth, and appends complete peer evidence under `P` IDs.
The final Bundle size gate still applies.

Contrastive execution re-verifies the persisted canonical selection before
rendering and provider invocation. Local Pydantic validity and a correct Bundle
hash alone do not establish same-cell truth. The pure Contrastive renderer
assumes that verification has already occurred; use the execution entry point
for this gate. A PASS peer is comparison evidence, not a gold repair, reference
fix, or proof that a particular difference caused failure.

## 7. Provider boundary (D4)

[`DiagnosisProvider`](../src/patchbench/providers/base.py) is separate from the
coding `Agent`. Its inference request contains only `instructions`, `input_text`,
and `output_schema_json`; it receives no Bundle, workspace, repository, Path,
shell callback, or filesystem handle. Settings carry provider configuration.
The response carries completed output text and observed response/model/client,
usage, and duration metadata. The application owns parsing and identity.

The built-in [`OpenAI adapter`](../src/patchbench/providers/openai.py) uses the
synchronous Responses API and `openai>=3.13,<4`. Model, reasoning effort,
maximum output tokens, and finite positive timeout are explicit configuration.
Its request sets `store=False`, `stream=False`, `tools=[]`,
`tool_choice="none"`, `truncation="disabled"`, explicit reasoning effort and
output limit, and strict JSON Schema under `text.format`. It does not send the
optional Responses `background` parameter because an OpenAI-compatible gateway
used for validation rejects that argument. The client uses
`max_retries=0`. One SDK request call is made per attempt, without application
retry; this does not claim network-level exactly-once delivery.

No conversation, previous response, provider files, search, code interpreter,
or MCP tools are requested. Normal SDK credential discovery is used. Provider
implementations are ordinary application code: the protocol does not sandbox
arbitrary third-party implementations or prevent their external actions.

## 8. Prompt and output contract

[`diagnosis_prompt.py`](../src/patchbench/application/diagnosis_prompt.py) freezes
`blind-diagnosis-v1` and `contrastive-diagnosis-v1`. Instructions fix official
outcomes, require supplied evidence only, forbid assuming unseen context or a
gold/reference fix, request one to three ranked hypotheses when supported, and
require abstention when evidence is insufficient. Evidence is explicitly
untrusted data; embedded instructions remain data, not instructions to follow.
This framing is not adversarial prompt-injection security.

Every evidence item appears once in Bundle order, with ID, kind, owner,
source state, path, artifact hash, and numbered lines. Only LF separates lines;
a final LF adds no line, CR remains content, and `ends_with_lf` preserves the
terminal LF distinction. Coordinates are artifact-relative: 41–45 remains
41–45. Empty evidence renders `lines=[]` and uses null/null citations.
The prompt SHA hashes canonical JSON containing exact instructions/input text.

The strict semantic output schema contains only `abstain`, `abstention_reason`,
`hypotheses`, and `recommendation`, with `additionalProperties=false` throughout.
Provider output cannot set `diagnosis_id`, `bundle_sha256`, `mode`,
`subject_run_id`, or `schema_version`. Each hypothesis has rank, failure family,
mechanism summary, evidence/counterevidence refs, and qualitative certainty.
The exact seven `FailureFamily` values are:

- `incorrect_local_logic`
- `incomplete_cross_file_repair`
- `partial_contract_handling`
- `state_consistency_violation`
- `regression_introduced`
- `ineffective_or_test_focused_repair`
- `other_semantic_failure`

Certainty is only `low`, `medium`, or `high`, never numeric confidence.
`insufficient_evidence` is represented through abstention with a reason and no
hypotheses, not an eighth FailureFamily. EvidenceRef coordinates are positive
integers or paired nulls. Final `FailureDiagnosis` validation is authoritative
for contiguous ranks, abstention consistency, and other cross-field rules.
Malformed JSON, extra fields, invalid enums/ranks/coordinates, and contradictory
abstention fail without JSON repair, fence stripping, retries, or citation repair.

## 9. Deterministic Auditor (D3)

[`audit_failure_diagnosis`](../src/patchbench/domain/diagnosis_audit.py) checks
Bundle integrity and linkage, peer ownership/kind consistency, and every
supporting/counterevidence citation's membership and range, including empty and
non-1-based evidence. Issue ordering is deterministic. It does not judge whether
a hypothesis is plausible, causally correct, or actually supported semantically.
An absurd claim with valid structure can pass. Audit FAIL is a completed typed
inference attempt and can be persisted without modification or retry.

## 10. Persistence and identity

Canonical hashes use compact UTF-8 JSON, sorted keys, and `ensure_ascii=False`.
Bundle SHA excludes only its own hash field; Diagnosis SHA covers the complete
Diagnosis. The normalized semantic payload SHA ignores raw JSON whitespace/key
order. PatchBench generates `diag-<64hex>` from Bundle SHA, provider name,
response ID, requested/returned models, template/prompt/schema identity, and
payload SHA. Different response attempt IDs distinguish otherwise identical
attempts. PatchBench injects all system-owned fields before final validation.

[`FilesystemArtifactStore`](../src/patchbench/storage/filesystem.py) keeps the
D3 `save_diagnosis_artifacts` / `load_diagnosis_artifacts` APIs at exactly three
files. D4's distinct execution APIs save/load four:

```text
results/diagnoses/<diagnosis-id>/
    bundle.json
    diagnosis.json
    audit.json
    execution.json       # D4/D5 completed execution only
```

Persistence is create-only with safe Diagnosis IDs, no overwrite, and cleanup
of a newly created directory on any partial-write failure. Disk JSON is sorted,
indented UTF-8 with a final newline; disk pretty bytes are not canonical hash
material. Save/load recompute integrity and audit, and check ID/hash/outcome
linkage. Audit FAIL round-trips normally. Load-time structural integrity is not
a fresh Experiment peer-selection check; Contrastive execution performs that
check before inference. Hashes detect inconsistent tampering, not coordinated
rewriting by an attacker who can replace every artifact and hash.

`DiagnosisExecutionRecord` binds Diagnosis/Bundle/payload hashes and audit status
to provider provenance. Its SHA covers the canonical record excluding only
`execution_sha256`. Provenance records provider/API/client/version, response ID,
requested/returned models, effort, output limit, timeout, nullable token usage,
duration, prompt/template/schema hashes, input bytes and limit, store/tool/
truncation/retry settings. There are no timestamps, hostnames, workspace paths,
API keys, or raw provider response bodies in this record. Model names are
observations, not immutable weight identities.

## 11. Failure semantics

Failed mode, integrity, permission, and byte preflights never invoke inference.
Contrastive selection verification failure also stops before rendering.
Provider setup/request failures, refusal, and incomplete output are typed errors;
refusal is not semantic abstention and partial JSON is not parsed as Diagnosis.
Invalid provider output fails without persistence. A valid semantic abstention
is a completed Diagnosis. Audit FAIL is also completed and persistable.
No failed-provider Diagnosis directory is created before a typed Diagnosis exists.

## 12. External policy and safety boundary

`DiagnosisExternalLLMPolicy.external_llm_allowed` defaults to false and must be
explicitly enabled by the caller/frozen benchmark policy. Its positive
`max_provider_input_bytes` bounds the sum of exact UTF-8 instructions, input
text, and canonical response schema bytes before invocation. This deterministic
bound is not a token/context-window guarantee. No evidence is dropped to fit.

V1.2 has no secret scanner, PII classifier, private-repository safety decision,
or redaction layer. The caller owns permission to transmit evidence. Tool-less
OpenAI requests and `store=False` do not imply Zero Data Retention, absence of
provider network access, or safety for arbitrary private repositories.

## 13. Human Gold scoring (D6.1)

[`diagnosis_validation.py`](../src/patchbench/application/diagnosis_validation.py)
and [`domain/diagnosis_validation.py`](../src/patchbench/domain/diagnosis_validation.py)
implement deterministic validation contracts for Human Gold. A
`DiagnosisGoldCase` binds route, subject evidence identity and semantic gold.
`compute_diagnosis_gold_sha256()` hashes the complete typed Gold JSON; scores
carry that hash so Blind/Contrastive comparisons cannot mix different gold
definitions.

Route scores compare `route_run_diagnosis()` output with route gold for
operational cases. Semantic scores compare a completed `FailureDiagnosis` with
Human Gold for abstention, preferred/top-k acceptable family, required evidence
coverage, Auditor results, invalid citation issue counts, and forbidden-claim
overclaim review. Human overclaim review is explicit: unreviewed applicable
claims are not silently treated as passed. The scorer is deterministic; it does
not ask an LLM to judge semantic correctness.

## 14. Aggregate and paired metrics (D6.2)

[`diagnosis_metrics.py`](../src/patchbench/application/diagnosis_metrics.py) and
[`domain/diagnosis_metrics.py`](../src/patchbench/domain/diagnosis_metrics.py)
compute exact counts, ratios and macro means from D6.1 scores. Metrics include
family accuracy variants, evidence coverage, abstention accuracy/recall,
unnecessary abstention, Auditor pass/invalid citation rates, and overclaim
review/violation rates.

Blind/Contrastive comparison requires exact pairing by case, subject evidence
identity, Gold hash, applicability and count fields. Paired deltas report
improved/unchanged/regressed transitions for family, abstention, evidence and
Audit outcomes. There is intentionally no composite/global winner score.

## 15. Frozen Validation V1 suite (D6.3)

The frozen suite under `validation/diagnosis/v1` contains 15 cases: 13 semantic
cases and two operational route cases. The frozen manifest byte SHA is
`81147642b9d39cc265c69151d470e03a8c01ed53b6a629a922e0106b4a216d14`; the suite
SHA is `ee724d3825c97f583bbbe13addd3aa0cd61b6ba3265680153486e7274c08643a`.

Semantic composition is two cases each for `incorrect_local_logic`,
`incomplete_cross_file_repair`, `partial_contract_handling`,
`state_consistency_violation` and `regression_introduced`, plus three
`should_abstain` cases. Operational cases cover `agent_command_failed` and
`agent_timed_out`. Contrastive fairness review is locked before final freeze;
Gold is not rewritten after peer evidence is shown.

## 16. Real-provider validation runner and sharding (D6-R1/R2)

[`diagnosis_validation_run.py`](../src/patchbench/application/diagnosis_validation_run.py)
executes the frozen semantic plan after verifying the final freeze. With no
selection it runs all 13 semantic cases, each Blind then Contrastive, for 26
slots. D6-R2 adds optional `selected_case_ids`; each selected semantic case is
still indivisible and contributes exactly Blind then Contrastive. Caller order
cannot reorder frozen suite order, and duplicate, unknown, operational or empty
selections fail before provider calls or output directories.

Runtime ledgers live under `results/diagnosis-validation-v1/<run-id>/run.json`.
Completed Diagnosis artifacts for that run live below the same run root under
`diagnoses/<diagnosis-id>/`. The runner records frozen suite identity, provider
settings, external policy, selected case IDs, exact plan, per-slot status and
completed execution hashes or safe failure reasons. It makes one provider
attempt per slot, stops on first failure, never retries, never resumes, and never
stitches failed run artifacts. Historical D6-R1 full-run ledgers without
`selected_case_ids` remain readable only for the old 26-slot full-run shape;
partial shard ledgers must explicitly contain `selected_case_ids`.

## 17. Acquisition collection and finalized results (D6-R3/R4/R5)

D6-R3 collects completed selected acquisition shards into an immutable collection
after verifying the frozen suite, run ledger invariants, slot order, bundle path
and hash identity, external policy, and persisted Diagnosis execution artifacts.
The final collection is:

```text
results/diagnosis-validation-v1/collections/gpt6astra-pro-v1/collection.json
collection_sha256 = 592bdf99f36afcbd3d54d770a7bf12a484a1e42ca2c1b08867712d174b36a738
```

It contains exactly one successful Blind+Contrastive pair for each of the 13
frozen semantic cases. Runtime ledgers and collections are local/ignored runtime
artifacts rather than committed frozen inputs.

D6-R4 prepares semantic scores and a human overclaim-review packet, then finalizes
26 semantic scores only after applicable forbidden-claim review is complete. The
final semantic scores are:

```text
results/diagnosis-validation-v1/semantic-scores/gpt6astra-pro-v1-semantic-scores-v1/scores.json
score_sha256 = 5c3a74133ae9653d1e7d7906cd45e91810daea9964d35334e57ca65e5aa86e19
```

D6-R5 binds the collection, scoring preparation, finalized semantic scores,
frozen manifest identity and operational Gold into the final deterministic result:

```text
results/diagnosis-validation-v1/final-results/gpt6astra-pro-v1-final-v1/result.json
result_sha256 = cc5ffa71a418d622dcf904963870e447e04cab956d117724f06c0b810e300fa4
```

The final collection used protocol label `gpt6astra-pro-v1`, requested model
`gpt-6-astra`, reasoning effort `none`, and a third-party OpenAI-compatible Pro
route. Because the request used the OpenAI-compatible adapter, persisted provider
provenance uses `provider_name="openai"`; that is not an official OpenAI API
result, does not prove gateway/base URL identity cryptographically, and does not
claim that `gpt-6-astra` is an official OpenAI model name. Earlier `gpt-5.5`
gateway runs are historical attempts, not the final result.

Final metrics on the frozen semantic suite:

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

Operational routing is 2/2 correct for `agent_command_failed` and
`agent_timed_out`. Paired Blind-vs-Contrastive deltas show no failure-family
improvement, nine unchanged non-abstention families and one regression
(`semantic-09`). Required evidence has one improvement (`semantic-07`), one
regression (`semantic-09`) and total satisfied delta -2. Audit has one regression
(`semantic-09`) with two invalid citation issues. Abstention correctness is
unchanged, and both modes have 0/3 abstention recall.

These results are bounded to the frozen Diagnosis Validation V1 suite. Do not
state that Contrastive is generally worse, that PASS peers harm diagnosis, that
Blind is universally better, that the model never overclaims, or that the result
is statistically significant. The 0/13 frozen forbidden-claim violation count
means no violations were marked during the required human review for this suite.

## 18. Invariants worth testing

Accepted tests cover routing and exact line semantics; historical reconstruction,
full bounded source and exact raw bytes; canonical locators; no-call preflights;
strict provider arguments/output and refusal versus abstention; deterministic
prompt/payload/attempt IDs; structural Audit FAIL persistence; create-only
three/four-file compatibility and tamper/cleanup behavior; canonical peer
selection, exact Blind prefix preservation, and stale/forged peer provenance.
See [compiler tests](../tests/test_diagnosis_evidence.py),
[prompt tests](../tests/test_diagnosis_prompt.py),
[adapter tests](../tests/test_diagnosis_provider_openai.py),
[execution tests](../tests/test_diagnosis_execution.py),
[Contrastive execution tests](../tests/test_diagnosis_contrastive_execution.py),
[validation scoring tests](../tests/test_diagnosis_validation_scoring.py),
[metrics tests](../tests/test_diagnosis_metrics.py),
[validation-run tests](../tests/test_diagnosis_validation_run.py),
[collection tests](../tests/test_diagnosis_validation_collection.py), and
[final-result tests](../tests/test_diagnosis_validation_results.py). These are
mostly deterministic/mocked checks; runtime provider artifacts remain local and
ignored even when they feed the final Validation V1 result.
