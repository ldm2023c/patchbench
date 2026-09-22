"""Build and verify the PatchBench V1.3 formal-study preregistration."""

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

from patchbench.domain.agent_identity import (
    AgentConfigurationManifest,
    compute_agent_configuration_manifest_sha256,
    compute_agent_configuration_sha256,
)
from patchbench.domain.benchmark import (
    BenchmarkCandidateManifest,
    BenchmarkDesignManifest,
    compute_benchmark_candidate_sha256,
    compute_benchmark_design_sha256,
)
from patchbench.domain.calibration import (
    V13CalibrationProtocol,
    compute_v13_calibration_protocol_sha256,
)
from patchbench.domain.formal_study import (
    V13FormalMetricPolicy,
    V13FormalPreregistration,
    V13FormalRetryPolicy,
    V13FormalSlot,
    compute_v13_formal_preregistration_sha256,
)
from scripts.v13_calibration_evidence import (
    ACCEPTED_FREEZE_SHA256,
    load_checked_freeze,
    verify_checked_freeze,
)


DESIGN_PATH = Path("tasks/reliability/v1.3-design.json")
CANDIDATE_PATH = Path("tasks/reliability/v1.3-candidate.json")
AGENT_MANIFEST_PATH = Path("tasks/reliability/v1.3-agent-configurations.json")
CALIBRATION_PROTOCOL_PATH = Path("tasks/reliability/v1.3-calibration-protocol.json")
PREREGISTRATION_PATH = Path("tasks/reliability/v1.3-formal-preregistration.json")

ACCEPTED_DESIGN_SHA256 = "dc48fdac627abe9fcd95303d3042b5f0c822abbb0bb53a4dfba17dcc2f99f931"
ACCEPTED_CANDIDATE_SHA256 = "a51000e6afccfea67ae198e3fa024a36cea02d49a22945aafc763c3d9302d043"
ACCEPTED_AGENT_MANIFEST_SHA256 = "6902dcac0c86c514405107fb2752c3b011e5bf119a3c35ee1164bd90ff0cb965"
ACCEPTED_CALIBRATION_PROTOCOL_SHA256 = "1347188de4d5cd3e25fb4f4444a60e7c0994dd4b020cb514bf369479d4794eff"
ACCEPTED_PREREGISTRATION_SHA256 = "192291d7d4f86f704dfd3200bea321fa5bb9ad04ce354e1724bcdb0ac837f807"
ACCEPTED_PREREGISTRATION_BYTE_SHA256 = "670ca7f4cd8ee874305a41f7411c47aece568c8452557d689cf5a509ec57a1b3"


class FormalPreregistrationIntegrityError(RuntimeError):
    pass


def _load(path: Path, model_type, label: str):
    try:
        return model_type.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise FormalPreregistrationIntegrityError(f"invalid {label}") from error


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise FormalPreregistrationIntegrityError("unable to hash preregistration input") from error


