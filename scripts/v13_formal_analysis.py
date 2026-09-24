"""Build and verify preregistered metrics from the checked V1.3 formal freeze."""

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

from patchbench.agents.base import AgentRunStatus
from patchbench.domain.benchmark import (
    BenchmarkCapability, BenchmarkDesignManifest, DesignedDifficulty,
    compute_benchmark_design_sha256,
)
from patchbench.domain.formal_analysis import (
    V13FormalAnalysis, V13FormalMetric, V13FormalMetricRow,
    V13FormalRetryReason, V13FormalRetryReporting,
    compute_v13_formal_analysis_sha256,
)
from patchbench.domain.formal_execution import FormalAttemptStatus, FormalSlotStatus
from scripts.v13_formal_evidence import (
    ACCEPTED_FORMAL_FREEZE_SHA256, FormalEvidenceIntegrityError,
    verify_checked_freeze,
)
from scripts.v13_formal_preregistration import (
    ACCEPTED_DESIGN_SHA256, ACCEPTED_PREREGISTRATION_SHA256, DESIGN_PATH,
    verify_preregistration,
)


ANALYSIS_PATH = Path("evidence/v1.3/formal/formal-study-analysis.json")
ACCEPTED_FORMAL_ANALYSIS_SHA256 = "57d591b880e4e40e668488bee3e0886ea36425df7f973b3d0d7a0a8ad69cc25a"
ACCEPTED_FORMAL_ANALYSIS_BYTE_SHA256 = "8ee99aaeea6da1b97ef22c98d8800d776d80c3e528d04eea63e01f0221ff12b0"


