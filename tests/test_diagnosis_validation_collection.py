"""D6-R3 explicit successful-shard collection; no provider I/O."""

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from patchbench.application.diagnosis_gold_lock import SEMANTIC_CASE_IDS
from patchbench.application.diagnosis_validation_collection import (
    DiagnosisValidationCollectionError,
    collect_diagnosis_validation_shards,
    parse_case_selection,
)
from patchbench.application.diagnosis_validation_run import run_frozen_diagnosis_validation
from patchbench.domain import DiagnosisMode
from patchbench.domain.diagnosis_validation_collection import DiagnosisValidationCollection
from patchbench.domain.diagnosis_execution import DiagnosisExternalLLMPolicy
from tests.test_diagnosis_execution import FakeProvider

VALIDATION = Path("validation/diagnosis/v1")
CANDIDATES = Path("fixtures/diagnosis_validation/v1_candidates")


def policy():
    return DiagnosisExternalLLMPolicy(external_llm_allowed=True, max_provider_input_bytes=1_000_000)


def make_successful_shards(tmp_path, *, cases=SEMANTIC_CASE_IDS):
    results = tmp_path / "results"
    selections = {}
    provider_calls = 0
    for case_id in cases:
        provider = FakeProvider(response_id=f"response-{case_id}")
        run_id = f"run-{case_id}"
        run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
            results_root=results, run_id=run_id, provider=provider, external_policy=policy(),
            selected_case_ids=[case_id])
        assert len(provider.calls) == 2
        provider_calls += len(provider.calls)
        selections[case_id] = run_id
    return results, selections, provider_calls


def run_json(results: Path, run_id: str) -> Path:
    return results / "diagnosis-validation-v1" / run_id / "run.json"


def read_run(results: Path, run_id: str):
    return json.loads(run_json(results, run_id).read_text(encoding="utf-8"))


def write_run(results: Path, run_id: str, data) -> None:
    run_json(results, run_id).write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def collect(tmp_path, results, selections, collection_id="collection"):
    return collect_diagnosis_validation_shards(validation_root=VALIDATION, candidate_root=CANDIDATES,
        results_root=results, collection_id=collection_id, selections=selections)


def assert_reason(exc, reason):
    assert exc.value.reason.value == reason


def test_happy_path_collects_13_explicit_shards_in_canonical_order(tmp_path):
    results, selections, provider_calls = make_successful_shards(tmp_path)
    collection = collect(tmp_path, results, selections)
    root = results / "diagnosis-validation-v1/collections/collection"
    assert provider_calls == 26
    assert [case.case_id for case in collection.cases] == list(SEMANTIC_CASE_IDS)
    assert [case.run_id for case in collection.cases] == [selections[case] for case in SEMANTIC_CASE_IDS]
    assert collection.collection_sha256 is not None
    loaded = DiagnosisValidationCollection.model_validate_json((root / "collection.json").read_bytes())
    assert loaded == collection
    assert not any((root / name).exists() for name in ["diagnoses", "bundle.json", "diagnosis.json"])


def test_selection_argument_order_does_not_affect_persisted_order(tmp_path):
    results, selections, _ = make_successful_shards(tmp_path)
    reversed_selection = {case: selections[case] for case in reversed(SEMANTIC_CASE_IDS)}
    collection = collect(tmp_path, results, reversed_selection)
    assert [case.case_id for case in collection.cases] == list(SEMANTIC_CASE_IDS)


@pytest.mark.parametrize("mutate", [
    lambda selections: selections.pop("semantic-25"),
    lambda selections: selections.__setitem__("semantic-99", selections.pop("semantic-25")),
    lambda selections: selections.__setitem__("operational-01", selections.pop("semantic-25")),
])
def test_invalid_selection_case_set_is_rejected(tmp_path, mutate):
    results, selections, _ = make_successful_shards(tmp_path)
    mutate(selections)
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, selections)
    assert_reason(caught, "invalid_selection")


def test_duplicate_run_id_is_rejected(tmp_path):
    results, selections, _ = make_successful_shards(tmp_path)
    selections["semantic-02"] = selections["semantic-01"]
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, selections)
    assert_reason(caught, "invalid_selection")


def test_malformed_selection_syntax_and_unsafe_ids_are_rejected():
    for raw in ["semantic-01", "semantic-01=", "=run", "a=b=c", "semantic-01=../run"]:
        with pytest.raises(DiagnosisValidationCollectionError):
            parse_case_selection(raw)
    assert parse_case_selection("semantic-01=run-semantic-01") == ("semantic-01", "run-semantic-01")


def test_selected_run_for_another_case_is_rejected(tmp_path):
    results, selections, _ = make_successful_shards(tmp_path)
    selections["semantic-01"], selections["semantic-02"] = selections["semantic-02"], selections["semantic-01"]
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, selections)
    assert_reason(caught, "run_case_mismatch")


def test_full_or_multicase_run_is_rejected(tmp_path):
    results, selections, _ = make_successful_shards(tmp_path)
    run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
        results_root=results, run_id="full-run", provider=FakeProvider(), external_policy=policy())
    selections["semantic-01"] = "full-run"
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, selections)
    assert_reason(caught, "run_case_mismatch")


