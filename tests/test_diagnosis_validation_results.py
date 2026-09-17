"""D6-R5 final deterministic Diagnosis validation metrics orchestration."""

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from patchbench.application.diagnosis_gold_lock import OPERATIONAL_CASE_IDS, SEMANTIC_CASE_IDS
from patchbench.application.diagnosis_metrics import (
    aggregate_route_scores,
    aggregate_semantic_scores,
    compare_blind_contrastive,
)
from patchbench.application.diagnosis_suite import _verify_embedded_gold_lock
from patchbench.application.diagnosis_validation_results import (
    DiagnosisValidationResultError,
    _load_operational_gold,
    _load_operational_run,
    compute_diagnosis_validation_results,
)
from patchbench.application.diagnosis_validation_scoring import (
    finalize_diagnosis_validation_scoring,
    prepare_diagnosis_validation_scoring,
)
from patchbench.domain import DiagnosisMode
from patchbench.domain.diagnosis_validation_collection import (
    DiagnosisValidationCollection,
    compute_diagnosis_validation_collection_sha256,
)
from patchbench.domain.diagnosis_validation_results import (
    DiagnosisValidationFinalResult,
    compute_diagnosis_validation_result_sha256,
)
from patchbench.domain.diagnosis_validation_scoring import (
    DiagnosisValidationFinalScores,
    DiagnosisValidationScoringPreparation,
    compute_diagnosis_validation_final_scores_sha256,
    compute_diagnosis_validation_preparation_sha256,
)
from tests.test_diagnosis_validation_collection import (
    CANDIDATES,
    VALIDATION,
    collect as collect_shards,
    make_successful_shards,
)


def _json_bytes(value) -> bytes:
    raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


