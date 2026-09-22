"""M12 formal-study preregistration tests."""

from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from patchbench.domain.benchmark import BenchmarkDesignManifest
from patchbench.domain.formal_study import (
    V13FormalPreregistration,
    compute_v13_formal_preregistration_sha256,
)
from scripts import v13_formal_preregistration as formal


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_checked_preregistration_rebuilds_and_has_anchored_hashes():
    checked = formal.verify_preregistration()
    assert checked == formal.build_formal_preregistration()
    assert compute_v13_formal_preregistration_sha256(checked) == (
        formal.ACCEPTED_PREREGISTRATION_SHA256
    )
    assert formal._sha256_file(PROJECT_ROOT / formal.PREREGISTRATION_PATH) == (
        formal.ACCEPTED_PREREGISTRATION_BYTE_SHA256
    )


def test_exact_frozen_links_and_shape():
    value = formal.load_preregistration()
    assert value.design_sha256 == formal.ACCEPTED_DESIGN_SHA256
    assert value.candidate_sha256 == formal.ACCEPTED_CANDIDATE_SHA256
    assert value.agent_manifest_sha256 == formal.ACCEPTED_AGENT_MANIFEST_SHA256
    assert value.calibration_protocol_sha256 == formal.ACCEPTED_CALIBRATION_PROTOCOL_SHA256
    assert value.calibration_evidence_freeze_sha256 == formal.ACCEPTED_FREEZE_SHA256
    assert value.accepted_calibration_batch_id == "calibration-001"
    assert value.evaluation_backend == "docker"
    assert value.repetitions_per_cell == 3
    assert value.planned_slot_count == len(value.slots) == 108
    assert len(value.task_order) == 12 and len(value.base_agent_order) == 3
    assert "example_bug" not in value.task_order
    assert all("claude-code" not in item for item in value.base_agent_order)


def test_exact_execution_order_and_latin_rotation():
    value = formal.load_preregistration()
    base = value.base_agent_order
    assert value.agent_order_by_repetition == (
        base,
        (base[1], base[2], base[0]),
        (base[2], base[0], base[1]),
    )
    assert tuple(slot.ordinal for slot in value.slots) == tuple(range(1, 109))
    assert len({slot.slot_id for slot in value.slots}) == 108
    for repetition in range(1, 4):
        slots = [slot for slot in value.slots if slot.repetition_index == repetition]
        assert [slots[index].task_id for index in range(0, 36, 3)] == list(value.task_order)
        for index in range(0, 36, 3):
            assert tuple(slot.config_id for slot in slots[index:index + 3]) == (
                value.agent_order_by_repetition[repetition - 1]
            )


def test_every_task_config_cell_has_three_repetitions_and_manifest_identities():
    value = formal.load_preregistration()
    candidate = formal._load(
        PROJECT_ROOT / formal.CANDIDATE_PATH, formal.BenchmarkCandidateManifest, "candidate"
    )
    manifest = formal._load(
        PROJECT_ROOT / formal.AGENT_MANIFEST_PATH, formal.AgentConfigurationManifest, "manifest"
    )
    tasks = {task.task_id: task for task in candidate.tasks}
    configs = {
        config.config_id: formal.compute_agent_configuration_sha256(config)
        for config in manifest.configurations
    }
    counts = Counter((slot.task_id, slot.config_id) for slot in value.slots)
    assert set(counts.values()) == {3}
    for slot in value.slots:
        task = tasks[slot.task_id]
        assert (slot.task_spec_sha256, slot.task_fingerprint_sha256,
                slot.resolved_base_commit) == (
            task.task_spec_sha256, task.task_fingerprint_sha256,
            task.resolved_base_commit,
        )
        assert slot.config_sha256 == configs[slot.config_id]


def test_denominator_sanity_is_derived_from_m1_m3_plan():
    value = formal.load_preregistration()
    design = formal._load(
        PROJECT_ROOT / formal.DESIGN_PATH, BenchmarkDesignManifest, "design"
    )
    profile = {task.task_id: task for task in design.tasks}
    assert len(value.slots) == 108
    assert set(Counter(slot.config_id for slot in value.slots).values()) == {36}
    assert set(Counter(slot.task_id for slot in value.slots).values()) == {9}
    assert set(Counter(profile[slot.task_id].primary_capability for slot in value.slots).values()) == {27}
    assert set(Counter(profile[slot.task_id].designed_difficulty for slot in value.slots).values()) == {36}