@pytest.mark.parametrize("slot_index,status", [(0, "pending"), (0, "failed"), (1, "failed")])
def test_pending_or_failed_slots_are_rejected(tmp_path, slot_index, status):
    results, selections, _ = make_successful_shards(tmp_path)
    data = read_run(results, selections["semantic-01"])
    data["slots"][slot_index]["status"] = status
    if status == "failed":
        data["slots"][slot_index]["failure_reason"] = "provider_failed"
    data["slots"][slot_index]["diagnosis_id"] = None
    data["slots"][slot_index]["execution_sha256"] = None
    write_run(results, selections["semantic-01"], data)
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, selections)
    assert caught.value.reason.value in {"invalid_run_ledger", "incomplete_shard"}


@pytest.mark.parametrize("field,reason", [
    ("freeze_manifest_sha256", "frozen_identity_mismatch"),
    ("frozen_suite_sha256", "frozen_identity_mismatch"),
])
def test_frozen_identity_mismatch_is_rejected(tmp_path, field, reason):
    results, selections, _ = make_successful_shards(tmp_path)
    data = read_run(results, selections["semantic-01"])
    data[field] = "0" * 64
    write_run(results, selections["semantic-01"], data)
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, selections)
    assert_reason(caught, reason)


def test_provider_settings_mismatch_is_rejected(tmp_path):
    results, selections, _ = make_successful_shards(tmp_path)
    data = read_run(results, selections["semantic-02"])
    data["provider_settings"]["requested_model"] = "other-model"
    write_run(results, selections["semantic-02"], data)
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, selections)
    assert_reason(caught, "provider_configuration_mismatch")


def test_external_policy_mismatch_is_rejected(tmp_path):
    results, selections, _ = make_successful_shards(tmp_path)
    data = read_run(results, selections["semantic-02"])
    data["external_policy"]["max_provider_input_bytes"] = 999999
    write_run(results, selections["semantic-02"], data)
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, selections)
    assert_reason(caught, "external_policy_mismatch")


def test_frozen_bundle_identity_or_plan_mismatch_is_rejected(tmp_path):
    results, selections, _ = make_successful_shards(tmp_path)
    data = read_run(results, selections["semantic-01"])
    data["plan"][0]["frozen_bundle_sha256"] = "0" * 64
    data["slots"][0]["frozen_bundle_sha256"] = "0" * 64
    write_run(results, selections["semantic-01"], data)
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, selections)
    assert_reason(caught, "frozen_bundle_plan_mismatch")


@pytest.mark.parametrize("field", ["diagnosis_id", "execution_sha256"])
def test_ledger_slot_identity_mismatch_with_artifact_is_rejected(tmp_path, field):
    results, selections, _ = make_successful_shards(tmp_path)
    data = read_run(results, selections["semantic-01"])
    data["slots"][0][field] = "diag-x" if field == "diagnosis_id" else "0" * 64
    write_run(results, selections["semantic-01"], data)
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, selections)
    assert_reason(caught, "diagnosis_artifact_mismatch")


def test_tampered_or_missing_diagnosis_execution_artifact_is_rejected(tmp_path):
    results, selections, _ = make_successful_shards(tmp_path)
    data = read_run(results, selections["semantic-01"])
    diagnosis_id = data["slots"][0]["diagnosis_id"]
    execution = results / "diagnosis-validation-v1" / selections["semantic-01"] / "diagnoses" / diagnosis_id / "execution.json"
    payload = json.loads(execution.read_text(encoding="utf-8"))
    payload["provider"]["returned_model"] = "tampered-model"
    execution.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, selections)
    assert_reason(caught, "diagnosis_artifact_mismatch")


def test_unsafe_collection_id_and_existing_collection_directory_are_rejected(tmp_path):
    results, selections, _ = make_successful_shards(tmp_path)
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, selections, collection_id="../bad")
    assert_reason(caught, "invalid_collection_id")
    collect(tmp_path, results, selections, collection_id="once")
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, selections, collection_id="once")
    assert_reason(caught, "collection_already_exists")


def test_missing_selected_run_is_rejected(tmp_path):
    results, selections, _ = make_successful_shards(tmp_path)
    selections["semantic-01"] = "missing-run"
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, selections)
    assert_reason(caught, "missing_selected_run")


def test_no_automatic_discovery_path_exists(tmp_path):
    results, _selections, _ = make_successful_shards(tmp_path)
    with pytest.raises(DiagnosisValidationCollectionError) as caught:
        collect(tmp_path, results, {})
    assert_reason(caught, "invalid_selection")


def test_collection_hash_validation_rejects_tampering(tmp_path):
    results, selections, _ = make_successful_shards(tmp_path)
    collection = collect(tmp_path, results, selections)
    raw = collection.model_dump(mode="json")
    raw["cases"][0]["run_id"] = "other-run"
    with pytest.raises(ValidationError):
        DiagnosisValidationCollection.model_validate(raw)
