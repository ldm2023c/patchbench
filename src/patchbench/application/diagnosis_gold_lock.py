"""Build and verify the deterministic pre-Contrastive Diagnosis Gold lock."""

from collections import Counter
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

from pydantic import ValidationError

from patchbench.agents.base import AgentRunStatus
from patchbench.application.diagnosis_validation import (
    DiagnosisValidationError,
    compute_diagnosis_gold_sha256,
    compute_subject_evidence_sha256,
    validate_semantic_gold_evidence,
)
from patchbench.domain.diagnosis import (
    DiagnosisEvidenceBundle, DiagnosisMode, DiagnosisRoute, DiagnosisRoutingReason,
    EvidenceOwner, FailureFamily, route_run_diagnosis,
)
from patchbench.domain.diagnosis_gold_lock import (
    DiagnosisGoldLockCase, DiagnosisGoldLockManifest, DiagnosisGoldLockSuite,
    compute_diagnosis_gold_lock_suite_sha256,
)
from patchbench.domain.diagnosis_integrity import canonical_json_bytes, compute_bundle_sha256
from patchbench.domain.diagnosis_suite import FrozenValidationFile
from patchbench.domain.diagnosis_validation import DiagnosisGoldCase
from patchbench.domain.models import RunRecord, Sha256Hex


SUITE_ID = "diagnosis-validation-v1"
SELECTED_CASE_IDS = (
    "semantic-01", "semantic-02", "semantic-05", "semantic-06",
    "semantic-07", "semantic-08", "semantic-09", "semantic-11",
    "semantic-16", "semantic-17", "semantic-22", "semantic-24",
    "semantic-25", "operational-01", "operational-02",
)
SEMANTIC_CASE_IDS = SELECTED_CASE_IDS[:13]
OPERATIONAL_CASE_IDS = SELECTED_CASE_IDS[13:]
_V1_FAMILIES = {
    FailureFamily.INCORRECT_LOCAL_LOGIC,
    FailureFamily.INCOMPLETE_CROSS_FILE_REPAIR,
    FailureFamily.PARTIAL_CONTRACT_HANDLING,
    FailureFamily.STATE_CONSISTENCY_VIOLATION,
    FailureFamily.REGRESSION_INTRODUCED,
}


class DiagnosisGoldLockReason(str, Enum):
    INVALID_INPUT = "invalid_input"
    INVALID_JSON = "invalid_json"
    INVALID_CASE = "invalid_case"
    INVALID_COMPOSITION = "invalid_composition"
    AUTHORING_RECORD_MISMATCH = "authoring_record_mismatch"
    UNSAFE_FILE = "unsafe_file"
    MISSING_FILE = "missing_file"
    EXTRA_FILE = "extra_file"
    FILE_HASH_MISMATCH = "file_hash_mismatch"
    FILE_LENGTH_MISMATCH = "file_length_mismatch"
    SUITE_HASH_MISMATCH = "suite_hash_mismatch"


class DiagnosisGoldLockError(ValueError):
    def __init__(self, reason: DiagnosisGoldLockReason, detail: str):
        self.reason = reason
        super().__init__(f"{reason.value}: {detail}")


def _sha256(data: bytes) -> Sha256Hex:
    return hashlib.sha256(data).hexdigest()


def _disk_json_bytes(value) -> bytes:
    raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _parse(model, data: bytes, label: str):
    try:
        data.decode("utf-8")
        return model.model_validate_json(data)
    except (UnicodeError, ValidationError, json.JSONDecodeError) as error:
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_JSON, f"invalid {label}: {error}") from error


def _read_regular_file(path: Path) -> bytes:
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise DiagnosisGoldLockError(
                DiagnosisGoldLockReason.UNSAFE_FILE, f"not a regular file: {path}")
        return path.read_bytes()
    except DiagnosisGoldLockError:
        raise
    except FileNotFoundError as error:
        raise DiagnosisGoldLockError(DiagnosisGoldLockReason.MISSING_FILE, str(path)) from error
    except OSError as error:
        raise DiagnosisGoldLockError(DiagnosisGoldLockReason.UNSAFE_FILE, str(error)) from error


