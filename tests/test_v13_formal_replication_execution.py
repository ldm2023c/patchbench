"""Provider-free tests for the admission-gated Replication-01 harness."""

import json
from pathlib import Path

import pytest

from patchbench.agents.base import AgentProviderTransportError, AgentRunStatus
from patchbench.application import v13_formal_execution as engine
from patchbench.application import v13_formal_replication_execution as replication
from patchbench.domain import (
    FormalAttemptStatus,
    FormalFailureCategory,
    FormalSlotStatus,
    FormalStudyStatus,
)
from scripts import v13_formal_replication_execution_admission as admission
from scripts.v13_formal_preregistration import (
    ACCEPTED_PREREGISTRATION_SHA256,
    verify_preregistration,
)
from scripts.v13_formal_replication_preregistration import (
    ACCEPTED_REPLICATION_PREREGISTRATION_SHA256,
    verify_replication_preregistration,
)
from tests.test_v13_formal_execution import (
    FakeSandbox,
    _runner,
    _write_canonical_run,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_HARNESS_COMMIT = "a" * 40


def _admission():
    return admission.build_replication_execution_admission(
        SYNTHETIC_HARNESS_COMMIT, project_root=PROJECT_ROOT
    )


def _admission_kwargs(value=None):
    value = _admission() if value is None else value
    return {
        "admission_verifier": lambda root: value,
        "required_execution_harness_commit": SYNTHETIC_HARNESS_COMMIT,
    }


def _initialize(tmp_path: Path):
    results = tmp_path / "replication"
    ledger = replication.initialize_replication_study(
        project_root=PROJECT_ROOT,
        results_root=results,
        **_admission_kwargs(),
    )
    return results, ledger


def _run_next(results: Path, runner):
    return replication.run_next_replication_attempt(
        project_root=PROJECT_ROOT,
        results_root=results,
        workspace_root=results.parent / "workspaces",
        sandbox=FakeSandbox(),
        runner=runner,
        **_admission_kwargs(),
    )


def test_replication_init_preserves_exact_frozen_identity(tmp_path):
    results, ledger = _initialize(tmp_path)
    preregistration = verify_replication_preregistration(PROJECT_ROOT)
    assert ledger.study_id == "patchbench-v1.3-formal-replication-01"
    assert ledger.formal_preregistration_sha256 == \
        ACCEPTED_REPLICATION_PREREGISTRATION_SHA256
    assert len(ledger.slots) == 108
    assert tuple(slot.slot_id for slot in ledger.slots) == tuple(
        slot.slot_id for slot in preregistration.slots
    )
    assert all(slot.slot_id.startswith("rep01-") for slot in ledger.slots)
    assert results != PROJECT_ROOT / engine.DEFAULT_FORMAL_RESULTS_PATH


def test_original_contract_remains_bound_to_original_preregistration(tmp_path):
    results = tmp_path / "original"
    ledger = engine.initialize_formal_study(
        project_root=PROJECT_ROOT, results_root=results
    )
    original = verify_preregistration(PROJECT_ROOT)
    assert ledger.study_id == original.study_id == "patchbench-v1.3-formal"
    assert ledger.formal_preregistration_sha256 == ACCEPTED_PREREGISTRATION_SHA256
    assert not ledger.slots[0].slot_id.startswith("rep01-")


def test_production_init_refuses_absent_m18b_admission_before_creation(tmp_path):
    results = tmp_path / "replication"
    with pytest.raises(engine.FormalExecutionIntegrityError, match="verification failed"):
        replication.initialize_replication_study(
            project_root=PROJECT_ROOT, results_root=results
        )
    assert not results.exists()


@pytest.mark.parametrize(
    "mutation",
    ["commit", "preregistration", "m16", "agent_manifest", "backend"],
)
def test_init_refuses_wrong_admission_links(tmp_path, mutation):
    value = _admission()
    changes = {
        "commit": {"execution_harness_commit": "b" * 40},
        "preregistration": {"replication_preregistration_sha256": "0" * 64},
        "m16": {"provider_failure_remediation_commit": "0" * 40},
        "agent_manifest": {"agent_manifest_sha256": "0" * 64},
        "backend": {"evaluation_backend": "host"},
    }
    value = value.model_copy(update=changes[mutation])
    results = tmp_path / "replication"
    with pytest.raises(engine.FormalExecutionIntegrityError, match="mismatch"):
        replication.initialize_replication_study(
            project_root=PROJECT_ROOT,
            results_root=results,
            **_admission_kwargs(value),
        )
    assert not results.exists()


def test_original_and_replication_namespaces_cannot_alias():
    with pytest.raises(engine.FormalExecutionIntegrityError, match="aliases"):
        replication.initialize_replication_study(
            project_root=PROJECT_ROOT,
            results_root=PROJECT_ROOT / "results/v1.3-formal",
            **_admission_kwargs(),
        )


def test_strict_one_slot_execution_uses_replication_slot(tmp_path):
    results, _ = _initialize(tmp_path)
    calls = []
    ledger = _run_next(results, _runner(calls=calls))
    assert ledger.slots[0].status is FormalSlotStatus.CANONICAL_OBSERVED
    assert ledger.slots[0].slot_id.startswith("rep01-")
    assert ledger.slots[1].status is FormalSlotStatus.PENDING
    assert len(calls) == 1


def test_provider_429_attempt_one_requires_explicit_retry(tmp_path):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(
        results,
        lambda *a, **k: (_ for _ in ()).throw(
            AgentProviderTransportError("safe")
        ),
    )
    slot = ledger.slots[0]
    attempt = engine._load_attempt(
        results / "slots" / slot.slot_id / "attempt-01"
    )
    assert ledger.status is FormalStudyStatus.RETRY_REQUIRED
    assert slot.status is FormalSlotStatus.RETRY_REQUIRED
    assert attempt.status is FormalAttemptStatus.RETRYABLE_INFRASTRUCTURE_FAILURE
    assert attempt.failure_category is \
        FormalFailureCategory.NETWORK_PROVIDER_TRANSPORT_SAME_ROUTE
    assert list((results / "slots" / slot.slot_id / "attempt-01/artifacts").iterdir()) == []


def test_provider_429_attempt_two_becomes_unresolved_without_attempt_three(tmp_path):
    results, _ = _initialize(tmp_path)
    fail = lambda *a, **k: (_ for _ in ()).throw(
        AgentProviderTransportError("safe")
    )
    ledger = _run_next(results, fail)
    slot_id = ledger.slots[0].slot_id
    ledger = replication.retry_replication_slot(
        project_root=PROJECT_ROOT,
        results_root=results,
        slot_id=slot_id,
        remediation=(
            "network/provider transport availability without changing provider route"
        ),
        sandbox=FakeSandbox(),
        runner=fail,
        **_admission_kwargs(),
    )
    assert ledger.slots[0].status is FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE
    assert ledger.slots[0].attempts == (1, 2)
    assert not (results / "slots" / slot_id / "attempt-03").exists()
    next_ledger = _run_next(results, _runner())
    assert next_ledger.slots[1].status is FormalSlotStatus.CANONICAL_OBSERVED


@pytest.mark.parametrize(
    ("status", "evaluation_passed"),
    [
        (AgentRunStatus.COMMAND_FAILED, False),
        (AgentRunStatus.COMPLETED, False),
        (AgentRunStatus.TIMED_OUT, False),
    ],
)
def test_canonical_agent_outcomes_disable_retry(
    tmp_path, status, evaluation_passed
):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(
        results, _runner(status=status, passed=evaluation_passed)
    )
    slot = ledger.slots[0]
    assert slot.status is FormalSlotStatus.CANONICAL_OBSERVED
    assert slot.canonical_agent_status is status
    assert slot.canonical_evaluation_passed is evaluation_passed


def test_canonical_run_beats_later_provider_exception(tmp_path):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(
        results,
        _runner(raise_after=AgentProviderTransportError("after Run")),
    )
    assert ledger.slots[0].status is FormalSlotStatus.CANONICAL_OBSERVED


def _start_interrupted_attempt(results: Path):
    preregistration = verify_replication_preregistration(PROJECT_ROOT)
    ledger = engine._load_study(
        results, preregistration, replication.REPLICATION_FORMAL_EXECUTION_CONTRACT
    )
    return engine._create_attempt(
        results,
        ledger,
        0,
        attempt_index=1,
        remediation=None,
        contract=replication.REPLICATION_FORMAL_EXECUTION_CONTRACT,
    )


def test_restart_reconciles_trustworthy_run_without_runner_call(tmp_path):
    results, _ = _initialize(tmp_path)
    _, _, attempt_dir = _start_interrupted_attempt(results)
    slot = verify_replication_preregistration(PROJECT_ROOT).slots[0]
    _write_canonical_run(
        attempt_dir / "artifacts",
        slot.config_id,
        PROJECT_ROOT / "tasks/reliability/env_config/task.yaml",
    )
    calls = []
    ledger = _run_next(results, _runner(calls=calls))
    assert ledger.slots[0].status is FormalSlotStatus.CANONICAL_OBSERVED
    assert calls == []


def test_restart_partial_evidence_blocks(tmp_path):
    results, _ = _initialize(tmp_path)
    _, _, attempt_dir = _start_interrupted_attempt(results)
    partial = attempt_dir / "artifacts/partial"
    partial.mkdir()
    (partial / "metadata.json").write_text("{}", encoding="utf-8")
    ledger = _run_next(results, _runner())
    attempt = engine._load_attempt(
        results / "slots" / ledger.slots[0].slot_id / "attempt-01"
    )
    assert ledger.status is FormalStudyStatus.BLOCKED
    assert attempt.failure_category is FormalFailureCategory.EVIDENCE_INTEGRITY


def test_attempt_three_and_wrong_remediation_are_rejected(tmp_path):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(
        results,
        lambda *a, **k: (_ for _ in ()).throw(
            AgentProviderTransportError("safe")
        ),
    )
    slot_id = ledger.slots[0].slot_id
    with pytest.raises(engine.FormalExecutionStateError, match="allow-listed"):
        replication.retry_replication_slot(
            project_root=PROJECT_ROOT,
            results_root=results,
            slot_id=slot_id,
            remediation="change provider",
            sandbox=FakeSandbox(),
            runner=_runner(),
            **_admission_kwargs(),
        )
    (results / "slots" / slot_id / "attempt-03").mkdir()
    with pytest.raises(engine.FormalExecutionIntegrityError):
        replication.check_replication_study(
            project_root=PROJECT_ROOT, results_root=results
        )


def test_ledger_preregistration_identity_drift_is_rejected(tmp_path):
    results, _ = _initialize(tmp_path)
    path = results / "study.json"
    data = json.loads(path.read_text())
    data["formal_preregistration_sha256"] = ACCEPTED_PREREGISTRATION_SHA256
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(engine.FormalExecutionIntegrityError, match="differs"):
        replication.check_replication_study(
            project_root=PROJECT_ROOT, results_root=results
        )


def test_m18a_defines_no_production_admission_artifact():
    assert admission.ACCEPTED_REPLICATION_EXECUTION_ADMISSION_SHA256 is None
    assert admission.ACCEPTED_REPLICATION_EXECUTION_ADMISSION_BYTE_SHA256 is None
    assert replication.REQUIRED_EXECUTION_HARNESS_COMMIT is None
    assert not (PROJECT_ROOT / admission.ADMISSION_PATH).exists()
