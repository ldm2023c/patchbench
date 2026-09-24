"""Build and verify the compact PatchBench V1.3 formal evidence freeze."""

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
from patchbench.domain.benchmark import (
    BenchmarkDesignManifest, compute_benchmark_design_sha256,
)
from patchbench.domain.calibration_evidence import compute_run_semantic_sha256
from patchbench.domain.formal_evidence import (
    V13FormalAttemptEvidence, V13FormalEvidenceFreeze, V13FormalRunEvidence,
    V13FormalSlotEvidence, compute_v13_formal_attempt_sha256,
    compute_v13_formal_evidence_freeze_sha256, compute_v13_formal_study_sha256,
)
from patchbench.domain.formal_execution import (
    FormalAttemptStatus, FormalSlotStatus, FormalStudyStatus,
    V13FormalAttemptRecord, V13FormalStudyLedger,
)
from patchbench.storage.filesystem import ArtifactStoreError, FilesystemArtifactStore
from scripts.v13_formal_preregistration import (
    ACCEPTED_AGENT_MANIFEST_SHA256, ACCEPTED_CANDIDATE_SHA256,
    ACCEPTED_DESIGN_SHA256, ACCEPTED_PREREGISTRATION_SHA256, DESIGN_PATH,
    verify_preregistration,
)


FREEZE_PATH = Path("evidence/v1.3/formal/formal-study-freeze.json")
DEFAULT_SOURCE = Path("results/v1.3-formal")
EXECUTION_HARNESS_COMMIT = "c735b112770060cb1dd367406c5b764f673ce6ba"
ACCEPTED_FORMAL_FREEZE_SHA256 = "c41b52f10d50075ac30bfc0ff1d2f5f498ff5960ec36f4b7aa9958495d1264bd"
ACCEPTED_FORMAL_FREEZE_BYTE_SHA256 = "40eb02324e55338f3c2c30ec0d393aaeddd74c17a49f2f69461ae553a1400cb2"

_RAW_RUN_FILES = {
    "metadata_sha256": "metadata.json",
    "prompt_sha256": "prompt.txt",
    "agent_stdout_sha256": "agent.log",
    "agent_stderr_sha256": "agent.stderr.log",
    "test_log_sha256": "test.log",
    "patch_sha256": "patch.diff",
}