def _read_tree(root: Path) -> dict[str, bytes]:
    try:
        mode = root.lstat().st_mode
    except OSError as error:
        raise DiagnosisGoldLockError(DiagnosisGoldLockReason.INVALID_INPUT, str(error)) from error
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_INPUT, "Gold lock root must be a real directory")
    result = {}
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in [*directories, *files]:
            path = current_path / name
            try:
                child_mode = path.lstat().st_mode
            except OSError as error:
                raise DiagnosisGoldLockError(
                    DiagnosisGoldLockReason.UNSAFE_FILE, str(error)) from error
            if stat.S_ISLNK(child_mode):
                raise DiagnosisGoldLockError(
                    DiagnosisGoldLockReason.UNSAFE_FILE,
                    f"symlink is forbidden: {path.relative_to(root)}")
            if name in files and not stat.S_ISREG(child_mode):
                raise DiagnosisGoldLockError(
                    DiagnosisGoldLockReason.UNSAFE_FILE,
                    f"non-regular file is forbidden: {path.relative_to(root)}")
        for name in files:
            path = current_path / name
            result[path.relative_to(root).as_posix()] = _read_regular_file(path)
    return result


def _required(files: dict[str, bytes], path: str | None) -> bytes:
    if path is None or path not in files:
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.MISSING_FILE, repr(path))
    return files[path]


def _authoring_record_hashes(data: bytes) -> dict[str, Sha256Hex]:
    try:
        text = data.decode("utf-8")
    except UnicodeError as error:
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.AUTHORING_RECORD_MISMATCH,
            "authoring record is not UTF-8") from error
    hashes = {}
    for line in text.splitlines():
        if not line.startswith("| semantic-"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        candidates = [cell for cell in cells if len(cell) == 64
                      and all(char in "0123456789abcdef" for char in cell)]
        if not candidates:
            continue
        if not cells or len(candidates) != 1 or cells[0] in hashes:
            raise DiagnosisGoldLockError(
                DiagnosisGoldLockReason.AUTHORING_RECORD_MISMATCH,
                "authoring record contains an ambiguous semantic hash row")
        hashes[cells[0]] = candidates[0]
    return hashes


def _validate_semantic_case(
    case: DiagnosisGoldLockCase,
    gold: DiagnosisGoldCase,
    bundle: DiagnosisEvidenceBundle,
) -> None:
    try:
        if (case.expected_route is not DiagnosisRoute.SEMANTIC_DIAGNOSIS
                or gold.case_id != case.case_id
                or gold.expected_route is not DiagnosisRoute.SEMANTIC_DIAGNOSIS
                or bundle.mode is not DiagnosisMode.BLIND
                or bundle.official_evaluation_passed
                or bundle.agent_status is not AgentRunStatus.COMPLETED
                or any(item.owner is EvidenceOwner.PEER for item in bundle.evidence_items)):
            raise ValueError("semantic case violates the Blind FAIL route boundary")
        if (compute_bundle_sha256(bundle) != bundle.bundle_sha256
                or bundle.bundle_sha256 != case.blind_bundle_sha256):
            raise ValueError("Blind Bundle identity differs")
        subject_sha = compute_subject_evidence_sha256(bundle)
        if (subject_sha != case.subject_evidence_sha256
                or subject_sha != gold.subject_evidence_sha256):
            raise ValueError("subject evidence identity differs")
        if compute_diagnosis_gold_sha256(gold) != case.gold_sha256:
            raise ValueError("complete Human Gold identity differs")
        validate_semantic_gold_evidence(bundle, gold)
    except (ValueError, DiagnosisValidationError) as error:
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_CASE, f"{case.case_id}: {error}") from error


