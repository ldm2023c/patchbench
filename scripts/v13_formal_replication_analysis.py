"""Build and verify preregistered Replication-01 metrics."""

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

from patchbench.domain.formal_analysis import (
    V13FormalReplicationAnalysis,
    compute_v13_formal_replication_analysis_sha256,
)
from patchbench.domain.formal_evidence import (
    compute_v13_formal_replication_evidence_freeze_sha256,
)
from scripts.v13_formal_analysis import (
    FormalAnalysisIntegrityError,
    _load_design,
    _read_file,
    _sha256_bytes,
    build_preregistered_metric_sections,
)
from scripts.v13_formal_preregistration import ACCEPTED_DESIGN_SHA256
from scripts.v13_formal_replication_evidence import (
    ACCEPTED_REPLICATION_FORMAL_FREEZE_SHA256,
    FormalReplicationEvidenceIntegrityError,
    verify_checked_replication_freeze,
)
from scripts.v13_formal_replication_preregistration import (
    ACCEPTED_REPLICATION_PREREGISTRATION_SHA256,
    verify_replication_preregistration,
)


ANALYSIS_PATH = Path(
    "evidence/v1.3/formal-replication-01/formal-study-analysis.json"
)
ACCEPTED_REPLICATION_FORMAL_ANALYSIS_SHA256: str | None = (
    "85059fe78f7cf533d27efe13ba02a1081e362fdecf1611d9473afea8e8b0a6f9"
)
ACCEPTED_REPLICATION_FORMAL_ANALYSIS_BYTE_SHA256: str | None = (
    "18d0ee7a5bf7b78a0e7b47e01935a25b4608fbb05c7b588b84ea805d40d35bf2"
)


class FormalReplicationAnalysisIntegrityError(FormalAnalysisIntegrityError):
    pass


def build_formal_replication_analysis(
    *,
    project_root: Path = PROJECT_ROOT,
    freeze=None,
) -> V13FormalReplicationAnalysis:
    root = Path(project_root).resolve()
    if freeze is None:
        try:
            freeze = verify_checked_replication_freeze(root)
        except FormalReplicationEvidenceIntegrityError as error:
            raise FormalReplicationAnalysisIntegrityError(
                "checked replication freeze failed"
            ) from error
    preregistration = verify_replication_preregistration(root)
    design = _load_design(root)
    if (
        freeze.replication_preregistration_sha256
        != ACCEPTED_REPLICATION_PREREGISTRATION_SHA256
        or freeze.design_sha256 != ACCEPTED_DESIGN_SHA256
        or tuple(
            (slot.ordinal, slot.slot_id, slot.task_id, slot.config_id)
            for slot in freeze.slots
        )
        != tuple(
            (slot.ordinal, slot.slot_id, slot.task_id, slot.config_id)
            for slot in preregistration.slots
        )
    ):
        raise FormalReplicationAnalysisIntegrityError(
            "replication freeze differs from frozen plan"
        )
    (overall, by_agent, by_capability, by_difficulty, by_task,
     retry_reporting) = build_preregistered_metric_sections(
        freeze=freeze,
        preregistration=preregistration,
        design=design,
    )
    return V13FormalReplicationAnalysis(
        analysis_id="patchbench-v1.3-formal-replication-01-analysis",
        formal_replication_evidence_freeze_sha256=(
            compute_v13_formal_replication_evidence_freeze_sha256(freeze)
        ),
        replication_preregistration_sha256=(
            ACCEPTED_REPLICATION_PREREGISTRATION_SHA256
        ),
        design_sha256=ACCEPTED_DESIGN_SHA256,
        metrics_policy=preregistration.metrics_policy,
        overall=overall,
        by_agent_configuration=by_agent,
        by_primary_capability=by_capability,
        by_designed_difficulty=by_difficulty,
        by_task=by_task,
        retry_reporting=retry_reporting,
    )


def deterministic_json(value: V13FormalReplicationAnalysis) -> str:
    return json.dumps(value.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def load_checked_replication_analysis(
    project_root: Path = PROJECT_ROOT,
) -> V13FormalReplicationAnalysis:
    try:
        return V13FormalReplicationAnalysis.model_validate_json(
            _read_file(
                Path(project_root) / ANALYSIS_PATH,
                "checked replication analysis",
            )
        )
    except ValidationError as error:
        raise FormalReplicationAnalysisIntegrityError(
            "invalid checked replication analysis"
        ) from error


def verify_checked_replication_analysis(
    project_root: Path = PROJECT_ROOT,
) -> V13FormalReplicationAnalysis:
    if (
        ACCEPTED_REPLICATION_FORMAL_ANALYSIS_SHA256 is None
        or ACCEPTED_REPLICATION_FORMAL_ANALYSIS_BYTE_SHA256 is None
        or ACCEPTED_REPLICATION_FORMAL_FREEZE_SHA256 is None
    ):
        raise FormalReplicationAnalysisIntegrityError(
            "M20 replication analysis is not locked"
        )
    root = Path(project_root).resolve()
    freeze = verify_checked_replication_freeze(root)
    checked = load_checked_replication_analysis(root)
    expected = build_formal_replication_analysis(
        project_root=root, freeze=freeze
    )
    if checked != expected:
        raise FormalReplicationAnalysisIntegrityError(
            "checked replication analysis semantic mismatch"
        )
    if compute_v13_formal_replication_analysis_sha256(checked) != \
            ACCEPTED_REPLICATION_FORMAL_ANALYSIS_SHA256:
        raise FormalReplicationAnalysisIntegrityError(
            "replication analysis semantic SHA mismatch"
        )
    if _sha256_bytes(
        _read_file(root / ANALYSIS_PATH, "checked replication analysis")
    ) != ACCEPTED_REPLICATION_FORMAL_ANALYSIS_BYTE_SHA256:
        raise FormalReplicationAnalysisIntegrityError(
            "replication analysis artifact byte SHA mismatch"
        )
    if checked.formal_replication_evidence_freeze_sha256 != \
            ACCEPTED_REPLICATION_FORMAL_FREEZE_SHA256:
        raise FormalReplicationAnalysisIntegrityError(
            "replication analysis freeze link mismatch"
        )
    return checked


def write_replication_analysis(
    value: V13FormalReplicationAnalysis,
    project_root: Path,
) -> None:
    path = Path(project_root) / ANALYSIS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(deterministic_json(value))
    except FileExistsError as error:
        raise FormalReplicationAnalysisIntegrityError(
            "checked replication analysis already exists"
        ) from error
    except OSError as error:
        raise FormalReplicationAnalysisIntegrityError(
            "unable to write checked replication analysis"
        ) from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.write:
            freeze = verify_checked_replication_freeze()
            value = build_formal_replication_analysis(freeze=freeze)
            write_replication_analysis(value, PROJECT_ROOT)
        else:
            value = verify_checked_replication_analysis()
    except (
        FormalAnalysisIntegrityError,
        FormalReplicationEvidenceIntegrityError,
    ) as error:
        raise SystemExit(
            f"Replication analysis integrity failure: {error}"
        ) from None
    print(
        "replication_formal_analysis_sha256="
        f"{compute_v13_formal_replication_analysis_sha256(value)}"
    )


if __name__ == "__main__":
    main()
