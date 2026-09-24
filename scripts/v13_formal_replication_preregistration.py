"""Build and verify the PatchBench V1.3 Replication-01 preregistration."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from patchbench.domain.formal_replication import (
    V13FormalReplicationPreregistration,
    V13FormalReplicationSlot,
    compute_v13_formal_replication_preregistration_sha256,
)
from scripts.v13_formal_analysis import (
    ACCEPTED_FORMAL_ANALYSIS_SHA256,
    verify_checked_analysis,
)
from scripts.v13_formal_evidence import ACCEPTED_FORMAL_FREEZE_SHA256
from scripts.v13_formal_incident import (
    ACCEPTED_FORMAL_INCIDENT_SHA256,
    M16_REMEDIATION_COMMIT,
    verify_checked_incident,
)
from scripts.v13_formal_preregistration import (
    ACCEPTED_AGENT_MANIFEST_SHA256,
    ACCEPTED_CANDIDATE_SHA256,
    ACCEPTED_DESIGN_SHA256,
    ACCEPTED_PREREGISTRATION_SHA256,
    verify_preregistration,
)


REPLICATION_PATH = Path(
    "tasks/reliability/v1.3-replication-01-preregistration.json"
)
ACCEPTED_REPLICATION_PREREGISTRATION_SHA256 = (
    "169ce60cf8727234f0ce258235f12ccd7cfbb00e10509aa13fb54493707b49ba"
)
ACCEPTED_REPLICATION_PREREGISTRATION_BYTE_SHA256 = (
    "8ca12c82ee72a6b738f169e24b4ad03a174be74589446555e1b4abf7919669a4"
)


class FormalReplicationIntegrityError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_file(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise FormalReplicationIntegrityError(f"missing or unsafe {label}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise FormalReplicationIntegrityError(f"unable to read {label}") from error


def build_formal_replication_preregistration(
    project_root: Path = PROJECT_ROOT,
) -> V13FormalReplicationPreregistration:
    root = Path(project_root).resolve()
    try:
        original = verify_preregistration(root)
        analysis = verify_checked_analysis(root)
        incident = verify_checked_incident(root)
    except Exception as error:
        raise FormalReplicationIntegrityError("checked replication input failed") from error
    if (
        original.design_sha256 != ACCEPTED_DESIGN_SHA256
        or original.candidate_sha256 != ACCEPTED_CANDIDATE_SHA256
        or original.agent_manifest_sha256 != ACCEPTED_AGENT_MANIFEST_SHA256
        or analysis.formal_evidence_freeze_sha256 != ACCEPTED_FORMAL_FREEZE_SHA256
        or incident.original_formal_analysis_sha256 != ACCEPTED_FORMAL_ANALYSIS_SHA256
        or incident.comparative_capability_interpretation_status
        != "infrastructure_confounded"
    ):
        raise FormalReplicationIntegrityError("replication frozen linkage mismatch")

    slots = tuple(V13FormalReplicationSlot(
        ordinal=slot.ordinal,
        slot_id=f"rep01-{slot.slot_id}",
        repetition_index=slot.repetition_index,
        task_id=slot.task_id,
        task_spec_sha256=slot.task_spec_sha256,
        task_fingerprint_sha256=slot.task_fingerprint_sha256,
        resolved_base_commit=slot.resolved_base_commit,
        config_id=slot.config_id,
        config_sha256=slot.config_sha256,
        replication_index=1,
    ) for slot in original.slots)
    return V13FormalReplicationPreregistration(
        replication_id="patchbench-v1.3-replication-01",
        study_id="patchbench-v1.3-formal-replication-01",
        formal_results_namespace="results/v1.3-formal-replication-01",
        original_study_id=original.study_id,
        original_results_namespace=original.formal_results_namespace,
        design_sha256=ACCEPTED_DESIGN_SHA256,
        candidate_sha256=ACCEPTED_CANDIDATE_SHA256,
        agent_manifest_sha256=ACCEPTED_AGENT_MANIFEST_SHA256,
        original_formal_preregistration_sha256=ACCEPTED_PREREGISTRATION_SHA256,
        original_formal_evidence_freeze_sha256=ACCEPTED_FORMAL_FREEZE_SHA256,
        original_formal_analysis_sha256=ACCEPTED_FORMAL_ANALYSIS_SHA256,
        formal_incident_freeze_sha256=ACCEPTED_FORMAL_INCIDENT_SHA256,
        provider_failure_remediation_commit=M16_REMEDIATION_COMMIT,
        replication_reason=(
            "original comparative capability interpretation was infrastructure-confounded "
            "by positively adjudicated Codex same-route HTTP 429 failures that were "
            "canonicalized by the pre-M16 harness"
        ),
        evaluation_backend=original.evaluation_backend,
        repetitions_per_cell=original.repetitions_per_cell,
        planned_slot_count=original.planned_slot_count,
        task_order=original.task_order,
        base_agent_order=original.base_agent_order,
        agent_order_by_repetition=original.agent_order_by_repetition,
        execution_order_policy=original.execution_order_policy,
        execution_admission_required_before_replication=True,
        future_execution_harness_commit_status="not_yet_frozen",
        required_provider_failure_remediation_commit=M16_REMEDIATION_COMMIT,
        structured_codex_http_429_requires_typed_provider_transport_failure=True,
        structured_codex_http_429_forbids_canonical_run=True,
        structured_codex_http_429_failure_category=(
            "network_provider_transport_same_route"
        ),
        provider_route_must_remain_unchanged=True,
        patchbench_automatic_retry_forbidden=True,
        original_outcomes_must_not_influence_replication_design=True,
        original_outcomes_excluded_from=(
            "task_selection", "task_modification", "agent_selection",
            "model_selection", "timeout", "provider_route", "task_order",
            "agent_order", "repetition_count", "retry_policy",
            "metric_definitions", "difficulty_labels", "capability_labels",
            "evaluator_definitions",
        ),
        only_permitted_original_study_consequence=(
            "independent_full_replication_under_corrected_provider_failure_classification"
        ),
        all_replication_observations_require_fresh_execution=True,
        original_runs_are_replication_observations=False,
        original_results_replaced_by_replication=False,
        original_and_replication_primary_metrics_pooled=False,
        replication_primary_metrics_source="replication_01_only",
        original_study_reporting_role=(
            "as_run_operational_study_and_discovered_infrastructure_incident"
        ),
        cross_study_comparison_role="descriptive_sensitivity_only",
        no_performance_based_stopping=True,
        retry_policy=original.retry_policy,
        metrics_policy=original.metrics_policy,
        slots=slots,
    )


def deterministic_json(value: V13FormalReplicationPreregistration) -> str:
    return json.dumps(value.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def load_checked_replication_preregistration(
    project_root: Path = PROJECT_ROOT,
) -> V13FormalReplicationPreregistration:
    try:
        return V13FormalReplicationPreregistration.model_validate_json(
            _read_file(
                Path(project_root) / REPLICATION_PATH,
                "checked replication preregistration",
            )
        )
    except ValidationError as error:
        raise FormalReplicationIntegrityError(
            "invalid checked replication preregistration"
        ) from error


def verify_replication_preregistration(
    project_root: Path = PROJECT_ROOT,
) -> V13FormalReplicationPreregistration:
    root = Path(project_root).resolve()
    checked = load_checked_replication_preregistration(root)
    expected = build_formal_replication_preregistration(root)
    if checked != expected:
        raise FormalReplicationIntegrityError(
            "replication preregistration semantic mismatch"
        )
    if compute_v13_formal_replication_preregistration_sha256(checked) != \
            ACCEPTED_REPLICATION_PREREGISTRATION_SHA256:
        raise FormalReplicationIntegrityError("replication semantic SHA mismatch")
    if _sha256_bytes(_read_file(root / REPLICATION_PATH, "replication artifact")) != \
            ACCEPTED_REPLICATION_PREREGISTRATION_BYTE_SHA256:
        raise FormalReplicationIntegrityError("replication artifact byte SHA mismatch")
    return checked


def write_replication_preregistration(
    value: V13FormalReplicationPreregistration,
    project_root: Path,
) -> None:
    path = Path(project_root) / REPLICATION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(deterministic_json(value))
    except FileExistsError as error:
        raise FormalReplicationIntegrityError(
            "replication preregistration already exists"
        ) from error
    except OSError as error:
        raise FormalReplicationIntegrityError(
            "unable to write replication preregistration"
        ) from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.write:
            value = build_formal_replication_preregistration()
            write_replication_preregistration(value, PROJECT_ROOT)
        else:
            value = verify_replication_preregistration()
    except FormalReplicationIntegrityError as error:
        raise SystemExit(f"Formal replication integrity failure: {error}") from None
    print(
        "replication_preregistration_sha256="
        f"{compute_v13_formal_replication_preregistration_sha256(value)}"
    )


if __name__ == "__main__":
    main()