def _validate_operational_case(
    case: DiagnosisGoldLockCase, gold: DiagnosisGoldCase, run: RunRecord,
) -> None:
    decision = route_run_diagnosis(run)
    run_sha = _sha256(canonical_json_bytes(run.model_dump(mode="json")))
    if (case.expected_route is not DiagnosisRoute.OPERATIONAL_ONLY
            or gold.case_id != case.case_id
            or gold.expected_route is not DiagnosisRoute.OPERATIONAL_ONLY
            or compute_diagnosis_gold_sha256(gold) != case.route_gold_sha256
            or run_sha != case.run_record_sha256
            or decision.route is not case.expected_route
            or decision.reason is not case.expected_routing_reason):
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_CASE,
            f"{case.case_id}: operational route linkage differs")


def _validate_composition(
    suite: DiagnosisGoldLockSuite, gold_by_case: dict[str, DiagnosisGoldCase],
) -> None:
    if tuple(case.case_id for case in suite.cases) != SELECTED_CASE_IDS:
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_COMPOSITION,
            "selected case IDs or canonical order differ")
    semantic = [case for case in suite.cases
                if case.expected_route is DiagnosisRoute.SEMANTIC_DIAGNOSIS]
    operational = [case for case in suite.cases
                   if case.expected_route is DiagnosisRoute.OPERATIONAL_ONLY]
    preferred = Counter()
    abstentions = 0
    for case in semantic:
        gold = gold_by_case[case.case_id]
        if gold.semantic_gold is None:
            raise DiagnosisGoldLockError(
                DiagnosisGoldLockReason.INVALID_COMPOSITION, "semantic Gold is absent")
        if gold.semantic_gold.should_abstain:
            abstentions += 1
        else:
            preferred[gold.semantic_gold.preferred_family] += 1
    reasons = Counter(case.expected_routing_reason for case in operational)
    if (len(semantic) != 13 or len(operational) != 2 or abstentions != 3
            or preferred != Counter({family: 2 for family in _V1_FAMILIES})
            or reasons != Counter({DiagnosisRoutingReason.AGENT_COMMAND_FAILED: 1,
                                   DiagnosisRoutingReason.AGENT_TIMED_OUT: 1})):
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_COMPOSITION,
            "Gold-derived semantic or operational composition differs")
    if len({case.subject_evidence_sha256 for case in semantic}) != 13:
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_COMPOSITION,
            "selected semantic subject identities are not unique")


def _semantic_source(
    candidate_root: Path, gold_root: Path, case_id: str,
) -> tuple[DiagnosisGoldLockCase, DiagnosisGoldCase, dict[str, bytes]]:
    case_root = candidate_root / case_id
    try:
        names = {path.name for path in case_root.iterdir()}
    except OSError as error:
        raise DiagnosisGoldLockError(DiagnosisGoldLockReason.INVALID_INPUT, str(error)) from error
    if names != {"base", "blind-bundle.json", "candidate.json", "task.yaml"}:
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_INPUT,
            f"{case_id}: human-facing candidate packet differs")
    candidate_raw = _read_regular_file(case_root / "candidate.json")
    bundle_raw = _read_regular_file(case_root / "blind-bundle.json")
    gold_raw = _read_regular_file(gold_root / case_id / "gold.json")
    try:
        candidate = json.loads(candidate_raw)
    except json.JSONDecodeError as error:
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_JSON, f"{case_id}: invalid candidate metadata") from error
    expected_keys = {"schema_version", "candidate_id", "expected_route", "subject_run_id",
                     "blind_bundle_sha256", "subject_evidence_sha256"}
    if (set(candidate) != expected_keys or candidate["schema_version"] != 1
            or candidate["candidate_id"] != case_id
            or candidate["expected_route"] != DiagnosisRoute.SEMANTIC_DIAGNOSIS.value):
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_CASE, f"{case_id}: candidate metadata differs")
    bundle = _parse(DiagnosisEvidenceBundle, bundle_raw, f"{case_id} Blind Bundle")
    gold = _parse(DiagnosisGoldCase, gold_raw, f"{case_id} Human Gold")
    case = DiagnosisGoldLockCase(
        case_id=case_id,
        expected_route=DiagnosisRoute.SEMANTIC_DIAGNOSIS,
        blind_bundle_path=f"cases/{case_id}/blind-bundle.json",
        gold_path=f"cases/{case_id}/gold.json",
        subject_evidence_sha256=candidate["subject_evidence_sha256"],
        blind_bundle_sha256=candidate["blind_bundle_sha256"],
        gold_sha256=compute_diagnosis_gold_sha256(gold),
    )
    if bundle.subject_run_id != candidate["subject_run_id"]:
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_CASE, f"{case_id}: subject Run linkage differs")
    _validate_semantic_case(case, gold, bundle)
    return case, gold, {case.blind_bundle_path: bundle_raw, case.gold_path: gold_raw}


