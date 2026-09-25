"""Build and verify the compact V1.3 Replication-01 evidence freeze."""

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

from patchbench.application.v13_formal_execution import check_formal_study
from patchbench.application.v13_formal_replication_execution import (
    DEFAULT_REPLICATION_RESULTS_PATH,
    ORIGINAL_FORMAL_RESULTS_PATH,
    REPLICATION_FORMAL_EXECUTION_CONTRACT,
)
from patchbench.domain.formal_evidence import (
    V13FormalReplicationEvidenceFreeze,
    compute_v13_formal_replication_evidence_freeze_sha256,
    compute_v13_formal_study_sha256,
)
from patchbench.domain.formal_execution import (
    FormalSlotStatus,
    FormalStudyStatus,
    V13FormalStudyLedger,
)
from scripts.v13_formal_evidence import (
    FormalEvidenceIntegrityError,
    _load_design,
    _read_exact_file,
    _sha256_bytes,
    freeze_verified_slots,
)
from scripts.v13_formal_preregistration import (
    ACCEPTED_AGENT_MANIFEST_SHA256,
    ACCEPTED_CANDIDATE_SHA256,
    ACCEPTED_DESIGN_SHA256,
)
from scripts.v13_formal_replication_execution_admission import (
    ACCEPTED_REPLICATION_EXECUTION_ADMISSION_SHA256,
    REVIEWED_M18A_EXECUTION_HARNESS_COMMIT,
    verify_checked_replication_execution_admission,
)
from scripts.v13_formal_replication_preregistration import (
    ACCEPTED_REPLICATION_PREREGISTRATION_SHA256,
    verify_replication_preregistration,
)


FREEZE_PATH = Path(
    "evidence/v1.3/formal-replication-01/formal-study-freeze.json"
)
DEFAULT_SOURCE = DEFAULT_REPLICATION_RESULTS_PATH
ACCEPTED_REPLICATION_FORMAL_FREEZE_SHA256: str | None = (
    "e5389dec6b316263bb5c2582b19ea64ba4fb8be1e34d906cf9009436301be395"
)
ACCEPTED_REPLICATION_FORMAL_FREEZE_BYTE_SHA256: str | None = (
    "84d1504b689634809d8e1d6e4ea3db22366c4bb1a1af6dd5469e3b1921ee77f2"
)


class FormalReplicationEvidenceIntegrityError(FormalEvidenceIntegrityError):
    pass


def _reject_namespace_alias(root: Path, source: Path) -> None:
    if source.resolve() == (root / ORIGINAL_FORMAL_RESULTS_PATH).resolve():
        raise FormalReplicationEvidenceIntegrityError(
            "replication source aliases original formal results"
        )


