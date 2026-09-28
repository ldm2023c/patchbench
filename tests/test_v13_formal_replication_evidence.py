"""Provider-free checks for the final Replication-01 freeze and analysis."""

import hashlib
from pathlib import Path

import pytest

from patchbench.agents.base import AgentRunStatus
from patchbench.domain.formal_evidence import (
    compute_v13_formal_attempt_sha256,
    compute_v13_formal_replication_evidence_freeze_sha256,
)
from patchbench.domain.formal_execution import (
    FormalAttemptStatus,
    FormalFailureCategory,
    FormalSlotStatus,
    FormalStudyStatus,
)
from scripts import v13_formal_analysis as original_analysis
from scripts import v13_formal_evidence as original_evidence
from scripts import v13_formal_replication_analysis as analysis
from scripts import v13_formal_replication_evidence as evidence
from scripts.v13_formal_replication_preregistration import (
    ACCEPTED_REPLICATION_PREREGISTRATION_SHA256,
    verify_replication_preregistration,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "results/v1.3-formal-replication-01"
requires_replication_runtime = pytest.mark.skipif(
    not SOURCE.is_dir(),
    reason="ignored Replication-01 runtime evidence is unavailable",
)


def test_checked_freeze_binds_completed_replication():
    freeze = evidence.verify_checked_replication_freeze(PROJECT_ROOT)
    preregistration = verify_replication_preregistration(PROJECT_ROOT)
    assert freeze.source_study_status == "completed"
    assert (
        freeze.planned_slot_count,
        freeze.terminal_slot_count,
        freeze.canonical_slot_count,
        freeze.unresolved_infrastructure_slot_count,
        freeze.blocked_slot_count,
    ) == (108, 108, 107, 1, 0)
    assert freeze.replication_preregistration_sha256 == \
        ACCEPTED_REPLICATION_PREREGISTRATION_SHA256
    assert tuple(
        (slot.ordinal, slot.slot_id, slot.task_id, slot.config_id)
        for slot in freeze.slots
    ) == tuple(
        (slot.ordinal, slot.slot_id, slot.task_id, slot.config_id)
        for slot in preregistration.slots
    )
    assert len(freeze.slots) == 108

    unresolved = tuple(
        slot for slot in freeze.slots
        if slot.source_slot_status is FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE
    )
    assert len(unresolved) == 1
    assert unresolved[0].slot_id == \
        "rep01-r01-env_config-codex-gpt-5.5-relay"
    assert unresolved[0].canonical_run is None
    assert unresolved[0].canonical_attempt_index is None
    canonical = tuple(
        slot for slot in freeze.slots
        if slot.source_slot_status is FormalSlotStatus.CANONICAL_OBSERVED
    )
    assert len(canonical) == 107
    assert all(slot.canonical_run is not None for slot in canonical)


@requires_replication_runtime
def test_checked_freeze_binds_sample_raw_evidence():
    freeze = evidence.verify_checked_replication_freeze(PROJECT_ROOT)
    assert not tuple(SOURCE.glob("slots/*/attempt-03"))
    canonical = tuple(
        slot for slot in freeze.slots
        if slot.source_slot_status is FormalSlotStatus.CANONICAL_OBSERVED
    )
    sample = canonical[0]
    attempt_index = sample.canonical_attempt_index
    assert attempt_index is not None
    attempt_dir = SOURCE / "slots" / sample.slot_id / f"attempt-{attempt_index:02d}"
    attempt, raw = original_evidence._load_attempt(attempt_dir)
    frozen_attempt = sample.attempts[attempt_index - 1]
    assert frozen_attempt.attempt_json_sha256 == hashlib.sha256(raw).hexdigest()
    assert frozen_attempt.attempt_semantic_sha256 == \
        compute_v13_formal_attempt_sha256(attempt)
    run = sample.canonical_run
    assert run is not None
    run_root = attempt_dir / "artifacts" / run.run_id
    for field, filename in original_evidence._RAW_RUN_FILES.items():
        assert getattr(run, field) == hashlib.sha256(
            (run_root / filename).read_bytes()
        ).hexdigest()


def test_retry_history_and_agent_identity_are_preserved():
    freeze = evidence.verify_checked_replication_freeze(PROJECT_ROOT)
    retried = tuple(slot for slot in freeze.slots if len(slot.attempts) == 2)
    assert tuple(slot.slot_id for slot in retried) == (
        "rep01-r01-env_config-codex-gpt-5.5-relay",
        "rep01-r01-request_signing-codex-gpt-5.5-relay",
    )
    for slot in retried:
        assert slot.attempts[0].status is \
            FormalAttemptStatus.RETRYABLE_INFRASTRUCTURE_FAILURE
        assert slot.attempts[0].failure_category is \
            FormalFailureCategory.NETWORK_PROVIDER_TRANSPORT_SAME_ROUTE
        assert slot.attempts[1].remediation == \
            "network/provider transport availability without changing provider route"
    assert retried[0].attempts[1].status is \
        FormalAttemptStatus.UNRESOLVED_INFRASTRUCTURE
    assert retried[1].attempts[1].status is FormalAttemptStatus.CANONICAL_OBSERVED
    assert all(
        slot.canonical_run is None
        or slot.canonical_run.identity_binding.config_id == slot.config_id
        for slot in freeze.slots
    )


def test_replication_and_original_namespaces_cannot_alias():
    with pytest.raises(evidence.FormalReplicationEvidenceIntegrityError):
        evidence.build_formal_replication_evidence_freeze(
            PROJECT_ROOT / "results/v1.3-formal", project_root=PROJECT_ROOT
        )


@requires_replication_runtime
def test_non_completed_replication_fails_closed(monkeypatch):
    ledger = evidence.check_formal_study(
        project_root=PROJECT_ROOT,
        results_root=SOURCE,
        contract=evidence.REPLICATION_FORMAL_EXECUTION_CONTRACT,
    )
    monkeypatch.setattr(
        evidence,
        "check_formal_study",
        lambda **_kwargs: ledger.model_copy(update={"status": FormalStudyStatus.RUNNING}),
    )
    with pytest.raises(evidence.FormalReplicationEvidenceIntegrityError):
        evidence.build_formal_replication_evidence_freeze(
            SOURCE, project_root=PROJECT_ROOT
        )


def test_checked_analysis_has_exact_formulas_denominators_and_retry_reporting():
    result = analysis.verify_checked_replication_analysis(PROJECT_ROOT)
    assert (
        result.overall.end_to_end_reliability.numerator,
        result.overall.end_to_end_reliability.denominator,
        result.overall.completed_semantic_repair.numerator,
        result.overall.completed_semantic_repair.denominator,
        result.overall.operational_completion.numerator,
        result.overall.operational_completion.denominator,
    ) == (107, 108, 107, 107, 107, 108)
    assert [row.end_to_end_reliability.denominator
            for row in result.by_agent_configuration] == [36] * 3
    assert [row.end_to_end_reliability.denominator
            for row in result.by_primary_capability] == [27] * 4
    assert [row.end_to_end_reliability.denominator
            for row in result.by_designed_difficulty] == [36] * 3
    assert [row.end_to_end_reliability.denominator
            for row in result.by_task] == [9] * 12
    assert result.retry_reporting.slots_resolving_on_retry == (
        "rep01-r01-request_signing-codex-gpt-5.5-relay",
    )
    assert result.retry_reporting.slots_unresolved_after_retry == (
        "rep01-r01-env_config-codex-gpt-5.5-relay",
    )
    assert result.formal_replication_evidence_freeze_sha256 == \
        evidence.ACCEPTED_REPLICATION_FORMAL_FREEZE_SHA256


def test_analysis_is_replication_only_and_all_canonical_runs_completed_and_passed():
    freeze = evidence.verify_checked_replication_freeze(PROJECT_ROOT)
    rebuilt = analysis.build_formal_replication_analysis(
        project_root=PROJECT_ROOT, freeze=freeze
    )
    assert rebuilt == analysis.verify_checked_replication_analysis(PROJECT_ROOT)
    canonical = tuple(slot.canonical_run for slot in freeze.slots
                      if slot.canonical_run is not None)
    assert len(canonical) == 107
    assert all(run.agent_status is AgentRunStatus.COMPLETED for run in canonical)
    assert all(run.evaluation_passed for run in canonical)
    assert compute_v13_formal_replication_evidence_freeze_sha256(freeze) == \
        analysis.ACCEPTED_REPLICATION_FORMAL_FREEZE_SHA256


def test_original_m15_checked_artifacts_remain_accepted_and_byte_exact():
    original_evidence.verify_checked_freeze(PROJECT_ROOT)
    original_analysis.verify_checked_analysis(PROJECT_ROOT)
    assert hashlib.sha256(
        (PROJECT_ROOT / original_evidence.FREEZE_PATH).read_bytes()
    ).hexdigest() == original_evidence.ACCEPTED_FORMAL_FREEZE_BYTE_SHA256
    assert hashlib.sha256(
        (PROJECT_ROOT / original_analysis.ANALYSIS_PATH).read_bytes()
    ).hexdigest() == original_analysis.ACCEPTED_FORMAL_ANALYSIS_BYTE_SHA256


def test_final_report_metric_counts_are_derived_consistently():
    result = analysis.verify_checked_replication_analysis(PROJECT_ROOT)
    report = (
        PROJECT_ROOT
        / "evidence/v1.3/formal-replication-01/FINAL_REPORT.md"
    ).read_text()
    sections = (
        (result.overall,),
        result.by_agent_configuration,
        result.by_primary_capability,
        result.by_designed_difficulty,
        result.by_task,
    )
    for rows in sections:
        for row in rows:
            for metric in (
                row.end_to_end_reliability,
                row.completed_semantic_repair,
                row.operational_completion,
            ):
                assert f"{metric.numerator}/{metric.denominator}" in report