def _operational_source(
    candidate_root: Path, case_id: str,
) -> tuple[DiagnosisGoldLockCase, DiagnosisGoldCase, dict[str, bytes]]:
    case_root = candidate_root / case_id
    candidate_raw = _read_regular_file(case_root / "candidate.json")
    run_raw = _read_regular_file(case_root / "run-record.json")
    gold_raw = _read_regular_file(case_root / "route-gold.json")
    try:
        candidate = json.loads(candidate_raw)
    except json.JSONDecodeError as error:
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_JSON, f"{case_id}: invalid candidate metadata") from error
    run = _parse(RunRecord, run_raw, f"{case_id} RunRecord")
    gold = _parse(DiagnosisGoldCase, gold_raw, f"{case_id} route Gold")
    decision = route_run_diagnosis(run)
    expected_keys = {"schema_version", "candidate_id", "expected_route",
                     "expected_routing_reason", "run_id"}
    if (set(candidate) != expected_keys or candidate.get("schema_version") != 1
            or candidate.get("candidate_id") != case_id
            or candidate.get("expected_route") != DiagnosisRoute.OPERATIONAL_ONLY.value
            or candidate.get("expected_routing_reason") != decision.reason.value
            or candidate.get("run_id") != run.run_id):
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_CASE, f"{case_id}: operational metadata differs")
    case = DiagnosisGoldLockCase(
        case_id=case_id,
        expected_route=DiagnosisRoute.OPERATIONAL_ONLY,
        run_record_path=f"cases/{case_id}/run-record.json",
        run_record_sha256=_sha256(canonical_json_bytes(run.model_dump(mode="json"))),
        route_gold_path=f"cases/{case_id}/route-gold.json",
        route_gold_sha256=compute_diagnosis_gold_sha256(gold),
        expected_routing_reason=decision.reason,
    )
    _validate_operational_case(case, gold, run)
    return case, gold, {case.run_record_path: run_raw, case.route_gold_path: gold_raw}


def build_diagnosis_gold_lock(
    candidate_root: Path,
    gold_root: Path,
    authoring_record_path: Path,
    output_root: Path,
) -> DiagnosisGoldLockSuite:
    """Copy exact selected artifacts and write the pre-Contrastive lock metadata."""
    candidate_root, gold_root = Path(candidate_root), Path(gold_root)
    cases, gold_by_case, artifacts = [], {}, {}
    for case_id in SEMANTIC_CASE_IDS:
        case, gold, files = _semantic_source(candidate_root, gold_root, case_id)
        cases.append(case)
        gold_by_case[case_id] = gold
        artifacts.update(files)
    for case_id in OPERATIONAL_CASE_IDS:
        case, gold, files = _operational_source(candidate_root, case_id)
        cases.append(case)
        gold_by_case[case_id] = gold
        artifacts.update(files)
    suite = DiagnosisGoldLockSuite(cases=cases)
    _validate_composition(suite, gold_by_case)

    recorded = _authoring_record_hashes(_read_regular_file(authoring_record_path))
    for case in cases[:13]:
        if recorded.get(case.case_id) != case.gold_sha256:
            raise DiagnosisGoldLockError(
                DiagnosisGoldLockReason.AUTHORING_RECORD_MISMATCH,
                f"{case.case_id}: recorded Gold hash differs")

    output_root = Path(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_INPUT, "output root must not exist")
    try:
        output_root.mkdir(parents=True)
        for relative, data in artifacts.items():
            path = output_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        suite_bytes = _disk_json_bytes(suite)
        (output_root / "suite.json").write_bytes(suite_bytes)
        locked_files = {"suite.json": suite_bytes, **artifacts}
        manifest = DiagnosisGoldLockManifest(
            suite_sha256=compute_diagnosis_gold_lock_suite_sha256(suite),
            selected_case_ids=list(SELECTED_CASE_IDS),
            files=[FrozenValidationFile(path=path, sha256=_sha256(data), byte_length=len(data))
                   for path, data in sorted(locked_files.items())],
        )
        (output_root / "gold-lock-manifest.json").write_bytes(_disk_json_bytes(manifest))
        verify_diagnosis_gold_lock(output_root)
    except Exception:
        shutil.rmtree(output_root, ignore_errors=True)
        raise
    return suite