class FormalAnalysisIntegrityError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_file(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise FormalAnalysisIntegrityError(f"missing or unsafe {label}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise FormalAnalysisIntegrityError(f"unable to read {label}") from error


def _load_design(root: Path) -> BenchmarkDesignManifest:
    try:
        design = BenchmarkDesignManifest.model_validate_json(
            _read_file(root / DESIGN_PATH, "M1 design")
        )
    except ValidationError as error:
        raise FormalAnalysisIntegrityError("invalid M1 design") from error
    if compute_benchmark_design_sha256(design) != ACCEPTED_DESIGN_SHA256:
        raise FormalAnalysisIntegrityError("M1 design SHA mismatch")
    return design


def _metric(numerator: int, denominator: int) -> V13FormalMetric:
    return V13FormalMetric(
        numerator=numerator,
        denominator=denominator,
        rate=None if denominator == 0 else numerator / denominator,
    )


def _row(value: str, slots) -> V13FormalMetricRow:
    slots = tuple(slots)
    successful = sum(
        slot.canonical_run is not None
        and slot.canonical_run.agent_status is AgentRunStatus.COMPLETED
        and slot.canonical_run.evaluation_passed
        for slot in slots
    )
    completed = sum(
        slot.canonical_run is not None
        and slot.canonical_run.agent_status is AgentRunStatus.COMPLETED
        for slot in slots
    )
    return V13FormalMetricRow(
        value=value,
        end_to_end_reliability=_metric(successful, len(slots)),
        completed_semantic_repair=_metric(successful, completed),
        operational_completion=_metric(completed, len(slots)),
    )


def build_formal_analysis(
    *,
    project_root: Path = PROJECT_ROOT,
    freeze=None,
) -> V13FormalAnalysis:
    root = Path(project_root).resolve()
    if freeze is None:
        try:
            freeze = verify_checked_freeze(root)
        except FormalEvidenceIntegrityError as error:
            raise FormalAnalysisIntegrityError("checked formal freeze failed") from error
    preregistration = verify_preregistration(root)
    design = _load_design(root)
    if (freeze.formal_preregistration_sha256 != ACCEPTED_PREREGISTRATION_SHA256
            or freeze.design_sha256 != ACCEPTED_DESIGN_SHA256
            or tuple((slot.ordinal, slot.slot_id, slot.task_id, slot.config_id)
                     for slot in freeze.slots)
            != tuple((slot.ordinal, slot.slot_id, slot.task_id, slot.config_id)
                     for slot in preregistration.slots)):
        raise FormalAnalysisIntegrityError("formal freeze differs from frozen plan")
    profile_by_task = {profile.task_id: profile for profile in design.tasks}
    if any(
        slot.primary_capability is not profile_by_task[slot.task_id].primary_capability
        or slot.designed_difficulty is not profile_by_task[slot.task_id].designed_difficulty
        for slot in freeze.slots
    ):
        raise FormalAnalysisIntegrityError("formal freeze M1 labels differ from design")

    def grouped(values, selector):
        return tuple(_row(value, (slot for slot in freeze.slots
                                  if selector(slot) == value)) for value in values)

    by_agent = grouped(preregistration.base_agent_order, lambda slot: slot.config_id)
    capability_order = tuple(item.value for item in BenchmarkCapability)
    by_capability = grouped(capability_order, lambda slot: slot.primary_capability.value)
    difficulty_order = tuple(item.value for item in DesignedDifficulty)
    by_difficulty = grouped(difficulty_order, lambda slot: slot.designed_difficulty.value)
    by_task = grouped(preregistration.task_order, lambda slot: slot.task_id)
    expected_denominators = (
        tuple(row.end_to_end_reliability.denominator for row in by_agent),
        tuple(row.end_to_end_reliability.denominator for row in by_capability),
        tuple(row.end_to_end_reliability.denominator for row in by_difficulty),
        tuple(row.end_to_end_reliability.denominator for row in by_task),
    )
    if expected_denominators != ((36,) * 3, (27,) * 4, (36,) * 3, (9,) * 12):
        raise FormalAnalysisIntegrityError("formal strata are not balanced as preregistered")

    retried = tuple(slot for slot in freeze.slots if len(slot.attempts) == 2)
    eligible_order = tuple(preregistration.retry_policy.retry_eligible_failure_categories)
    reason_counts = {
        category: sum(
            slot.attempts[0].failure_category is not None
            and slot.attempts[0].failure_category.value == category
            for slot in retried
        )
        for category in eligible_order
    }
    retry_reporting = V13FormalRetryReporting(
        slots_requiring_retry=tuple(slot.slot_id for slot in retried),
        retry_reasons=tuple(
            V13FormalRetryReason(failure_category=category, count=reason_counts[category])
            for category in eligible_order if reason_counts[category]
        ),
        slots_resolving_on_retry=tuple(
            slot.slot_id for slot in retried
            if slot.attempts[1].status is FormalAttemptStatus.CANONICAL_OBSERVED
        ),
        slots_unresolved_after_retry=tuple(
            slot.slot_id for slot in retried
            if slot.source_slot_status is FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE
        ),
    )
    return V13FormalAnalysis(
        analysis_id="patchbench-v1.3-formal-analysis",
        formal_evidence_freeze_sha256=compute_freeze_sha(freeze),
        formal_preregistration_sha256=ACCEPTED_PREREGISTRATION_SHA256,
        design_sha256=ACCEPTED_DESIGN_SHA256,
        metrics_policy=preregistration.metrics_policy,
        overall=_row("overall", freeze.slots),
        by_agent_configuration=by_agent,
        by_primary_capability=by_capability,
        by_designed_difficulty=by_difficulty,
        by_task=by_task,
        retry_reporting=retry_reporting,
    )


def compute_freeze_sha(freeze) -> str:
    from patchbench.domain.formal_evidence import (
        compute_v13_formal_evidence_freeze_sha256,
    )
    return compute_v13_formal_evidence_freeze_sha256(freeze)


def deterministic_json(analysis: V13FormalAnalysis) -> str:
    return json.dumps(analysis.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def load_checked_analysis(project_root: Path = PROJECT_ROOT) -> V13FormalAnalysis:
    try:
        return V13FormalAnalysis.model_validate_json(
            _read_file(Path(project_root) / ANALYSIS_PATH, "checked formal analysis")
        )
    except ValidationError as error:
        raise FormalAnalysisIntegrityError("invalid checked formal analysis") from error


def verify_checked_analysis(project_root: Path = PROJECT_ROOT) -> V13FormalAnalysis:
    root = Path(project_root).resolve()
    freeze = verify_checked_freeze(root)
    checked = load_checked_analysis(root)
    expected = build_formal_analysis(project_root=root, freeze=freeze)
    if checked != expected:
        raise FormalAnalysisIntegrityError("checked formal analysis semantic mismatch")
    if compute_v13_formal_analysis_sha256(checked) != ACCEPTED_FORMAL_ANALYSIS_SHA256:
        raise FormalAnalysisIntegrityError("formal analysis semantic SHA mismatch")
    if _sha256_bytes(_read_file(root / ANALYSIS_PATH, "checked formal analysis")) != \
            ACCEPTED_FORMAL_ANALYSIS_BYTE_SHA256:
        raise FormalAnalysisIntegrityError("formal analysis artifact byte SHA mismatch")
    if checked.formal_evidence_freeze_sha256 != ACCEPTED_FORMAL_FREEZE_SHA256:
        raise FormalAnalysisIntegrityError("formal analysis freeze link mismatch")
    return checked


def write_analysis(analysis: V13FormalAnalysis, project_root: Path) -> None:
    path = Path(project_root) / ANALYSIS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(deterministic_json(analysis))
    except FileExistsError as error:
        raise FormalAnalysisIntegrityError("checked formal analysis already exists") from error
    except OSError as error:
        raise FormalAnalysisIntegrityError("unable to write checked formal analysis") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.write:
            analysis = build_formal_analysis()
            write_analysis(analysis, PROJECT_ROOT)
        else:
            analysis = verify_checked_analysis()
    except (FormalAnalysisIntegrityError, FormalEvidenceIntegrityError) as error:
        raise SystemExit(f"Formal analysis integrity failure: {error}") from None
    print(f"formal_analysis_sha256={compute_v13_formal_analysis_sha256(analysis)}")


if __name__ == "__main__":
    main()
