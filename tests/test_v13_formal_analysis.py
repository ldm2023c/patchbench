"""Provider-free tests for preregistered V1.3 formal metrics."""

import hashlib
from pathlib import Path

import pytest

from patchbench.agents.base import AgentRunStatus
from patchbench.domain import FormalAttemptStatus, FormalFailureCategory, FormalSlotStatus
from patchbench.domain.formal_analysis import (
    V13FormalMetric, compute_v13_formal_analysis_sha256,
)
from patchbench.domain.formal_evidence import V13FormalEvidenceFreeze
from scripts import v13_formal_analysis as analysis
from scripts import v13_formal_evidence as evidence
from scripts.v13_formal_preregistration import verify_preregistration


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def mixed_freeze():
    data = evidence.load_checked_freeze(PROJECT_ROOT).model_dump(mode="json")
    for slot in data["slots"]:
        slot["source_slot_status"] = FormalSlotStatus.CANONICAL_OBSERVED.value
        slot["canonical_attempt_index"] = 1
        slot["canonical_run"]["agent_status"] = AgentRunStatus.COMPLETED.value
        slot["canonical_run"]["evaluation_passed"] = True
        slot["attempts"] = [slot["attempts"][-1]]
        slot["attempts"][0].update({
            "attempt_index": 1,
            "status": FormalAttemptStatus.CANONICAL_OBSERVED.value,
            "remediation": None,
            "failure_category": None,
            "canonical_run_id": slot["canonical_run"]["run_id"],
            "agent_status": AgentRunStatus.COMPLETED.value,
            "evaluation_passed": True,
        })
    for index, (status, passed) in enumerate((
        (AgentRunStatus.COMPLETED, True),
        (AgentRunStatus.COMPLETED, False),
        (AgentRunStatus.COMMAND_FAILED, False),
        (AgentRunStatus.TIMED_OUT, False),
    )):
        slot = data["slots"][index]
        slot["canonical_run"]["agent_status"] = status.value
        slot["canonical_run"]["evaluation_passed"] = passed
        slot["attempts"][0]["agent_status"] = status.value
        slot["attempts"][0]["evaluation_passed"] = passed

    resolved = data["slots"][4]
    first = dict(resolved["attempts"][0])
    first.update({
        "attempt_index": 1,
        "status": FormalAttemptStatus.RETRYABLE_INFRASTRUCTURE_FAILURE.value,
        "remediation": None,
        "failure_category": FormalFailureCategory.AGENT_SETUP.value,
        "canonical_run_id": None, "agent_status": None, "evaluation_passed": None,
    })
    second = dict(resolved["attempts"][0])
    second.update({"attempt_index": 2, "remediation": "Docker availability"})
    resolved["attempts"] = [first, second]
    resolved["canonical_attempt_index"] = 2

    unresolved = data["slots"][5]
    first = dict(unresolved["attempts"][0])
    first.update({
        "attempt_index": 1,
        "status": FormalAttemptStatus.RETRYABLE_INFRASTRUCTURE_FAILURE.value,
        "remediation": None,
        "failure_category": FormalFailureCategory.DOCKER_INFRASTRUCTURE.value,
        "canonical_run_id": None, "agent_status": None, "evaluation_passed": None,
    })
    second = dict(first)
    second.update({
        "attempt_index": 2,
        "status": FormalAttemptStatus.UNRESOLVED_INFRASTRUCTURE.value,
        "remediation": "Docker availability",
    })
    unresolved.update({
        "source_slot_status": FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE.value,
        "attempts": [first, second],
        "canonical_attempt_index": None,
        "canonical_run": None,
    })
    data["canonical_slot_count"] = 107
    data["unresolved_infrastructure_slot_count"] = 1
    return V13FormalEvidenceFreeze.model_validate(data)


def test_exact_preregistered_metric_formulas_and_retry_reporting(mixed_freeze):
    result = analysis.build_formal_analysis(
        project_root=PROJECT_ROOT, freeze=mixed_freeze
    )
    assert (result.overall.end_to_end_reliability.numerator,
            result.overall.end_to_end_reliability.denominator) == (104, 108)
    assert (result.overall.completed_semantic_repair.numerator,
            result.overall.completed_semantic_repair.denominator) == (104, 105)
    assert (result.overall.operational_completion.numerator,
            result.overall.operational_completion.denominator) == (105, 108)
    retry = result.retry_reporting
    assert retry.slots_requiring_retry == (
        mixed_freeze.slots[4].slot_id, mixed_freeze.slots[5].slot_id,
    )
    assert [(item.failure_category, item.count) for item in retry.retry_reasons] == [
        (FormalFailureCategory.AGENT_SETUP, 1),
        (FormalFailureCategory.DOCKER_INFRASTRUCTURE, 1),
    ]
    assert retry.slots_resolving_on_retry == (mixed_freeze.slots[4].slot_id,)
    assert retry.slots_unresolved_after_retry == (mixed_freeze.slots[5].slot_id,)


def test_strata_cardinalities_denominators_and_frozen_order(mixed_freeze):
    result = analysis.build_formal_analysis(
        project_root=PROJECT_ROOT, freeze=mixed_freeze
    )
    prereg = verify_preregistration(PROJECT_ROOT)
    assert [row.value for row in result.by_agent_configuration] == list(
        prereg.base_agent_order
    )
    assert [row.end_to_end_reliability.denominator
            for row in result.by_agent_configuration] == [36] * 3
    assert [row.end_to_end_reliability.denominator
            for row in result.by_primary_capability] == [27] * 4
    assert [row.value for row in result.by_designed_difficulty] == [
        "easy", "medium", "hard",
    ]
    assert [row.end_to_end_reliability.denominator
            for row in result.by_designed_difficulty] == [36] * 3
    assert [row.value for row in result.by_task] == list(prereg.task_order)
    assert [row.end_to_end_reliability.denominator for row in result.by_task] == [9] * 12


def test_zero_conditional_denominator_uses_null_rate():
    metric = V13FormalMetric(numerator=0, denominator=0, rate=None)
    assert metric.rate is None
    with pytest.raises(Exception):
        V13FormalMetric(numerator=0, denominator=0, rate=0.0)


def test_analysis_hash_is_deterministic(mixed_freeze):
    first = analysis.build_formal_analysis(project_root=PROJECT_ROOT, freeze=mixed_freeze)
    second = type(first).model_validate_json(analysis.deterministic_json(first))
    assert compute_v13_formal_analysis_sha256(first) == \
        compute_v13_formal_analysis_sha256(second)


def test_analysis_builder_never_reads_live_results(mixed_freeze, monkeypatch):
    original = Path.read_bytes
    def guarded(path):
        assert "results/v1.3-formal" not in path.as_posix()
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", guarded)
    analysis.build_formal_analysis(project_root=PROJECT_ROOT, freeze=mixed_freeze)


def test_checked_analysis_rebuilds_and_has_exact_byte_identity():
    checked = analysis.verify_checked_analysis(PROJECT_ROOT)
    assert checked == analysis.build_formal_analysis(project_root=PROJECT_ROOT)
    assert hashlib.sha256((PROJECT_ROOT / analysis.ANALYSIS_PATH).read_bytes()).hexdigest() == \
        analysis.ACCEPTED_FORMAL_ANALYSIS_BYTE_SHA256