def verify_diagnosis_gold_lock(root: Path) -> DiagnosisGoldLockSuite:
    """Verify the closed pre-Contrastive tree without filesystem redirects."""
    files = _read_tree(Path(root))
    manifest_raw = files.pop("gold-lock-manifest.json", None)
    if manifest_raw is None:
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.MISSING_FILE, "gold-lock-manifest.json")
    manifest = _parse(DiagnosisGoldLockManifest, manifest_raw, "Gold lock manifest")
    expected, actual = {item.path for item in manifest.files}, set(files)
    if expected - actual:
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.MISSING_FILE, repr(sorted(expected - actual)))
    if actual - expected:
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.EXTRA_FILE, repr(sorted(actual - expected)))
    for item in manifest.files:
        data = files[item.path]
        if len(data) != item.byte_length:
            raise DiagnosisGoldLockError(
                DiagnosisGoldLockReason.FILE_LENGTH_MISMATCH, item.path)
        if _sha256(data) != item.sha256:
            raise DiagnosisGoldLockError(
                DiagnosisGoldLockReason.FILE_HASH_MISMATCH, item.path)
    suite_raw = files.get("suite.json")
    if suite_raw is None:
        raise DiagnosisGoldLockError(DiagnosisGoldLockReason.MISSING_FILE, "suite.json")
    suite = _parse(DiagnosisGoldLockSuite, suite_raw, "Gold lock suite")
    if compute_diagnosis_gold_lock_suite_sha256(suite) != manifest.suite_sha256:
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.SUITE_HASH_MISMATCH, "suite.json")
    if manifest.selected_case_ids != list(SELECTED_CASE_IDS):
        raise DiagnosisGoldLockError(
            DiagnosisGoldLockReason.INVALID_COMPOSITION, "manifest selection differs")
    expected_directories = {"cases", *(f"cases/{case_id}" for case_id in SELECTED_CASE_IDS)}
    actual_directories = {
        path.relative_to(root).as_posix()
        for path in Path(root).rglob("*") if path.is_dir()
    }
    if actual_directories != expected_directories:
        missing = sorted(expected_directories - actual_directories)
        extra = sorted(actual_directories - expected_directories)
        reason = (DiagnosisGoldLockReason.MISSING_FILE if missing
                  else DiagnosisGoldLockReason.EXTRA_FILE)
        raise DiagnosisGoldLockError(reason, repr(missing or extra))

    gold_by_case = {}
    for case in suite.cases:
        if case.expected_route is DiagnosisRoute.SEMANTIC_DIAGNOSIS:
            bundle = _parse(DiagnosisEvidenceBundle,
                            _required(files, case.blind_bundle_path), "Blind Bundle")
            gold = _parse(DiagnosisGoldCase,
                          _required(files, case.gold_path), "Human Gold")
            _validate_semantic_case(case, gold, bundle)
        else:
            run = _parse(RunRecord, _required(files, case.run_record_path), "RunRecord")
            gold = _parse(DiagnosisGoldCase,
                          _required(files, case.route_gold_path), "route Gold")
            _validate_operational_case(case, gold, run)
        gold_by_case[case.case_id] = gold
    _validate_composition(suite, gold_by_case)
    return suite