def test_retry_policy_is_one_retry_only_before_canonical_run():
    policy = formal.load_preregistration().retry_policy
    assert policy.max_attempts_per_slot == 2
    assert policy.max_retries_per_slot == 1
    assert policy.retry_requires_no_canonical_run_record is True
    assert policy.canonical_run_disables_retry is True
    assert policy.canonical_agent_statuses_not_retryable == (
        "completed", "command_failed", "timed_out"
    )
    assert policy.evaluator_failure_not_retryable is True
    assert policy.evaluation_infrastructure_error_not_retryable is True
    assert policy.empty_patch_not_retryable is True
    assert policy.incorrect_semantic_repair_not_retryable is True
    assert policy.frozen_task_integrity_failure_not_retryable is True
    assert policy.retry_preserves_slot_identity is True
    assert policy.retry_does_not_add_planned_slot is True
    assert policy.no_fallback_agent is True
    assert policy.no_substitute_task is True
    assert policy.no_replacement_slot is True
    assert policy.exhausted_infrastructure_slot_remains_in_denominator is True


def test_metric_and_anti_selection_policy_is_exact():
    value = formal.load_preregistration()
    metrics = value.metrics_policy
    assert metrics.end_to_end_success_condition == "canonical_completed_and_evaluator_pass"
    assert metrics.end_to_end_denominator == "all_planned_slots_in_stratum"
    assert metrics.unresolved_infrastructure_is_end_to_end_failure is True
    assert metrics.completed_semantic_repair_numerator == "canonical_completed_and_evaluator_pass"
    assert metrics.completed_semantic_repair_denominator == "canonical_completed_slots"
    assert metrics.completed_semantic_repair_is_conditional is True
    assert metrics.operational_completion_numerator == "canonical_completed_slots"
    assert metrics.operational_completion_denominator == "all_planned_slots_in_stratum"
    assert metrics.operational_completion_is_descriptive is True
    assert metrics.m1_m3_design_labels_authoritative is True
    assert value.calibration_outcome_must_not_influence_formal_design is True
    assert value.calibration_outcome_excluded_from == (
        "task_selection", "agent_selection", "model_selection", "timeout",
        "endpoint_or_relay", "task_order", "repetition_count", "retry_policy",
        "metric_definitions",
    )
    assert all((
        metrics.no_weighted_composite_agent_score,
        metrics.no_post_hoc_best_agent_rule,
        metrics.no_outcome_based_task_removal,
        metrics.no_outcome_based_agent_removal,
        metrics.no_difficulty_relabeling,
        metrics.no_failure_denominator_exclusion,
        metrics.no_cherry_picked_repetitions,
        metrics.no_replacement_runs_beyond_retry,
        metrics.no_performance_based_stopping,
    ))


def test_calibration_evaluator_outcomes_do_not_change_plan(monkeypatch):
    original = formal.verify_checked_freeze
    freeze = original()
    changed = freeze.model_copy(update={
        "slots": tuple(slot.model_copy(update={"evaluation_passed": not slot.evaluation_passed})
                       for slot in freeze.slots)
    })
    monkeypatch.setattr(formal, "verify_checked_freeze", lambda root: changed)
    rebuilt = formal.build_formal_preregistration()
    baseline = formal.load_preregistration()
    assert rebuilt.task_order == baseline.task_order
    assert rebuilt.base_agent_order == baseline.base_agent_order
    assert rebuilt.agent_order_by_repetition == baseline.agent_order_by_repetition
    assert rebuilt.retry_policy == baseline.retry_policy
    assert rebuilt.metrics_policy == baseline.metrics_policy
    assert rebuilt.slots == baseline.slots


def test_meaningful_mutation_changes_semantic_sha_and_extra_fields_reject():
    value = formal.load_preregistration()
    changed = value.model_copy(update={"formal_results_namespace": "results/other"})
    assert compute_v13_formal_preregistration_sha256(changed) != (
        compute_v13_formal_preregistration_sha256(value)
    )
    with pytest.raises(ValidationError):
        V13FormalPreregistration.model_validate(
            value.model_dump(mode="json") | {"extra": True}
        )


@pytest.mark.parametrize(
    "field",
    ["design_sha256", "candidate_sha256", "agent_manifest_sha256",
     "calibration_protocol_sha256", "calibration_evidence_freeze_sha256"],
)
def test_frozen_link_mutation_differs_from_rebuilt_contract(field):
    checked = formal.load_preregistration()
    changed = checked.model_copy(update={field: "0" * 64})
    assert changed != formal.build_formal_preregistration()