def build_formal_preregistration(
    project_root: Path = PROJECT_ROOT,
) -> V13FormalPreregistration:
    root = Path(project_root).resolve()
    design = _load(root / DESIGN_PATH, BenchmarkDesignManifest, "M1 design")
    candidate = _load(root / CANDIDATE_PATH, BenchmarkCandidateManifest, "M3 candidate")
    manifest = _load(root / AGENT_MANIFEST_PATH, AgentConfigurationManifest, "M8 manifest")
    protocol = _load(
        root / CALIBRATION_PROTOCOL_PATH, V13CalibrationProtocol, "M10A protocol"
    )
    freeze = verify_checked_freeze(root)

    design_sha = compute_benchmark_design_sha256(design)
    candidate_sha = compute_benchmark_candidate_sha256(candidate)
    manifest_sha = compute_agent_configuration_manifest_sha256(manifest)
    protocol_sha = compute_v13_calibration_protocol_sha256(protocol)
    if design_sha != ACCEPTED_DESIGN_SHA256:
        raise FormalPreregistrationIntegrityError("M1 design SHA mismatch")
    if (candidate_sha != ACCEPTED_CANDIDATE_SHA256
            or candidate.design_sha256 != design_sha):
        raise FormalPreregistrationIntegrityError("M3 candidate SHA/link mismatch")
    if manifest_sha != ACCEPTED_AGENT_MANIFEST_SHA256:
        raise FormalPreregistrationIntegrityError("M8 manifest SHA mismatch")
    if (protocol_sha != ACCEPTED_CALIBRATION_PROTOCOL_SHA256
            or protocol.m3_candidate_sha256 != candidate_sha
            or protocol.m8_agent_manifest_sha256 != manifest_sha):
        raise FormalPreregistrationIntegrityError("M10A protocol SHA/link mismatch")
    if (freeze.source_batch_id != "calibration-001"
            or freeze.calibration_protocol_sha256 != protocol_sha
            or freeze.m3_candidate_sha256 != candidate_sha
            or freeze.m8_agent_manifest_sha256 != manifest_sha
            or not all(slot.agent_status.value == "completed" for slot in freeze.slots)):
        raise FormalPreregistrationIntegrityError("calibration freeze link/admission mismatch")

    task_order = tuple(task.task_id for task in candidate.tasks)
    design_order = tuple(task.task_id for task in design.tasks)
    base_agent_order = tuple(config.config_id for config in manifest.configurations)
    if task_order != design_order or len(task_order) != 12:
        raise FormalPreregistrationIntegrityError("M1/M3 task order mismatch")
    if base_agent_order != protocol.ordered_agent_config_ids or len(base_agent_order) != 3:
        raise FormalPreregistrationIntegrityError("M8/M10A Agent order mismatch")
    if tuple(slot.config_id for slot in freeze.slots) != base_agent_order:
        raise FormalPreregistrationIntegrityError("calibration admission config mismatch")

    task_by_id = {task.task_id: task for task in candidate.tasks}
    config_sha = {
        config.config_id: compute_agent_configuration_sha256(config)
        for config in manifest.configurations
    }
    rotations = tuple(
        base_agent_order[index:] + base_agent_order[:index] for index in range(3)
    )
    slots = []
    ordinal = 1
    for repetition_index, agent_order in enumerate(rotations, start=1):
        for task_id in task_order:
            task = task_by_id[task_id]
            for config_id in agent_order:
                slots.append(V13FormalSlot(
                    ordinal=ordinal,
                    slot_id=f"r{repetition_index:02d}-{task_id}-{config_id}",
                    repetition_index=repetition_index,
                    task_id=task_id,
                    task_spec_sha256=task.task_spec_sha256,
                    task_fingerprint_sha256=task.task_fingerprint_sha256,
                    resolved_base_commit=task.resolved_base_commit,
                    config_id=config_id,
                    config_sha256=config_sha[config_id],
                ))
                ordinal += 1

    retry = V13FormalRetryPolicy(
        max_attempts_per_slot=2,
        max_retries_per_slot=1,
        retry_requires_no_canonical_run_record=True,
        retry_eligible_failure_categories=(
            "agent_setup", "agent_infrastructure", "repository_infrastructure",
            "docker_infrastructure", "artifact_infrastructure_before_canonical_run",
            "network_provider_transport_same_route",
        ),
        canonical_run_disables_retry=True,
        canonical_agent_statuses_not_retryable=(
            "completed", "command_failed", "timed_out",
        ),
        evaluator_failure_not_retryable=True,
        evaluation_infrastructure_error_not_retryable=True,
        empty_patch_not_retryable=True,
        incorrect_semantic_repair_not_retryable=True,
        frozen_task_integrity_failure_not_retryable=True,
        retry_preserves_slot_identity=True,
        retry_identity_fields=(
            "slot_id", "task", "base_commit", "task_spec", "config_id", "m8_binding",
            "requested_model", "timeout", "provider_endpoint_or_relay", "evaluator",
            "backend", "repetition",
        ),
        retry_does_not_add_planned_slot=True,
        no_fallback_agent=True,
        no_substitute_task=True,
        no_replacement_slot=True,
        exhausted_infrastructure_slot_remains_in_denominator=True,
        first_attempt_evidence_retained=True,
        explicit_environment_remediation_required=True,
        allowed_environment_remediation=(
            "authentication availability",
            "restoration of the required frozen CLI/version",
            "Docker availability",
            "network/provider transport availability without changing provider route",
            "host/process/filesystem setup that does not change frozen study semantics",
        ),
        forbidden_semantic_remediation=(
            "M3 task changes", "M4 policy changes", "M8 manifest changes",
            "model changes", "timeout changes", "provider route/endpoint changes",
            "Grok context-window changes", "prompt changes", "evaluator changes",
            "M9 trusted execution changes", "repetition/order changes", "metric changes",
        ),
    )
    metrics = V13FormalMetricPolicy(
        end_to_end_success_condition="canonical_completed_and_evaluator_pass",
        end_to_end_denominator="all_planned_slots_in_stratum",
        unresolved_infrastructure_is_end_to_end_failure=True,
        completed_semantic_repair_numerator="canonical_completed_and_evaluator_pass",
        completed_semantic_repair_denominator="canonical_completed_slots",
        completed_semantic_repair_is_conditional=True,
        operational_completion_numerator="canonical_completed_slots",
        operational_completion_denominator="all_planned_slots_in_stratum",
        operational_completion_is_descriptive=True,
        retry_reporting_required=(
            "slots_requiring_retry", "retry_reasons", "slots_resolving_on_retry",
            "slots_unresolved_after_retry",
        ),
        reporting_strata=(
            "overall", "agent_configuration", "primary_capability",
            "designed_difficulty", "task",
        ),
        m1_m3_design_labels_authoritative=True,
        no_weighted_composite_agent_score=True,
        no_post_hoc_best_agent_rule=True,
        no_outcome_based_task_removal=True,
        no_outcome_based_agent_removal=True,
        no_difficulty_relabeling=True,
        no_failure_denominator_exclusion=True,
        no_cherry_picked_repetitions=True,
        no_replacement_runs_beyond_retry=True,
        no_performance_based_stopping=True,
    )
    return V13FormalPreregistration(
        study_id="patchbench-v1.3-formal",
        design_sha256=design_sha,
        candidate_sha256=candidate_sha,
        agent_manifest_sha256=manifest_sha,
        calibration_protocol_sha256=protocol_sha,
        calibration_evidence_freeze_sha256=ACCEPTED_FREEZE_SHA256,
        accepted_calibration_batch_id=freeze.source_batch_id,
        evaluation_backend="docker",
        repetitions_per_cell=3,
        planned_slot_count=108,
        task_order=task_order,
        base_agent_order=base_agent_order,
        agent_order_by_repetition=rotations,
        execution_order_policy="repetition_then_m3_task_then_rotated_agent",
        formal_results_namespace="results/v1.3-formal",
        calibration_outcome_must_not_influence_formal_design=True,
        calibration_outcome_excluded_from=(
            "task_selection", "agent_selection", "model_selection", "timeout",
            "endpoint_or_relay", "task_order", "repetition_count", "retry_policy",
            "metric_definitions",
        ),
        retry_policy=retry,
        metrics_policy=metrics,
        slots=tuple(slots),
    )