class FormalEvidenceIntegrityError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_exact_file(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise FormalEvidenceIntegrityError(f"missing or unsafe {label}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise FormalEvidenceIntegrityError(f"unable to read {label}") from error


def _load_design(root: Path) -> BenchmarkDesignManifest:
    try:
        design = BenchmarkDesignManifest.model_validate_json(
            _read_exact_file(root / DESIGN_PATH, "M1 design")
        )
    except ValidationError as error:
        raise FormalEvidenceIntegrityError("invalid M1 design") from error
    if compute_benchmark_design_sha256(design) != ACCEPTED_DESIGN_SHA256:
        raise FormalEvidenceIntegrityError("M1 design SHA mismatch")
    return design


def _load_attempt(path: Path) -> tuple[V13FormalAttemptRecord, bytes]:
    raw = _read_exact_file(path / "attempt.json", "attempt ledger")
    try:
        attempt = V13FormalAttemptRecord.model_validate_json(raw)
    except ValidationError as error:
        raise FormalEvidenceIntegrityError("invalid attempt ledger") from error
    if path.name != f"attempt-{attempt.attempt_index:02d}" or path.parent.name != attempt.slot_id:
        raise FormalEvidenceIntegrityError("attempt path identity mismatch")
    return attempt, raw


def _freeze_attempt(attempt: V13FormalAttemptRecord, raw: bytes) -> V13FormalAttemptEvidence:
    return V13FormalAttemptEvidence(
        attempt_index=attempt.attempt_index,
        status=attempt.status,
        remediation=attempt.remediation,
        failure_category=attempt.failure_category,
        attempt_json_sha256=_sha256_bytes(raw),
        attempt_semantic_sha256=compute_v13_formal_attempt_sha256(attempt),
        canonical_run_id=attempt.canonical_run_id,
        agent_status=attempt.agent_status,
        evaluation_passed=attempt.evaluation_passed,
    )


def _freeze_run(
    attempt_dir: Path,
    *,
    run_id: str,
    slot,
    planned,
) -> V13FormalRunEvidence:
    artifacts = attempt_dir / "artifacts"
    try:
        names = tuple(path.name for path in artifacts.iterdir())
    except OSError as error:
        raise FormalEvidenceIntegrityError("unable to inspect canonical artifacts") from error
    run_names = tuple(name for name in names if name != "experiments")
    if run_names != (run_id,):
        raise FormalEvidenceIntegrityError("canonical attempt must contain exactly its Run")
    run_root = artifacts / run_id
    if run_root.is_symlink() or not run_root.is_dir():
        raise FormalEvidenceIntegrityError("canonical Run directory is unsafe")
    try:
        run = FilesystemArtifactStore(artifacts).load_run_record(run_id)
    except ArtifactStoreError as error:
        raise FormalEvidenceIntegrityError("invalid canonical Run") from error
    binding = run.agent.identity_binding
    if (run.run_id != run_id or run.task_id != slot.task_id
            or run.agent.status is not slot.canonical_agent_status
            or run.evaluation_passed != slot.canonical_evaluation_passed
            or binding is None
            or binding.manifest_sha256 != ACCEPTED_AGENT_MANIFEST_SHA256
            or binding.config_id != slot.config_id
            or binding.config_sha256 != planned.config_sha256
            or run.provenance is None
            or run.provenance.base_commit_used != planned.resolved_base_commit
            or run.provenance.task_fingerprint_sha256
            != planned.task_fingerprint_sha256):
        raise FormalEvidenceIntegrityError("canonical Run identity differs from slot")
    raw_hashes = {
        field: _sha256_bytes(_read_exact_file(run_root / filename, filename))
        for field, filename in _RAW_RUN_FILES.items()
    }
    return V13FormalRunEvidence(
        run_id=run.run_id,
        agent_status=run.agent.status,
        evaluation_passed=run.evaluation_passed,
        identity_binding=binding,
        run_semantic_sha256=compute_run_semantic_sha256(run),
        **raw_hashes,
    )


def build_formal_evidence_freeze(
    source_results: Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> V13FormalEvidenceFreeze:
    root = Path(project_root).resolve()
    supplied_source = Path(source_results)
    if supplied_source.is_symlink():
        raise FormalEvidenceIntegrityError("formal source namespace is symlinked")
    source = supplied_source.resolve()
    preregistration = verify_preregistration(root)
    ledger = check_formal_study(project_root=root, results_root=source)
    design = _load_design(root)
    if ledger.status is not FormalStudyStatus.COMPLETED:
        raise FormalEvidenceIntegrityError("formal source study is not completed")
    study_bytes = _read_exact_file(source / "study.json", "source study ledger")
    try:
        if V13FormalStudyLedger.model_validate_json(study_bytes) != ledger:
            raise FormalEvidenceIntegrityError("source study changed during verification")
    except ValidationError as error:
        raise FormalEvidenceIntegrityError("invalid source study ledger") from error
    if tuple((item.ordinal, item.slot_id, item.repetition_index, item.task_id, item.config_id)
             for item in ledger.slots) != tuple(
                 (item.ordinal, item.slot_id, item.repetition_index, item.task_id, item.config_id)
                 for item in preregistration.slots
             ):
        raise FormalEvidenceIntegrityError("source slots differ from preregistration")
    profiles = {item.task_id: item for item in design.tasks}
    if tuple(profiles) != preregistration.task_order:
        raise FormalEvidenceIntegrityError("M1 task order differs from preregistration")

    frozen_slots = []
    for slot, planned in zip(ledger.slots, preregistration.slots, strict=True):
        if slot.status not in {
                FormalSlotStatus.CANONICAL_OBSERVED,
                FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE,
        }:
            raise FormalEvidenceIntegrityError("completed study contains nonterminal slot")
        slot_dir = source / "slots" / slot.slot_id
        attempts = []
        loaded_attempts = {}
        for attempt_index in slot.attempts:
            attempt_dir = slot_dir / f"attempt-{attempt_index:02d}"
            attempt, attempt_bytes = _load_attempt(attempt_dir)
            if (attempt.slot_id != slot.slot_id
                    or attempt.attempt_index != attempt_index
                    or attempt.formal_preregistration_sha256
                    != ACCEPTED_PREREGISTRATION_SHA256
                    or attempt.config_id != slot.config_id
                    or attempt.task_id != slot.task_id):
                raise FormalEvidenceIntegrityError("attempt identity differs from slot")
            loaded_attempts[attempt_index] = (attempt, attempt_dir)
            attempts.append(_freeze_attempt(attempt, attempt_bytes))
        canonical_run = None
        if slot.status is FormalSlotStatus.CANONICAL_OBSERVED:
            if slot.canonical_attempt_index is None or slot.canonical_run_id is None:
                raise FormalEvidenceIntegrityError("canonical slot lacks Run linkage")
            attempt, attempt_dir = loaded_attempts[slot.canonical_attempt_index]
            if (attempt.status is not FormalAttemptStatus.CANONICAL_OBSERVED
                    or attempt.canonical_run_id != slot.canonical_run_id):
                raise FormalEvidenceIntegrityError("canonical attempt linkage mismatch")
            canonical_run = _freeze_run(
                attempt_dir, run_id=slot.canonical_run_id, slot=slot,
                planned=planned,
            )
        elif slot.canonical_attempt_index is not None or slot.canonical_run_id is not None:
            raise FormalEvidenceIntegrityError("unresolved slot contains canonical linkage")
        profile = profiles[slot.task_id]
        frozen_slots.append(V13FormalSlotEvidence(
            ordinal=slot.ordinal,
            slot_id=slot.slot_id,
            repetition_index=slot.repetition_index,
            task_id=slot.task_id,
            config_id=slot.config_id,
            primary_capability=profile.primary_capability,
            designed_difficulty=profile.designed_difficulty,
            source_slot_status=slot.status,
            attempts=tuple(attempts),
            canonical_attempt_index=slot.canonical_attempt_index,
            canonical_run=canonical_run,
        ))
    canonical_count = sum(
        slot.status is FormalSlotStatus.CANONICAL_OBSERVED for slot in ledger.slots
    )
    unresolved_count = sum(
        slot.status is FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE
        for slot in ledger.slots
    )
    return V13FormalEvidenceFreeze(
        freeze_id="patchbench-v1.3-formal-results",
        study_id=ledger.study_id,
        formal_preregistration_sha256=ACCEPTED_PREREGISTRATION_SHA256,
        design_sha256=ACCEPTED_DESIGN_SHA256,
        candidate_sha256=ACCEPTED_CANDIDATE_SHA256,
        agent_manifest_sha256=ACCEPTED_AGENT_MANIFEST_SHA256,
        execution_harness_commit=EXECUTION_HARNESS_COMMIT,
        source_study_status=ledger.status.value,
        source_study_json_sha256=_sha256_bytes(study_bytes),
        source_study_semantic_sha256=compute_v13_formal_study_sha256(ledger),
        planned_slot_count=preregistration.planned_slot_count,
        canonical_slot_count=canonical_count,
        unresolved_infrastructure_slot_count=unresolved_count,
        slots=tuple(frozen_slots),
    )


def deterministic_json(freeze: V13FormalEvidenceFreeze) -> str:
    return json.dumps(freeze.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def load_checked_freeze(project_root: Path = PROJECT_ROOT) -> V13FormalEvidenceFreeze:
    try:
        return V13FormalEvidenceFreeze.model_validate_json(
            _read_exact_file(Path(project_root) / FREEZE_PATH, "checked formal freeze")
        )
    except ValidationError as error:
        raise FormalEvidenceIntegrityError("invalid checked formal freeze") from error


def verify_checked_freeze(project_root: Path = PROJECT_ROOT) -> V13FormalEvidenceFreeze:
    root = Path(project_root).resolve()
    freeze = load_checked_freeze(root)
    raw = _read_exact_file(root / FREEZE_PATH, "checked formal freeze")
    if compute_v13_formal_evidence_freeze_sha256(freeze) != ACCEPTED_FORMAL_FREEZE_SHA256:
        raise FormalEvidenceIntegrityError("formal freeze semantic SHA mismatch")
    if _sha256_bytes(raw) != ACCEPTED_FORMAL_FREEZE_BYTE_SHA256:
        raise FormalEvidenceIntegrityError("formal freeze artifact byte SHA mismatch")
    preregistration = verify_preregistration(root)
    if (freeze.formal_preregistration_sha256 != ACCEPTED_PREREGISTRATION_SHA256
            or freeze.design_sha256 != ACCEPTED_DESIGN_SHA256
            or freeze.candidate_sha256 != ACCEPTED_CANDIDATE_SHA256
            or freeze.agent_manifest_sha256 != ACCEPTED_AGENT_MANIFEST_SHA256
            or freeze.execution_harness_commit != EXECUTION_HARNESS_COMMIT
            or freeze.study_id != preregistration.study_id):
        raise FormalEvidenceIntegrityError("formal freeze frozen-link mismatch")
    return freeze


def verify_source_against_checked_freeze(
    source_results: Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> V13FormalEvidenceFreeze:
    freeze = verify_checked_freeze(project_root)
    rebuilt = build_formal_evidence_freeze(source_results, project_root=project_root)
    if rebuilt != freeze:
        raise FormalEvidenceIntegrityError("formal source evidence differs from freeze")
    return freeze


def write_freeze(freeze: V13FormalEvidenceFreeze, project_root: Path) -> None:
    path = Path(project_root) / FREEZE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(deterministic_json(freeze))
    except FileExistsError as error:
        raise FormalEvidenceIntegrityError("checked formal freeze already exists") from error
    except OSError as error:
        raise FormalEvidenceIntegrityError("unable to write checked formal freeze") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--check-source", action="store_true")
    parser.add_argument("--source-results", type=Path, default=PROJECT_ROOT / DEFAULT_SOURCE)
    args = parser.parse_args()
    try:
        if args.write:
            freeze = build_formal_evidence_freeze(args.source_results)
            write_freeze(freeze, PROJECT_ROOT)
        elif args.check_source:
            freeze = verify_source_against_checked_freeze(args.source_results)
        else:
            freeze = verify_checked_freeze()
    except FormalEvidenceIntegrityError as error:
        raise SystemExit(f"Formal evidence integrity failure: {error}") from None
    print(f"formal_freeze_sha256={compute_v13_formal_evidence_freeze_sha256(freeze)}")


if __name__ == "__main__":
    main()
