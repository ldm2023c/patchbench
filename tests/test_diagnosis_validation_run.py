"""D6-R1 frozen provider-run harness with fake providers only."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

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
from patchbench.domain import DiagnosisMode, DiagnosisValidationRunRecord
from patchbench.domain.diagnosis_execution import DiagnosisExternalLLMPolicy
from tests.test_diagnosis_execution import FakeProvider


VALIDATION = Path("validation/diagnosis/v1")
CANDIDATES = Path("fixtures/diagnosis_validation/v1_candidates")


def tree_identity(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


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


def test_complete_fake_provider_run_writes_only_runtime_results_and_preserves_support(tmp_path):
    before_support = tree_identity(CANDIDATES / "_support")
    provider = CountingProvider()
    record = run_frozen_diagnosis_validation(validation_root=VALIDATION, candidate_root=CANDIDATES,
        results_root=tmp_path / "results", run_id="official-test", provider=provider,
        external_policy=policy())
    run_root = tmp_path / "results/diagnosis-validation-v1/official-test"
    assert len(provider.calls) == 26
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
