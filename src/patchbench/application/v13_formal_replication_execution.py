"""Admission-gated execution facade for V1.3 Replication-01."""

from collections.abc import Callable
from pathlib import Path

from patchbench.application.v13_agent_execution import (
    resolve_v13_agent_config,
    run_v13_agent_experiment,
)
from patchbench.application.v13_formal_execution import (
    FormalExecutionContract,
    FormalExecutionIntegrityError,
    FormalStudyStatusSummary,
    Resolver,
    Runner,
    check_formal_study,
    formal_study_status,
    initialize_formal_study,
    retry_formal_slot,
    run_next_formal_attempt,
)
from patchbench.domain.formal_execution import V13FormalStudyLedger
from patchbench.domain.formal_replication_execution import (
    V13FormalReplicationExecutionAdmission,
)
from patchbench.sandbox.base import Sandbox
from scripts.v13_formal_incident import M16_REMEDIATION_COMMIT
from scripts.v13_formal_preregistration import ACCEPTED_AGENT_MANIFEST_SHA256
from scripts.v13_formal_replication_execution_admission import (
    verify_checked_replication_execution_admission,
)
from scripts.v13_formal_replication_preregistration import (
    ACCEPTED_REPLICATION_PREREGISTRATION_SHA256,
    verify_replication_preregistration,
)


DEFAULT_REPLICATION_RESULTS_PATH = Path("results/v1.3-formal-replication-01")
ORIGINAL_FORMAL_RESULTS_PATH = Path("results/v1.3-formal")

# Tests may pin an expected commit; production trusts only the checked M18B artifact.
REQUIRED_EXECUTION_HARNESS_COMMIT: str | None = None

AdmissionVerifier = Callable[[Path], V13FormalReplicationExecutionAdmission]


def _verify_replication_preregistration(project_root: Path):
    return verify_replication_preregistration(project_root)


REPLICATION_FORMAL_EXECUTION_CONTRACT = FormalExecutionContract(
    study_id="patchbench-v1.3-formal-replication-01",
    accepted_preregistration_sha256=(
        ACCEPTED_REPLICATION_PREREGISTRATION_SHA256
    ),
    default_results_path=DEFAULT_REPLICATION_RESULTS_PATH,
    preregistration_verifier=_verify_replication_preregistration,
)


def _default_admission_verifier(
    project_root: Path,
) -> V13FormalReplicationExecutionAdmission:
    return verify_checked_replication_execution_admission(project_root)


def _require_admission(
    project_root: Path,
    *,
    admission_verifier: AdmissionVerifier,
    required_execution_harness_commit: str | None,
) -> V13FormalReplicationExecutionAdmission:
    try:
        admission = admission_verifier(project_root)
    except Exception as error:
        raise FormalExecutionIntegrityError(
            "replication execution admission verification failed"
        ) from error
    if (
        admission.replication_id != "patchbench-v1.3-replication-01"
        or admission.study_id != REPLICATION_FORMAL_EXECUTION_CONTRACT.study_id
        or admission.results_namespace
        != DEFAULT_REPLICATION_RESULTS_PATH.as_posix()
        or admission.replication_preregistration_sha256
        != ACCEPTED_REPLICATION_PREREGISTRATION_SHA256
        or admission.provider_failure_remediation_commit
        != M16_REMEDIATION_COMMIT
        or (
            required_execution_harness_commit is not None
            and admission.execution_harness_commit
            != required_execution_harness_commit
        )
        or admission.agent_manifest_sha256 != ACCEPTED_AGENT_MANIFEST_SHA256
        or admission.evaluation_backend != "docker"
    ):
        raise FormalExecutionIntegrityError(
            "replication execution admission frozen-link mismatch"
        )
    return admission


def _reject_original_namespace(project_root: Path, results_root: Path | None) -> None:
    selected = (
        project_root / DEFAULT_REPLICATION_RESULTS_PATH
        if results_root is None else Path(results_root)
    ).resolve()
    if selected == (project_root / ORIGINAL_FORMAL_RESULTS_PATH).resolve():
        raise FormalExecutionIntegrityError(
            "replication results namespace aliases original formal results"
        )


def initialize_replication_study(
    *,
    project_root: Path,
    results_root: Path | None = None,
    admission_verifier: AdmissionVerifier = _default_admission_verifier,
    required_execution_harness_commit: str | None = REQUIRED_EXECUTION_HARNESS_COMMIT,
) -> V13FormalStudyLedger:
    root = Path(project_root).resolve()
    _reject_original_namespace(root, results_root)
    _require_admission(
        root,
        admission_verifier=admission_verifier,
        required_execution_harness_commit=required_execution_harness_commit,
    )
    return initialize_formal_study(
        project_root=root,
        results_root=results_root,
        contract=REPLICATION_FORMAL_EXECUTION_CONTRACT,
    )


def run_next_replication_attempt(
    *,
    project_root: Path,
    sandbox: Sandbox,
    results_root: Path | None = None,
    workspace_root: Path | None = None,
    resolver: Resolver = resolve_v13_agent_config,
    runner: Runner = run_v13_agent_experiment,
    admission_verifier: AdmissionVerifier = _default_admission_verifier,
    required_execution_harness_commit: str | None = REQUIRED_EXECUTION_HARNESS_COMMIT,
) -> V13FormalStudyLedger:
    root = Path(project_root).resolve()
    _reject_original_namespace(root, results_root)
    _require_admission(
        root,
        admission_verifier=admission_verifier,
        required_execution_harness_commit=required_execution_harness_commit,
    )
    return run_next_formal_attempt(
        project_root=root, sandbox=sandbox, results_root=results_root,
        workspace_root=workspace_root, resolver=resolver, runner=runner,
        contract=REPLICATION_FORMAL_EXECUTION_CONTRACT,
    )


def retry_replication_slot(
    *,
    project_root: Path,
    slot_id: str,
    remediation: str,
    sandbox: Sandbox,
    results_root: Path | None = None,
    workspace_root: Path | None = None,
    resolver: Resolver = resolve_v13_agent_config,
    runner: Runner = run_v13_agent_experiment,
    admission_verifier: AdmissionVerifier = _default_admission_verifier,
    required_execution_harness_commit: str | None = REQUIRED_EXECUTION_HARNESS_COMMIT,
) -> V13FormalStudyLedger:
    root = Path(project_root).resolve()
    _reject_original_namespace(root, results_root)
    _require_admission(
        root,
        admission_verifier=admission_verifier,
        required_execution_harness_commit=required_execution_harness_commit,
    )
    return retry_formal_slot(
        project_root=root, slot_id=slot_id, remediation=remediation,
        sandbox=sandbox, results_root=results_root, workspace_root=workspace_root,
        resolver=resolver, runner=runner,
        contract=REPLICATION_FORMAL_EXECUTION_CONTRACT,
    )


def check_replication_study(
    *,
    project_root: Path,
    results_root: Path | None = None,
    resolver: Resolver = resolve_v13_agent_config,
) -> V13FormalStudyLedger:
    root = Path(project_root).resolve()
    _reject_original_namespace(root, results_root)
    return check_formal_study(
        project_root=root, results_root=results_root, resolver=resolver,
        contract=REPLICATION_FORMAL_EXECUTION_CONTRACT,
    )


def replication_study_status(
    *, project_root: Path, results_root: Path | None = None,
) -> FormalStudyStatusSummary:
    root = Path(project_root).resolve()
    _reject_original_namespace(root, results_root)
    return formal_study_status(
        project_root=root, results_root=results_root,
        contract=REPLICATION_FORMAL_EXECUTION_CONTRACT,
    )
