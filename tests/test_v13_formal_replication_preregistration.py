"""Provider-free tests for the V1.3 Replication-01 preregistration."""

from collections import Counter
import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from patchbench.domain.benchmark import BenchmarkDesignManifest
from patchbench.domain.formal_replication import (
    V13FormalReplicationPreregistration,
    compute_v13_formal_replication_preregistration_sha256,
)
from scripts import v13_formal_replication_preregistration as replication
from scripts.v13_formal_preregistration import DESIGN_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_builder_freezes_new_identity_and_complete_fresh_plan():
    value = replication.build_formal_replication_preregistration(PROJECT_ROOT)
    assert value.replication_id == "patchbench-v1.3-replication-01"
    assert value.study_id == "patchbench-v1.3-formal-replication-01"
    assert value.formal_results_namespace == "results/v1.3-formal-replication-01"
    assert value.formal_results_namespace != value.original_results_namespace
    assert value.planned_slot_count == len(value.slots) == 108
    assert tuple(slot.ordinal for slot in value.slots) == tuple(range(1, 109))
    assert len({slot.slot_id for slot in value.slots}) == 108
    assert all(slot.slot_id.startswith("rep01-r") for slot in value.slots)
    assert all(slot.replication_index == 1 for slot in value.slots)
    assert "example_bug" not in value.task_order


def test_replication_balance_and_frozen_latin_rotation():
    value = replication.build_formal_replication_preregistration(PROJECT_ROOT)
    assert Counter(slot.config_id for slot in value.slots) == {
        config_id: 36 for config_id in value.base_agent_order
    }
    assert set(Counter(slot.task_id for slot in value.slots).values()) == {9}
    assert set(Counter((slot.task_id, slot.config_id)
                       for slot in value.slots).values()) == {3}
    base = value.base_agent_order
    assert value.agent_order_by_repetition == (
        base, (base[1], base[2], base[0]), (base[2], base[0], base[1])
    )
    for repetition in range(1, 4):
        slots = [slot for slot in value.slots
                 if slot.repetition_index == repetition]
        assert [slots[index].task_id for index in range(0, 36, 3)] == \
            list(value.task_order)
        assert all(
            tuple(item.config_id for item in slots[index:index + 3])
            == value.agent_order_by_repetition[repetition - 1]
            for index in range(0, 36, 3)
        )


def test_replication_capability_and_difficulty_balance():
    value = replication.build_formal_replication_preregistration(PROJECT_ROOT)
    design = BenchmarkDesignManifest.model_validate_json(
        (PROJECT_ROOT / DESIGN_PATH).read_bytes()
    )
    profiles = {item.task_id: item for item in design.tasks}
    capability = Counter(
        profiles[slot.task_id].primary_capability for slot in value.slots
    )
    difficulty = Counter(
        profiles[slot.task_id].designed_difficulty for slot in value.slots
    )
    assert set(capability.values()) == {27}
    assert set(difficulty.values()) == {36}


def test_replication_copies_exact_original_slots_retry_and_metrics():
    value = replication.build_formal_replication_preregistration(PROJECT_ROOT)
    original = replication.verify_preregistration(PROJECT_ROOT)
    assert value.task_order == original.task_order
    assert value.base_agent_order == original.base_agent_order
    assert value.agent_order_by_repetition == original.agent_order_by_repetition
    assert value.retry_policy == original.retry_policy
    assert value.metrics_policy == original.metrics_policy
    for new, old in zip(value.slots, original.slots, strict=True):
        assert (
            new.ordinal, new.repetition_index, new.task_id,
            new.task_spec_sha256, new.task_fingerprint_sha256,
            new.resolved_base_commit, new.config_id, new.config_sha256,
        ) == (
            old.ordinal, old.repetition_index, old.task_id,
            old.task_spec_sha256, old.task_fingerprint_sha256,
            old.resolved_base_commit, old.config_id, old.config_sha256,
        )


def test_m16_admission_and_original_outcome_separation_are_explicit():
    value = replication.build_formal_replication_preregistration(PROJECT_ROOT)
    assert value.provider_failure_remediation_commit == \
        replication.M16_REMEDIATION_COMMIT
    assert value.required_provider_failure_remediation_commit == \
        replication.M16_REMEDIATION_COMMIT
    assert value.execution_admission_required_before_replication is True
    assert value.future_execution_harness_commit_status == "not_yet_frozen"
    assert value.structured_codex_http_429_requires_typed_provider_transport_failure
    assert value.structured_codex_http_429_forbids_canonical_run
    assert value.provider_route_must_remain_unchanged
    assert value.patchbench_automatic_retry_forbidden
    assert value.original_runs_are_replication_observations is False
    assert value.original_results_replaced_by_replication is False
    assert value.original_and_replication_primary_metrics_pooled is False
    assert value.replication_primary_metrics_source == "replication_01_only"
    assert value.no_performance_based_stopping is True
    serialized = replication.deterministic_json(value)
    assert "run_id" not in serialized


