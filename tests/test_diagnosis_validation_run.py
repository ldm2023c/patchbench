"""D6-R1 frozen provider-run harness with fake providers only."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from patchbench.application.diagnosis_execution import (
    DiagnosisExecutionError,
    DiagnosisExecutionReason,
)
from patchbench.application.diagnosis_gold_lock import SEMANTIC_CASE_IDS
from patchbench.application.diagnosis_validation_run import (
    DiagnosisValidationRunError,
    build_diagnosis_validation_run_plan,
    run_frozen_diagnosis_validation,
)
from patchbench.domain import DiagnosisMode, DiagnosisRoute, DiagnosisValidationRunRecord
from patchbench.domain.diagnosis_execution import DiagnosisExternalLLMPolicy
from patchbench.domain.diagnosis_gold_lock import DiagnosisGoldLockSuite
from patchbench.domain.diagnosis_validation_run import DiagnosisValidationRunSlotResult
from tests.test_diagnosis_execution import FakeProvider


VALIDATION = Path("validation/diagnosis/v1")
CANDIDATES = Path("fixtures/diagnosis_validation/v1_candidates")


def tree_identity(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}




def frozen_suite_semantic_cases():
    suite = DiagnosisGoldLockSuite.model_validate_json((VALIDATION / "suite.json").read_bytes())
    return [case for case in suite.cases if case.expected_route is DiagnosisRoute.SEMANTIC_DIAGNOSIS]

def policy(limit=1_000_000):
    return DiagnosisExternalLLMPolicy(
        external_llm_allowed=True,
        max_provider_input_bytes=limit,
    )


class CountingProvider(FakeProvider):
    def __init__(self, *, fail_at: int | None = None,
                 reason: DiagnosisExecutionReason | None = None):
        super().__init__()
        self.fail_at = fail_at
        self.reason = reason or DiagnosisExecutionReason.PROVIDER_FAILED

    def infer(self, request):
        if self.fail_at is not None and len(self.calls) + 1 == self.fail_at:
            self.calls.append(request)
            raise DiagnosisExecutionError(self.reason)
        return super().infer(request)


def test_tampered_freeze_makes_zero_provider_calls(tmp_path):
    frozen = tmp_path / "validation"
    shutil.copytree(VALIDATION, frozen)
    (frozen / "suite.json").write_bytes((frozen / "suite.json").read_bytes() + b" ")
    provider = CountingProvider()
    with pytest.raises(DiagnosisValidationRunError) as caught:
        run_frozen_diagnosis_validation(validation_root=frozen, candidate_root=CANDIDATES,
            results_root=tmp_path / "results", run_id="run", provider=provider,
            external_policy=policy())
    assert caught.value.reason.value == "invalid_freeze"
    assert provider.calls == []
    assert not (tmp_path / "results/diagnosis-validation-v1/run").exists()


def test_exact_plan_is_26_slots_case_order_blind_then_contrastive():
    plan = build_diagnosis_validation_run_plan(VALIDATION)
    assert len(plan) == 26
    assert [(slot.case_id, slot.mode) for slot in plan] == [
        (case_id, mode)
        for case_id in SEMANTIC_CASE_IDS
        for mode in (DiagnosisMode.BLIND, DiagnosisMode.CONTRASTIVE)
    ]


def test_plan_is_driven_by_frozen_suite_semantic_case_order_and_bundle_fields():
    semantic_cases = frozen_suite_semantic_cases()
    plan = build_diagnosis_validation_run_plan(VALIDATION)
    assert len(semantic_cases) == 13
    assert [(slot.case_id, slot.mode, slot.frozen_bundle_path, slot.frozen_bundle_sha256)
            for slot in plan] == [
        expected
        for case in semantic_cases
        for expected in (
            (case.case_id, DiagnosisMode.BLIND, case.blind_bundle_path, case.blind_bundle_sha256),
            (case.case_id, DiagnosisMode.CONTRASTIVE,
             f"cases/{case.case_id}/contrastive-bundle.json",
             next(slot.frozen_bundle_sha256 for slot in plan
                  if slot.case_id == case.case_id and slot.mode is DiagnosisMode.CONTRASTIVE)),
        )
    ]


def test_complete_fake_provider_run_writes_only_runtime_results_and_preserves_support(tmp_path):
    before_support = tree_identity(CANDIDATES / "_support")
    provider = CountingProvider()
    record = run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
        results_root=tmp_path / "results", run_id="official-test", provider=provider,
        external_policy=policy())
    run_root = tmp_path / "results/diagnosis-validation-v1/official-test"
    assert len(provider.calls) == 26
    assert record.selected_case_ids == list(SEMANTIC_CASE_IDS)
    assert {slot.status for slot in record.slots} == {"completed"}
    assert len(list((run_root / "diagnoses").iterdir())) == 26
    assert (run_root / "run.json").exists()
    assert not any(path.is_file() for path in Path("validation/diagnosis/v1").glob("**/diagnoses/**"))
    assert tree_identity(CANDIDATES / "_support") == before_support
    raw = (run_root / "run.json").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in raw
    assert "sk-" not in raw
    assert "environment" not in raw.lower()
    loaded = DiagnosisValidationRunRecord.model_validate_json((run_root / "run.json").read_bytes())
    assert loaded == record
    assert loaded.provider_settings.requested_model == "test-model"
    assert loaded.external_policy.max_provider_input_bytes == 1_000_000
    assert loaded.freeze_manifest_sha256 == hashlib.sha256(
        (VALIDATION / "freeze-manifest.json").read_bytes()).hexdigest()


def test_contrastive_verification_reads_source_support(tmp_path):
    candidates = tmp_path / "candidates"
    shutil.copytree(CANDIDATES, candidates)
    path = candidates / "_support/semantic-01/results/semantic-01-peer/test.log"
    path.write_bytes(path.read_bytes() + b"drift\n")
    provider = CountingProvider()
    with pytest.raises(DiagnosisValidationRunError) as caught:
        run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=candidates,
            results_root=tmp_path / "results", run_id="support-drift", provider=provider,
            external_policy=policy())
    assert caught.value.reason.value == "invalid_freeze"
    assert provider.calls == []
    assert not (tmp_path / "results/diagnosis-validation-v1/support-drift").exists()


def test_provider_failure_on_slot_n_stops_without_retry(tmp_path):
    provider = CountingProvider(fail_at=5, reason=DiagnosisExecutionReason.PROVIDER_REFUSED)
    record = run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
        results_root=tmp_path / "results", run_id="fails-on-five", provider=provider,
        external_policy=policy())
    assert len(provider.calls) == 5
    assert [slot.status for slot in record.slots[:5]] == [
        "completed", "completed", "completed", "completed", "failed"]
    assert record.slots[4].failure_reason == "provider_refused"
    assert {slot.status for slot in record.slots[5:]} == {"pending"}


@pytest.mark.parametrize("reason", [
    DiagnosisExecutionReason.PROVIDER_REFUSED,
    DiagnosisExecutionReason.PROVIDER_INCOMPLETE,
    DiagnosisExecutionReason.INVALID_PROVIDER_OUTPUT,
])
def test_existing_execution_failure_reasons_are_recorded_safely(tmp_path, reason):
    provider = CountingProvider(fail_at=1, reason=reason)
    record = run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
        results_root=tmp_path / "results", run_id=f"fail-{reason.value}", provider=provider,
        external_policy=policy())
    assert len(provider.calls) == 1
    assert record.slots[0].status == "failed"
    assert record.slots[0].failure_reason == reason.value
    assert {slot.status for slot in record.slots[1:]} == {"pending"}


def test_existing_run_id_is_rejected_without_overwrite(tmp_path):
    root = tmp_path / "results/diagnosis-validation-v1/reused"
    root.mkdir(parents=True)
    marker = root / "marker.txt"
    marker.write_text("keep", encoding="utf-8")
    provider = CountingProvider()
    with pytest.raises(DiagnosisValidationRunError) as caught:
        run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
            results_root=tmp_path / "results", run_id="reused", provider=provider,
            external_policy=policy())
    assert caught.value.reason.value == "run_already_exists"
    assert provider.calls == []
    assert marker.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("unsafe_run_id", ["../escape", "a/b", "/tmp/escape", "a\\b", ".", "..", "bad\nrun"])
def test_unsafe_run_id_is_rejected_before_output_or_provider_call(tmp_path, unsafe_run_id):
    provider = CountingProvider()
    with pytest.raises(DiagnosisValidationRunError) as caught:
        run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
            results_root=tmp_path / "results", run_id=unsafe_run_id, provider=provider,
            external_policy=policy())
    assert caught.value.reason.value == "invalid_run_id"
    assert provider.calls == []
    assert not (tmp_path / "escape").exists()
    assert not (tmp_path / "results" / "escape").exists()
    assert not (tmp_path / "results/diagnosis-validation-v1").exists()


def test_valid_normal_run_id_is_accepted(tmp_path):
    provider = CountingProvider(fail_at=1, reason=DiagnosisExecutionReason.PROVIDER_REFUSED)
    record = run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
        results_root=tmp_path / "results", run_id="run-2026_09.16", provider=provider,
        external_policy=policy())
    assert len(provider.calls) == 1
    assert record.run_id == "run-2026_09.16"
    assert (tmp_path / "results/diagnosis-validation-v1/run-2026_09.16/run.json").exists()


def test_slot_result_status_payload_invariants():
    slot = build_diagnosis_validation_run_plan(VALIDATION)[0]
    with pytest.raises(ValidationError):
        DiagnosisValidationRunSlotResult(**slot.model_dump(mode="json"), status="pending",
            failure_reason="provider_failed")
    with pytest.raises(ValidationError):
        DiagnosisValidationRunSlotResult(**slot.model_dump(mode="json"), status="completed",
            diagnosis_id="diag-x")
    with pytest.raises(ValidationError):
        DiagnosisValidationRunSlotResult(**slot.model_dump(mode="json"), status="failed")


def test_run_record_rejects_slots_that_do_not_match_plan(tmp_path):
    provider = CountingProvider(fail_at=1, reason=DiagnosisExecutionReason.PROVIDER_REFUSED)
    record = run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
        results_root=tmp_path / "results", run_id="mismatch-base", provider=provider,
        external_policy=policy())
    raw = record.model_dump(mode="json")
    raw["slots"][0]["case_id"] = raw["plan"][1]["case_id"]
    raw["slots"][0]["mode"] = raw["plan"][1]["mode"]
    raw["slots"][0]["frozen_bundle_path"] = raw["plan"][1]["frozen_bundle_path"]
    raw["slots"][0]["frozen_bundle_sha256"] = raw["plan"][1]["frozen_bundle_sha256"]
    with pytest.raises(ValidationError):
        DiagnosisValidationRunRecord.model_validate(raw)


def test_one_case_shard_runs_exact_blind_contrastive_pair(tmp_path):
    provider = CountingProvider()
    record = run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
        results_root=tmp_path / "results", run_id="shard-semantic-01", provider=provider,
        external_policy=policy(), selected_case_ids=["semantic-01"])
    assert len(provider.calls) == 2
    assert record.selected_case_ids == ["semantic-01"]
    assert [(slot.case_id, slot.mode) for slot in record.plan] == [
        ("semantic-01", DiagnosisMode.BLIND),
        ("semantic-01", DiagnosisMode.CONTRASTIVE),
    ]
    assert [slot.status for slot in record.slots] == ["completed", "completed"]
    assert len(list((tmp_path / "results/diagnosis-validation-v1/shard-semantic-01/diagnoses").iterdir())) == 2


def test_multi_case_selection_preserves_frozen_order_not_caller_order(tmp_path):
    provider = CountingProvider(fail_at=1, reason=DiagnosisExecutionReason.PROVIDER_REFUSED)
    record = run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
        results_root=tmp_path / "results", run_id="shard-two", provider=provider,
        external_policy=policy(), selected_case_ids=["semantic-06", "semantic-05"])
    assert len(provider.calls) == 1
    assert record.selected_case_ids == ["semantic-05", "semantic-06"]
    assert [(slot.case_id, slot.mode) for slot in record.plan] == [
        ("semantic-05", DiagnosisMode.BLIND),
        ("semantic-05", DiagnosisMode.CONTRASTIVE),
        ("semantic-06", DiagnosisMode.BLIND),
        ("semantic-06", DiagnosisMode.CONTRASTIVE),
    ]


@pytest.mark.parametrize("selection", [
    ["semantic-01", "semantic-01"],
    ["semantic-99"],
    ["operational-01"],
    [],
])
def test_invalid_case_selection_fails_before_provider_or_output(tmp_path, selection):
    provider = CountingProvider()
    with pytest.raises(DiagnosisValidationRunError) as caught:
        run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
            results_root=tmp_path / "results", run_id="bad-selection", provider=provider,
            external_policy=policy(), selected_case_ids=selection)
    assert caught.value.reason.value == "invalid_selection"
    assert provider.calls == []
    assert not (tmp_path / "results/diagnosis-validation-v1/bad-selection").exists()


def test_one_case_failure_preserves_completed_blind_and_failed_contrastive_without_retry(tmp_path):
    provider = CountingProvider(fail_at=2, reason=DiagnosisExecutionReason.PROVIDER_FAILED)
    record = run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
        results_root=tmp_path / "results", run_id="shard-fail-second", provider=provider,
        external_policy=policy(), selected_case_ids=["semantic-01"])
    assert len(provider.calls) == 2
    assert [(slot.case_id, slot.mode, slot.status) for slot in record.slots] == [
        ("semantic-01", DiagnosisMode.BLIND, "completed"),
        ("semantic-01", DiagnosisMode.CONTRASTIVE, "failed"),
    ]
    assert record.slots[1].failure_reason == "provider_failed"


def test_run_record_rejects_selected_case_ids_that_do_not_match_plan(tmp_path):
    provider = CountingProvider(fail_at=1, reason=DiagnosisExecutionReason.PROVIDER_REFUSED)
    record = run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
        results_root=tmp_path / "results", run_id="selected-mismatch", provider=provider,
        external_policy=policy(), selected_case_ids=["semantic-01"])
    raw = record.model_dump(mode="json")
    raw["selected_case_ids"] = ["semantic-02"]
    with pytest.raises(ValidationError):
        DiagnosisValidationRunRecord.model_validate(raw)


def test_run_record_rejects_missing_contrastive_pair(tmp_path):
    provider = CountingProvider(fail_at=1, reason=DiagnosisExecutionReason.PROVIDER_REFUSED)
    record = run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
        results_root=tmp_path / "results", run_id="missing-pair", provider=provider,
        external_policy=policy(), selected_case_ids=["semantic-01"])
    raw = record.model_dump(mode="json")
    raw["plan"] = raw["plan"][:1]
    raw["slots"] = raw["slots"][:1]
    with pytest.raises(ValidationError):
        DiagnosisValidationRunRecord.model_validate(raw)


def test_legacy_full_run_record_without_selected_case_ids_is_readable(tmp_path):
    provider = CountingProvider(fail_at=1, reason=DiagnosisExecutionReason.PROVIDER_REFUSED)
    record = run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
        results_root=tmp_path / "results", run_id="legacy-readable", provider=provider,
        external_policy=policy())
    raw = record.model_dump(mode="json")
    raw.pop("selected_case_ids")
    loaded = DiagnosisValidationRunRecord.model_validate(raw)
    assert loaded.selected_case_ids == list(SEMANTIC_CASE_IDS)