def build_formal_replication_evidence_freeze(
    source_results: Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> V13FormalReplicationEvidenceFreeze:
    root = Path(project_root).resolve()
    supplied_source = Path(source_results)
    if supplied_source.is_symlink():
        raise FormalReplicationEvidenceIntegrityError(
            "replication source namespace is symlinked"
        )
    source = supplied_source.resolve()
    _reject_namespace_alias(root, source)

    preregistration = verify_replication_preregistration(root)
    admission = verify_checked_replication_execution_admission(root)
    ledger = check_formal_study(
        project_root=root,
        results_root=source,
        contract=REPLICATION_FORMAL_EXECUTION_CONTRACT,
    )
    design = _load_design(root)
    if ledger.status is not FormalStudyStatus.COMPLETED:
        raise FormalReplicationEvidenceIntegrityError(
            "replication source study is not completed"
        )
    study_bytes = _read_exact_file(source / "study.json", "replication study ledger")
    try:
        if V13FormalStudyLedger.model_validate_json(study_bytes) != ledger:
            raise FormalReplicationEvidenceIntegrityError(
                "replication study changed during verification"
            )
    except ValidationError as error:
        raise FormalReplicationEvidenceIntegrityError(
            "invalid replication study ledger"
        ) from error
    if tuple(
        (item.ordinal, item.slot_id, item.repetition_index, item.task_id, item.config_id)
        for item in ledger.slots
    ) != tuple(
        (item.ordinal, item.slot_id, item.repetition_index, item.task_id, item.config_id)
        for item in preregistration.slots
    ):
        raise FormalReplicationEvidenceIntegrityError(
            "replication source slots differ from preregistration"
        )

    frozen_slots = freeze_verified_slots(
        source,
        ledger=ledger,
        preregistration=preregistration,
        design=design,
        accepted_preregistration_sha256=(
            ACCEPTED_REPLICATION_PREREGISTRATION_SHA256
        ),
    )
    canonical_count = sum(
        slot.status is FormalSlotStatus.CANONICAL_OBSERVED for slot in ledger.slots
    )
    unresolved_count = sum(
        slot.status is FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE
        for slot in ledger.slots
    )
    blocked_count = sum(
        slot.status is FormalSlotStatus.BLOCKED for slot in ledger.slots
    )
    terminal_count = canonical_count + unresolved_count
    if (
        len(ledger.slots) != 108
        or terminal_count != 108
        or canonical_count != 107
        or unresolved_count != 1
        or blocked_count != 0
    ):
        raise FormalReplicationEvidenceIntegrityError(
            "replication terminal counts differ from the completed M19 study"
        )
    return V13FormalReplicationEvidenceFreeze(
        freeze_id="patchbench-v1.3-formal-replication-01-results",
        replication_id=preregistration.replication_id,
        study_id=ledger.study_id,
        replication_preregistration_sha256=(
            ACCEPTED_REPLICATION_PREREGISTRATION_SHA256
        ),
        design_sha256=ACCEPTED_DESIGN_SHA256,
        candidate_sha256=ACCEPTED_CANDIDATE_SHA256,
        agent_manifest_sha256=ACCEPTED_AGENT_MANIFEST_SHA256,
        execution_harness_commit=REVIEWED_M18A_EXECUTION_HARNESS_COMMIT,
        execution_admission_sha256=(
            ACCEPTED_REPLICATION_EXECUTION_ADMISSION_SHA256
        ),
        source_study_status=ledger.status.value,
        source_study_json_sha256=_sha256_bytes(study_bytes),
        source_study_semantic_sha256=compute_v13_formal_study_sha256(ledger),
        planned_slot_count=preregistration.planned_slot_count,
        terminal_slot_count=terminal_count,
        canonical_slot_count=canonical_count,
        unresolved_infrastructure_slot_count=unresolved_count,
        blocked_slot_count=blocked_count,
        slots=frozen_slots,
    )


def deterministic_json(value: V13FormalReplicationEvidenceFreeze) -> str:
    return json.dumps(value.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def load_checked_replication_freeze(
    project_root: Path = PROJECT_ROOT,
) -> V13FormalReplicationEvidenceFreeze:
    try:
        return V13FormalReplicationEvidenceFreeze.model_validate_json(
            _read_exact_file(
                Path(project_root) / FREEZE_PATH,
                "checked replication freeze",
            )
        )
    except ValidationError as error:
        raise FormalReplicationEvidenceIntegrityError(
            "invalid checked replication freeze"
        ) from error


def verify_checked_replication_freeze(
    project_root: Path = PROJECT_ROOT,
) -> V13FormalReplicationEvidenceFreeze:
    if (
        ACCEPTED_REPLICATION_FORMAL_FREEZE_SHA256 is None
        or ACCEPTED_REPLICATION_FORMAL_FREEZE_BYTE_SHA256 is None
    ):
        raise FormalReplicationEvidenceIntegrityError(
            "M20 replication freeze is not locked"
        )
    root = Path(project_root).resolve()
    freeze = load_checked_replication_freeze(root)
    raw = _read_exact_file(root / FREEZE_PATH, "checked replication freeze")
    if compute_v13_formal_replication_evidence_freeze_sha256(freeze) != \
            ACCEPTED_REPLICATION_FORMAL_FREEZE_SHA256:
        raise FormalReplicationEvidenceIntegrityError(
            "replication freeze semantic SHA mismatch"
        )
    if _sha256_bytes(raw) != ACCEPTED_REPLICATION_FORMAL_FREEZE_BYTE_SHA256:
        raise FormalReplicationEvidenceIntegrityError(
            "replication freeze artifact byte SHA mismatch"
        )
    preregistration = verify_replication_preregistration(root)
    admission = verify_checked_replication_execution_admission(root)
    if (
        freeze.replication_id != preregistration.replication_id
        or freeze.study_id != preregistration.study_id
        or freeze.replication_preregistration_sha256
        != ACCEPTED_REPLICATION_PREREGISTRATION_SHA256
        or freeze.design_sha256 != ACCEPTED_DESIGN_SHA256
        or freeze.candidate_sha256 != ACCEPTED_CANDIDATE_SHA256
        or freeze.agent_manifest_sha256 != ACCEPTED_AGENT_MANIFEST_SHA256
        or freeze.execution_harness_commit != admission.execution_harness_commit
        or freeze.execution_admission_sha256
        != ACCEPTED_REPLICATION_EXECUTION_ADMISSION_SHA256
    ):
        raise FormalReplicationEvidenceIntegrityError(
            "replication freeze frozen-link mismatch"
        )
    return freeze


def verify_source_against_checked_replication_freeze(
    source_results: Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> V13FormalReplicationEvidenceFreeze:
    checked = verify_checked_replication_freeze(project_root)
    rebuilt = build_formal_replication_evidence_freeze(
        source_results, project_root=project_root
    )
    if rebuilt != checked:
        raise FormalReplicationEvidenceIntegrityError(
            "replication source evidence differs from freeze"
        )
    return checked


def write_replication_freeze(
    value: V13FormalReplicationEvidenceFreeze,
    project_root: Path,
) -> None:
    path = Path(project_root) / FREEZE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(deterministic_json(value))
    except FileExistsError as error:
        raise FormalReplicationEvidenceIntegrityError(
            "checked replication freeze already exists"
        ) from error
    except OSError as error:
        raise FormalReplicationEvidenceIntegrityError(
            "unable to write checked replication freeze"
        ) from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--check-source", action="store_true")
    parser.add_argument(
        "--source-results", type=Path, default=PROJECT_ROOT / DEFAULT_SOURCE
    )
    args = parser.parse_args()
    try:
        if args.write:
            value = build_formal_replication_evidence_freeze(args.source_results)
            write_replication_freeze(value, PROJECT_ROOT)
        elif args.check_source:
            value = verify_source_against_checked_replication_freeze(
                args.source_results
            )
        else:
            value = verify_checked_replication_freeze()
    except FormalEvidenceIntegrityError as error:
        raise SystemExit(f"Replication evidence integrity failure: {error}") from None
    print(
        "replication_formal_freeze_sha256="
        f"{compute_v13_formal_replication_evidence_freeze_sha256(value)}"
    )


if __name__ == "__main__":
    main()