@pytest.fixture(scope="module")
def d6r5_base(tmp_path_factory):
    root = tmp_path_factory.mktemp("d6r5-base")
    results, selections, provider_calls = make_successful_shards(root)
    collect_shards(root, results, selections, collection_id="collection")
    preparation, packet = prepare_diagnosis_validation_scoring(
        validation_root=VALIDATION,
        candidate_root=CANDIDATES,
        results_root=results,
        collection_id="collection",
        preparation_id="prep",
    )
    review_path = root / "review.json"
    review_path.write_text(json.dumps({
        "schema_version": 1,
        "preparation_id": preparation.preparation_id,
        "preparation_sha256": preparation.preparation_sha256,
        "reviews": [
            {"schema_version": 1, "case_id": item.case_id,
             "diagnosis_id": item.diagnosis_id, "violated_claim_ids": []}
            for item in packet.items
        ],
    }, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    finalize_diagnosis_validation_scoring(
        validation_root=VALIDATION,
        candidate_root=CANDIDATES,
        results_root=results,
        preparation_id="prep",
        review_file=review_path,
        score_id="scores",
    )
    return {"results": results, "provider_calls": provider_calls}


@pytest.fixture
def d6r5_results(tmp_path, d6r5_base):
    target = tmp_path / "results"
    shutil.copytree(d6r5_base["results"], target)
    return target


def _score_path(results: Path) -> Path:
    return results / "diagnosis-validation-v1/semantic-scores/scores/scores.json"


def _prep_path(results: Path) -> Path:
    return results / "diagnosis-validation-v1/scoring-preparations/prep/preparation.json"


def _collection_path(results: Path) -> Path:
    return results / "diagnosis-validation-v1/collections/collection/collection.json"


def _load_scores(results: Path) -> DiagnosisValidationFinalScores:
    return DiagnosisValidationFinalScores.model_validate_json(_score_path(results).read_bytes())


def _write_scores(results: Path, raw: dict) -> DiagnosisValidationFinalScores:
    raw = dict(raw)
    raw["score_sha256"] = None
    scores = DiagnosisValidationFinalScores.model_validate(raw)
    scores = DiagnosisValidationFinalScores.model_validate(scores.model_dump(mode="json") | {
        "score_sha256": compute_diagnosis_validation_final_scores_sha256(scores),
    })
    _score_path(results).write_bytes(_json_bytes(scores))
    return scores


def _write_preparation(results: Path, raw: dict) -> DiagnosisValidationScoringPreparation:
    raw = dict(raw)
    raw["preparation_sha256"] = None
    preparation = DiagnosisValidationScoringPreparation.model_validate(raw)
    preparation = DiagnosisValidationScoringPreparation.model_validate(preparation.model_dump(mode="json") | {
        "preparation_sha256": compute_diagnosis_validation_preparation_sha256(preparation),
    })
    _prep_path(results).write_bytes(_json_bytes(preparation))
    return preparation


def _write_collection(results: Path, raw: dict) -> DiagnosisValidationCollection:
    raw = dict(raw)
    raw["collection_sha256"] = None
    collection = DiagnosisValidationCollection.model_validate(raw)
    collection = DiagnosisValidationCollection.model_validate(collection.model_dump(mode="json") | {
        "collection_sha256": compute_diagnosis_validation_collection_sha256(collection),
    })
    _collection_path(results).write_bytes(_json_bytes(collection))
    return collection


def _compute(results: Path, result_id="result"):
    return compute_diagnosis_validation_results(
        validation_root=VALIDATION,
        candidate_root=CANDIDATES,
        results_root=results,
        semantic_score_id="scores",
        result_id=result_id,
    )


def _assert_reason(caught, reason: str) -> None:
    assert caught.value.reason.value == reason


def test_happy_path_computes_operational_and_semantic_metrics(d6r5_results, d6r5_base):
    result = _compute(d6r5_results)
    assert d6r5_base["provider_calls"] == 26
    assert [score.case_id for score in result.operational_scores] == list(OPERATIONAL_CASE_IDS)
    assert result.operational_aggregate.case_count == 2
    assert result.semantic_comparison.blind_aggregate.case_count == 13
    assert result.semantic_comparison.contrastive_aggregate.case_count == 13
    assert result.semantic_comparison.pair_count == 13
    assert not hasattr(result, "winner")
    assert not hasattr(result, "composite_score")
    loaded = DiagnosisValidationFinalResult.model_validate_json(
        (d6r5_results / "diagnosis-validation-v1/final-results/result/result.json").read_bytes())
    assert loaded == result


def test_metrics_match_existing_d6_2_functions(d6r5_results):
    scores = _load_scores(d6r5_results).scores
    expected_operational = result = _compute(d6r5_results).operational_scores
    blind, contrastive = scores[0::2], scores[1::2]
    assert result == expected_operational
    computed = DiagnosisValidationFinalResult.model_validate_json(
        (d6r5_results / "diagnosis-validation-v1/final-results/result/result.json").read_bytes())
    assert computed.operational_aggregate == aggregate_route_scores(expected_operational)
    assert computed.semantic_comparison.blind_aggregate == aggregate_semantic_scores(blind)
    assert computed.semantic_comparison.contrastive_aggregate == aggregate_semantic_scores(contrastive)
    assert computed.semantic_comparison == compare_blind_contrastive(blind, contrastive)


def test_command_failed_and_timed_out_cases_score_through_route_scorer(d6r5_results):
    result = _compute(d6r5_results)
    reasons = {score.case_id: score.actual_reason.value for score in result.operational_scores}
    assert reasons == {
        "operational-01": "agent_command_failed",
        "operational-02": "agent_timed_out",
    }
    assert all(score.correct for score in result.operational_scores)


@pytest.mark.parametrize("mutation,reason", [
    ("sha", "missing_or_invalid_semantic_score"),
    ("id", "semantic_score_identity_mismatch"),
    ("order", "semantic_score_identity_mismatch"),
    ("unfinished", "unfinished_semantic_score_review"),
    ("gold", "semantic_score_identity_mismatch"),
    ("subject", "semantic_score_identity_mismatch"),
])
def test_semantic_score_artifact_validation(d6r5_results, mutation, reason):
    raw = json.loads(_score_path(d6r5_results).read_text(encoding="utf-8"))
    if mutation == "sha":
        raw["scores"][0]["diagnosis_id"] = "diag-tampered"
        _score_path(d6r5_results).write_text(json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    elif mutation == "id":
        raw["score_id"] = "other-score"
        _write_scores(d6r5_results, raw)
    elif mutation == "order":
        raw["scores"][0], raw["scores"][1] = raw["scores"][1], raw["scores"][0]
        _write_scores(d6r5_results, raw)
    elif mutation == "unfinished":
        raw["scores"][0]["overclaim_reviewed"] = False
        raw["scores"][0]["overclaim_violation"] = None
        raw["scores"][0]["violated_claim_ids"] = []
        _write_scores(d6r5_results, raw)
    elif mutation == "gold":
        raw["scores"][0]["gold_sha256"] = "0" * 64
        _write_scores(d6r5_results, raw)
    elif mutation == "subject":
        raw["scores"][0]["subject_evidence_sha256"] = "0" * 64
        _write_scores(d6r5_results, raw)
    with pytest.raises(DiagnosisValidationResultError) as caught:
        _compute(d6r5_results)
    _assert_reason(caught, reason)


def test_missing_semantic_score_artifact_is_rejected(d6r5_results):
    _score_path(d6r5_results).unlink()
    with pytest.raises(DiagnosisValidationResultError) as caught:
        _compute(d6r5_results)
    _assert_reason(caught, "missing_or_invalid_semantic_score")


def test_preparation_identity_and_collection_linkage_are_verified(d6r5_results):
    raw = json.loads(_prep_path(d6r5_results).read_text(encoding="utf-8"))
    raw["collection_sha256"] = "0" * 64
    _write_preparation(d6r5_results, raw)
    with pytest.raises(DiagnosisValidationResultError) as caught:
        _compute(d6r5_results)
    _assert_reason(caught, "preparation_identity_mismatch")


def test_preparation_sha_mismatch_is_rejected(d6r5_results):
    raw = json.loads(_prep_path(d6r5_results).read_text(encoding="utf-8"))
    raw["cases"][0]["case_id"] = "semantic-x"
    _prep_path(d6r5_results).write_text(json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(DiagnosisValidationResultError) as caught:
        _compute(d6r5_results)
    _assert_reason(caught, "invalid_preparation")


def test_collection_sha_and_order_are_verified(d6r5_results):
    raw = json.loads(_collection_path(d6r5_results).read_text(encoding="utf-8"))
    raw["cases"][0], raw["cases"][1] = raw["cases"][1], raw["cases"][0]
    _write_collection(d6r5_results, raw)
    with pytest.raises(DiagnosisValidationResultError) as caught:
        _compute(d6r5_results)
    _assert_reason(caught, "collection_identity_mismatch")


def test_collection_sha_mismatch_is_rejected(d6r5_results):
    raw = json.loads(_collection_path(d6r5_results).read_text(encoding="utf-8"))
    raw["cases"][0]["run_id"] = "other-run"
    _collection_path(d6r5_results).write_text(json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(DiagnosisValidationResultError) as caught:
        _compute(d6r5_results)
    _assert_reason(caught, "invalid_collection")


def test_frozen_manifest_and_gold_lock_identity_mismatch_rejected(tmp_path, d6r5_results):
    validation = tmp_path / "validation"
    shutil.copytree(VALIDATION, validation)
    manifest = json.loads((validation / "freeze-manifest.json").read_text(encoding="utf-8"))
    manifest["suite_sha256"] = "0" * 64
    (validation / "freeze-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(DiagnosisValidationResultError) as caught:
        compute_diagnosis_validation_results(validation_root=validation, candidate_root=CANDIDATES,
            results_root=d6r5_results, semantic_score_id="scores", result_id="result")
    _assert_reason(caught, "frozen_validation_identity_mismatch")


def test_operational_gold_run_and_routing_helpers_reject_mismatches(tmp_path):
    validation = tmp_path / "validation"
    shutil.copytree(VALIDATION, validation)
    gold_lock = _verify_embedded_gold_lock(VALIDATION)
    operational = {case.case_id: case for case in gold_lock.cases if case.case_id in OPERATIONAL_CASE_IDS}

    gold_raw = json.loads((validation / operational["operational-01"].route_gold_path).read_text(encoding="utf-8"))
    gold_raw["case_id"] = "other-case"
    (validation / operational["operational-01"].route_gold_path).write_text(json.dumps(gold_raw, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(DiagnosisValidationResultError) as caught:
        _load_operational_gold(validation, operational["operational-01"])
    _assert_reason(caught, "invalid_operational_gold")

    validation = tmp_path / "validation-run"
    shutil.copytree(VALIDATION, validation)
    run_raw = json.loads((validation / operational["operational-01"].run_record_path).read_text(encoding="utf-8"))
    run_raw["task_id"] = "other-task"
    (validation / operational["operational-01"].run_record_path).write_text(json.dumps(run_raw, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(DiagnosisValidationResultError) as caught:
        _load_operational_run(validation, operational["operational-01"])
    _assert_reason(caught, "operational_provenance_mismatch")

    validation = tmp_path / "validation-routing"
    shutil.copytree(VALIDATION, validation)
    run_raw = json.loads((validation / operational["operational-01"].run_record_path).read_text(encoding="utf-8"))
    run_raw["agent"]["status"] = "timed_out"
    run_raw["agent"]["exit_code"] = None
    (validation / operational["operational-01"].run_record_path).write_text(json.dumps(run_raw, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    changed = operational["operational-01"].model_copy(update={
        "run_record_sha256": hashlib_sha256_run(run_raw),
    })
    with pytest.raises(DiagnosisValidationResultError) as caught:
        _load_operational_run(validation, changed)
    _assert_reason(caught, "operational_routing_mismatch")


def hashlib_sha256_run(raw):
    from patchbench.domain.diagnosis_integrity import canonical_json_bytes
    from patchbench.domain.models import RunRecord
    import hashlib
    return hashlib.sha256(canonical_json_bytes(RunRecord.model_validate(raw).model_dump(mode="json"))).hexdigest()


def test_result_persistence_create_only_failure_cleanup_and_retry(d6r5_results, monkeypatch):
    with pytest.raises(DiagnosisValidationResultError) as caught:
        compute_diagnosis_validation_results(validation_root=VALIDATION, candidate_root=CANDIDATES,
            results_root=d6r5_results, semantic_score_id="scores", result_id="../bad")
    _assert_reason(caught, "invalid_result_id")

    _compute(d6r5_results, result_id="once")
    with pytest.raises(DiagnosisValidationResultError) as caught:
        _compute(d6r5_results, result_id="once")
    _assert_reason(caught, "result_already_exists")

    preexisting = d6r5_results / "diagnosis-validation-v1/final-results/preexisting"
    preexisting.mkdir(parents=True)
    (preexisting / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(DiagnosisValidationResultError):
        _compute(d6r5_results, result_id="preexisting")
    assert (preexisting / "keep.txt").read_text(encoding="utf-8") == "keep"

    root = d6r5_results / "diagnosis-validation-v1/final-results/retry"
    original_write = Path.write_bytes

    def fail_write(path, data):
        if path == root / "result.json":
            raise OSError("injected")
        return original_write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_bytes", fail_write)
        with pytest.raises(DiagnosisValidationResultError) as caught:
            _compute(d6r5_results, result_id="retry")
    _assert_reason(caught, "result_persistence_failed")
    assert not root.exists()
    _compute(d6r5_results, result_id="retry")
    assert (root / "result.json").exists()


def test_result_sha_tamper_rejected(d6r5_results):
    result = _compute(d6r5_results)
    raw = result.model_dump(mode="json")
    raw["operational_scores"][0]["correct"] = False
    with pytest.raises(ValidationError):
        DiagnosisValidationFinalResult.model_validate(raw)
    assert result.result_sha256 == compute_diagnosis_validation_result_sha256(result)