def test_original_outcomes_do_not_affect_replication_design(monkeypatch):
    baseline = replication.build_formal_replication_preregistration(PROJECT_ROOT)
    original_verify = replication.verify_checked_incident
    changed = original_verify(PROJECT_ROOT).model_copy(update={
        "structured_429_adjudicated_slots": 0,
        "unadjudicated_command_failed_slots": 32,
    })
    monkeypatch.setattr(replication, "verify_checked_incident", lambda root: changed)
    rebuilt = replication.build_formal_replication_preregistration(PROJECT_ROOT)
    assert rebuilt.task_order == baseline.task_order
    assert rebuilt.base_agent_order == baseline.base_agent_order
    assert rebuilt.agent_order_by_repetition == baseline.agent_order_by_repetition
    assert rebuilt.retry_policy == baseline.retry_policy
    assert rebuilt.metrics_policy == baseline.metrics_policy
    assert rebuilt.slots == baseline.slots


@pytest.mark.parametrize(
    "dependency",
    ["M1", "M3", "M8", "M12", "M15 freeze", "M15 analysis", "M17 incident"],
)
def test_checked_dependency_failure_is_rejected(monkeypatch, dependency):
    if dependency in {"M1", "M3", "M8", "M12"}:
        target = "verify_preregistration"
    elif dependency in {"M15 freeze", "M15 analysis"}:
        target = "verify_checked_analysis"
    else:
        target = "verify_checked_incident"
    monkeypatch.setattr(
        replication, target,
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError(dependency)),
    )
    with pytest.raises(replication.FormalReplicationIntegrityError):
        replication.build_formal_replication_preregistration(PROJECT_ROOT)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("formal_results_namespace", "results/v1.3-formal"),
        ("planned_slot_count", 107),
        ("provider_failure_remediation_commit", "0" * 40),
        ("retry_policy", None),
        ("metrics_policy", None),
    ],
)
def test_contract_rejects_identity_policy_and_namespace_drift(field, value):
    baseline = replication.build_formal_replication_preregistration(PROJECT_ROOT)
    data = baseline.model_dump(mode="json")
    data[field] = value
    with pytest.raises(ValidationError):
        V13FormalReplicationPreregistration.model_validate(data)


def test_slot_order_and_identity_drift_are_rejected():
    baseline = replication.build_formal_replication_preregistration(PROJECT_ROOT)
    data = baseline.model_dump(mode="json")
    data["slots"][0], data["slots"][1] = data["slots"][1], data["slots"][0]
    with pytest.raises(ValidationError):
        V13FormalReplicationPreregistration.model_validate(data)
    data = baseline.model_dump(mode="json")
    data["slots"][0]["slot_id"] = "r01-not-replication-specific"
    with pytest.raises(ValidationError):
        V13FormalReplicationPreregistration.model_validate(data)


def test_semantic_hash_is_deterministic_and_model_is_strict():
    value = replication.build_formal_replication_preregistration(PROJECT_ROOT)
    rebuilt = V13FormalReplicationPreregistration.model_validate_json(
        replication.deterministic_json(value)
    )
    assert compute_v13_formal_replication_preregistration_sha256(value) == \
        compute_v13_formal_replication_preregistration_sha256(rebuilt)
    with pytest.raises(ValidationError):
        V13FormalReplicationPreregistration.model_validate(
            value.model_dump(mode="json") | {"unexpected": True}
        )


def test_checked_artifact_has_exact_hashes_when_present():
    if not (PROJECT_ROOT / replication.REPLICATION_PATH).exists():
        pytest.skip("production artifact is generated after synthetic tests")
    value = replication.verify_replication_preregistration(PROJECT_ROOT)
    assert compute_v13_formal_replication_preregistration_sha256(value) == \
        replication.ACCEPTED_REPLICATION_PREREGISTRATION_SHA256
    assert hashlib.sha256(
        (PROJECT_ROOT / replication.REPLICATION_PATH).read_bytes()
    ).hexdigest() == replication.ACCEPTED_REPLICATION_PREREGISTRATION_BYTE_SHA256