def deterministic_json(value: V13FormalPreregistration) -> str:
    return json.dumps(value.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def load_preregistration(project_root: Path = PROJECT_ROOT) -> V13FormalPreregistration:
    return _load(
        project_root / PREREGISTRATION_PATH,
        V13FormalPreregistration,
        "formal preregistration",
    )


def verify_preregistration(project_root: Path = PROJECT_ROOT) -> V13FormalPreregistration:
    checked = load_preregistration(project_root)
    expected = build_formal_preregistration(project_root)
    if checked != expected:
        raise FormalPreregistrationIntegrityError("formal preregistration semantic mismatch")
    if compute_v13_formal_preregistration_sha256(checked) != ACCEPTED_PREREGISTRATION_SHA256:
        raise FormalPreregistrationIntegrityError("formal preregistration SHA mismatch")
    if _sha256_file(project_root / PREREGISTRATION_PATH) != ACCEPTED_PREREGISTRATION_BYTE_SHA256:
        raise FormalPreregistrationIntegrityError("formal preregistration byte SHA mismatch")
    return checked


def write_preregistration(value: V13FormalPreregistration, project_root: Path) -> None:
    path = project_root / PREREGISTRATION_PATH
    path.write_text(deterministic_json(value), encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.write:
            value = build_formal_preregistration()
            write_preregistration(value, PROJECT_ROOT)
        else:
            value = verify_preregistration()
    except FormalPreregistrationIntegrityError as error:
        raise SystemExit(f"Formal preregistration integrity failure: {error}") from None
    print(f"formal_preregistration_sha256={compute_v13_formal_preregistration_sha256(value)}")


if __name__ == "__main__":
    main()
