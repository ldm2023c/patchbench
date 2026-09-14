"""Offline integrity and composition verification for Diagnosis validation suites."""

from collections import Counter
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import stat

from pydantic import ValidationError

from patchbench.application.diagnosis_validation import (
    DiagnosisValidationError,
    compute_diagnosis_gold_sha256,
    compute_subject_evidence_sha256,
    validate_semantic_gold_evidence,
)
from patchbench.application.diagnosis_evidence import _snapshot_hash
from patchbench.application.diagnosis_peer import (
    ContrastivePeerSelection, DiagnosisPeerError, verify_contrastive_peer_selection,
)
from patchbench.domain.diagnosis import (
    DiagnosisEvidenceBundle,
    DiagnosisMode,
    DiagnosisRoute,
    DiagnosisRoutingReason,
    EvidenceOwner,
    EvidenceKind,
    FailureFamily,
    route_run_diagnosis,
)
from patchbench.domain.diagnosis_integrity import canonical_json_bytes, compute_bundle_sha256
from patchbench.domain.diagnosis_suite import (
    DiagnosisValidationFreezeManifest,
    DiagnosisValidationSuite,
    DiagnosisValidationSuiteCase,
    compute_diagnosis_validation_suite_sha256,
)
from patchbench.domain.diagnosis_validation import DiagnosisGoldCase
from patchbench.domain.models import RunRecord, Sha256Hex
from patchbench.storage.filesystem import ArtifactStoreError, FilesystemArtifactStore


class DiagnosisSuiteReason(str, Enum):
    INVALID_ROOT = "invalid_root"
    INVALID_MANIFEST = "invalid_manifest"
    UNSAFE_FILE = "unsafe_file"
    MISSING_FILE = "missing_file"
    EXTRA_FILE = "extra_file"
    FILE_HASH_MISMATCH = "file_hash_mismatch"
    FILE_LENGTH_MISMATCH = "file_length_mismatch"
    INVALID_JSON = "invalid_json"
    SUITE_HASH_MISMATCH = "suite_hash_mismatch"
    CASE_FILE_HASH_MISMATCH = "case_file_hash_mismatch"
    CASE_ID_MISMATCH = "case_id_mismatch"
    INVALID_CASE = "invalid_case"
    INVALID_COMPOSITION = "invalid_composition"


class DiagnosisSuiteError(ValueError):
    def __init__(self, reason: DiagnosisSuiteReason, detail: str):
        self.reason = reason
        super().__init__(f"{reason.value}: {detail}")


def _sha256(data: bytes) -> Sha256Hex:
    return hashlib.sha256(data).hexdigest()


def compute_run_record_sha256(run: RunRecord) -> Sha256Hex:
    return _sha256(canonical_json_bytes(run.model_dump(mode="json")))


def verify_semantic_validation_case(
    case: DiagnosisValidationSuiteCase,
    gold: DiagnosisGoldCase,
    blind_bundle: DiagnosisEvidenceBundle,
    contrastive_bundle: DiagnosisEvidenceBundle | None = None,
    *,
    peer_selection: ContrastivePeerSelection | None = None,
    peer_artifact_store: FilesystemArtifactStore | None = None,
) -> None:
    """Verify all final semantic identity, outcome and grounding boundaries."""
    try:
        if case.expected_route is not DiagnosisRoute.SEMANTIC_DIAGNOSIS:
            raise ValueError("case is not semantic")
        if gold.case_id != case.case_id or gold.expected_route is not DiagnosisRoute.SEMANTIC_DIAGNOSIS:
            raise ValueError("gold case identity or route differs")
        if compute_diagnosis_gold_sha256(gold) != case.gold_sha256:
            raise ValueError("complete Human Gold hash differs")
        if blind_bundle.mode is not DiagnosisMode.BLIND:
            raise ValueError("authoritative subject bundle must be Blind")
        if (compute_bundle_sha256(blind_bundle) != blind_bundle.bundle_sha256
                or blind_bundle.bundle_sha256 != case.blind_bundle_sha256):
            raise ValueError("Blind Bundle hash differs")
        if blind_bundle.official_evaluation_passed:
            raise ValueError("semantic subject must have official FAIL")
        if blind_bundle.agent_status.value != "completed":
            raise ValueError("semantic subject Agent status must be COMPLETED")
        if any(item.owner is EvidenceOwner.PEER for item in blind_bundle.evidence_items):
            raise ValueError("Blind Bundle cannot contain peer evidence")
        subject_sha = compute_subject_evidence_sha256(blind_bundle)
        if subject_sha != case.subject_evidence_sha256 or subject_sha != gold.subject_evidence_sha256:
            raise ValueError("subject evidence identities differ")
        validate_semantic_gold_evidence(blind_bundle, gold)
        if contrastive_bundle is not None:
            if peer_selection is None or peer_artifact_store is None:
                raise ValueError("Contrastive verification requires frozen D5 selection and support")
            if contrastive_bundle.mode is not DiagnosisMode.CONTRASTIVE:
                raise ValueError("declared Contrastive Bundle has wrong mode")
            if (compute_bundle_sha256(contrastive_bundle) != contrastive_bundle.bundle_sha256
                    or contrastive_bundle.bundle_sha256 != case.contrastive_bundle_sha256):
                raise ValueError("Contrastive Bundle hash differs")
            if compute_subject_evidence_sha256(contrastive_bundle) != subject_sha:
                raise ValueError("Contrastive subject evidence differs from Blind")
            verified_subject, verified_peer = verify_contrastive_peer_selection(
                peer_selection, artifact_store=peer_artifact_store)
            peer_provenance = contrastive_bundle.provenance.peer
            if peer_provenance is None:
                raise ValueError("Contrastive Bundle lacks peer provenance")
            if (verified_subject.run_id != blind_bundle.subject_run_id
                    or peer_selection.subject_run_id != blind_bundle.subject_run_id
                    or contrastive_bundle.subject_run_id != peer_selection.subject_run_id
                    or verified_peer.run_id != peer_selection.peer_run_id
                    or contrastive_bundle.peer_run_id != peer_selection.peer_run_id
                    or peer_provenance.peer_run_id != peer_selection.peer_run_id
                    or peer_provenance.peer_experiment_id != peer_selection.peer_experiment_id
                    or peer_provenance.peer_run_index != peer_selection.peer_run_index):
                raise ValueError("Contrastive provenance differs from verified D5 selection")
            subject_provenance = blind_bundle.provenance.subject
            if (verified_subject.provenance is None
                    or verified_subject.patch_summary is None
                    or verified_subject.evaluation_evidence is None
                    or verified_subject.task_id != blind_bundle.task_id
                    or verified_subject.provenance.base_commit_used != blind_bundle.base_commit
                    or verified_subject.provenance.task_fingerprint_sha256
                    != blind_bundle.task_fingerprint_sha256
                    or verified_subject.patch_summary.patch_sha256
                    != subject_provenance.canonical_patch_sha256
                    or verified_subject.evaluation_evidence.test_log_sha256
                    != subject_provenance.evaluation_log_sha256):
                raise ValueError("verified D5 subject differs from Blind provenance")
            patch = peer_artifact_store.load_run_patch(verified_peer.run_id)
            log = peer_artifact_store.load_run_test_log(verified_peer.run_id)
            patch_sha, log_sha = _sha256(patch.encode("utf-8")), _sha256(log.encode("utf-8"))
            if (verified_peer.patch_summary is None or verified_peer.evaluation_evidence is None
                    or verified_peer.patch_summary.patch_sha256 != patch_sha
                    or verified_peer.evaluation_evidence.test_log_sha256 != log_sha
                    or peer_provenance.peer_patch_sha256 != patch_sha
                    or peer_provenance.peer_evaluation_log_sha256 != log_sha):
                raise ValueError("peer raw evidence differs from Run and Contrastive provenance")
            peer_patch = [item for item in contrastive_bundle.evidence_items
                          if item.kind is EvidenceKind.PEER_PATCH]
            peer_logs = [item for item in contrastive_bundle.evidence_items
                         if item.kind is EvidenceKind.PEER_EVALUATION]
            peer_sources = [item for item in contrastive_bundle.evidence_items
                            if item.kind is EvidenceKind.PEER_SOURCE]
            if (len(peer_patch) != 1 or len(peer_logs) != 1
                    or peer_patch[0].content != patch or peer_logs[0].content != log
                    or peer_patch[0].owner is not EvidenceOwner.PEER
                    or peer_logs[0].owner is not EvidenceOwner.PEER
                    or peer_patch[0].artifact_sha256 != patch_sha
                    or peer_logs[0].artifact_sha256 != log_sha
                    or len({item.path for item in peer_sources}) != len(peer_sources)
                    or any(item.owner is not EvidenceOwner.PEER
                           or item.path is None
                           or item.artifact_sha256 != _sha256(item.content.encode("utf-8"))
                           for item in peer_sources)
                    or _snapshot_hash({item.path: item.content.encode("utf-8")
                                       for item in peer_sources})
                    != peer_provenance.peer_candidate_snapshot_sha256):
                raise ValueError("Contrastive peer evidence differs from frozen support")
    except (ValueError, DiagnosisValidationError, DiagnosisPeerError,
            ArtifactStoreError) as error:
        raise DiagnosisSuiteError(DiagnosisSuiteReason.INVALID_CASE, str(error)) from error


_V1_FAMILIES = {
    FailureFamily.INCORRECT_LOCAL_LOGIC,
    FailureFamily.INCOMPLETE_CROSS_FILE_REPAIR,
    FailureFamily.PARTIAL_CONTRACT_HANDLING,
    FailureFamily.STATE_CONSISTENCY_VIOLATION,
    FailureFamily.REGRESSION_INTRODUCED,
}


def verify_diagnosis_validation_v1_composition(
    cases: list[DiagnosisValidationSuiteCase],
    gold_by_case: dict[str, DiagnosisGoldCase],
) -> None:
    """Enforce the exact accepted 15-case V1 composition from typed Gold."""
    try:
        if len(cases) != 15 or len({case.case_id for case in cases}) != 15:
            raise ValueError("V1 requires exactly 15 unique cases")
        if set(gold_by_case) != {case.case_id for case in cases}:
            raise ValueError("Gold case set must exactly equal suite case set")
        semantic = [case for case in cases if case.expected_route is DiagnosisRoute.SEMANTIC_DIAGNOSIS]
        operational = [case for case in cases if case.expected_route is DiagnosisRoute.OPERATIONAL_ONLY]
        if len(semantic) != 13 or len(operational) != 2:
            raise ValueError("V1 requires 13 semantic and 2 operational cases")

        preferred = Counter()
        abstention_count = 0
        for case in cases:
            gold = gold_by_case[case.case_id]
            if gold.case_id != case.case_id or compute_diagnosis_gold_sha256(gold) != case.gold_sha256:
                raise ValueError("case and complete Human Gold identity must agree")
            if gold.expected_route is not case.expected_route:
                raise ValueError("case and Gold route must agree")
            if case.expected_route is DiagnosisRoute.SEMANTIC_DIAGNOSIS:
                if gold.semantic_gold is None:
                    raise ValueError("semantic case requires semantic Gold")
                if gold.semantic_gold.should_abstain:
                    abstention_count += 1
                else:
                    family = gold.semantic_gold.preferred_family
                    if family not in _V1_FAMILIES:
                        raise ValueError("V1 preferred family is outside the five accepted families")
                    preferred[family] += 1
        if abstention_count != 3 or preferred != Counter({family: 2 for family in _V1_FAMILIES}):
            raise ValueError("V1 semantic Gold requires three abstentions and two of each family")
        reasons = Counter(case.expected_routing_reason for case in operational)
        if reasons != Counter({DiagnosisRoutingReason.AGENT_COMMAND_FAILED: 1,
                               DiagnosisRoutingReason.AGENT_TIMED_OUT: 1}):
            raise ValueError("V1 operational cases require one command failure and one timeout")
    except ValueError as error:
        raise DiagnosisSuiteError(DiagnosisSuiteReason.INVALID_COMPOSITION, str(error)) from error


def _read_tree(root: Path) -> dict[str, bytes]:
    try:
        root_stat = root.lstat()
    except OSError as error:
        raise DiagnosisSuiteError(DiagnosisSuiteReason.INVALID_ROOT, str(error)) from error
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise DiagnosisSuiteError(DiagnosisSuiteReason.INVALID_ROOT,
                                  "suite root must be a real directory")
    result: dict[str, bytes] = {}
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in [*directories, *files]:
            path = current_path / name
            try:
                mode = path.lstat().st_mode
            except OSError as error:
                raise DiagnosisSuiteError(DiagnosisSuiteReason.UNSAFE_FILE, str(error)) from error
            if stat.S_ISLNK(mode):
                raise DiagnosisSuiteError(DiagnosisSuiteReason.UNSAFE_FILE,
                                          f"symlink is forbidden: {path.relative_to(root)}")
            if name in files and not stat.S_ISREG(mode):
                raise DiagnosisSuiteError(DiagnosisSuiteReason.UNSAFE_FILE,
                                          f"non-regular file is forbidden: {path.relative_to(root)}")
        for name in files:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            try:
                result[relative] = path.read_bytes()
            except OSError as error:
                raise DiagnosisSuiteError(DiagnosisSuiteReason.UNSAFE_FILE, str(error)) from error
    return result


def _parse(model, data: bytes, label: str):
    try:
        data.decode("utf-8")
        return model.model_validate_json(data)
    except (UnicodeError, ValidationError, json.JSONDecodeError) as error:
        raise DiagnosisSuiteError(DiagnosisSuiteReason.INVALID_JSON,
                                  f"invalid {label}: {error}") from error


def _required_file(files: dict[str, bytes], path: str) -> bytes:
    try:
        return files[path]
    except KeyError as error:
        raise DiagnosisSuiteError(DiagnosisSuiteReason.MISSING_FILE, path) from error


def verify_diagnosis_validation_suite(
    root: Path, *, enforce_v1_composition: bool = True,
) -> DiagnosisValidationSuite:
    """Verify an immutable suite tree without following filesystem redirects."""
    files = _read_tree(root)
    manifest_bytes = files.pop("freeze-manifest.json", None)
    if manifest_bytes is None:
        raise DiagnosisSuiteError(DiagnosisSuiteReason.MISSING_FILE,
                                  "freeze-manifest.json is missing")
    manifest = _parse(DiagnosisValidationFreezeManifest, manifest_bytes, "freeze manifest")
    expected = {item.path for item in manifest.files}
    actual = set(files)
    missing, extra = sorted(expected - actual), sorted(actual - expected)
    if missing:
        raise DiagnosisSuiteError(DiagnosisSuiteReason.MISSING_FILE, repr(missing))
    if extra:
        raise DiagnosisSuiteError(DiagnosisSuiteReason.EXTRA_FILE, repr(extra))
    for item in manifest.files:
        data = files[item.path]
        if len(data) != item.byte_length:
            raise DiagnosisSuiteError(DiagnosisSuiteReason.FILE_LENGTH_MISMATCH, item.path)
        if _sha256(data) != item.sha256:
            raise DiagnosisSuiteError(DiagnosisSuiteReason.FILE_HASH_MISMATCH, item.path)

    suite = _parse(DiagnosisValidationSuite, _required_file(files, manifest.suite_path), "suite")
    if compute_diagnosis_validation_suite_sha256(suite) != manifest.suite_sha256:
        raise DiagnosisSuiteError(DiagnosisSuiteReason.SUITE_HASH_MISMATCH, manifest.suite_path)

    cases: list[DiagnosisValidationSuiteCase] = []
    gold_by_case: dict[str, DiagnosisGoldCase] = {}
    for reference in suite.case_files:
        raw = files.get(reference.path)
        if raw is None:
            raise DiagnosisSuiteError(DiagnosisSuiteReason.MISSING_FILE, reference.path)
        if _sha256(raw) != reference.sha256:
            raise DiagnosisSuiteError(DiagnosisSuiteReason.CASE_FILE_HASH_MISMATCH, reference.path)
        case = _parse(DiagnosisValidationSuiteCase, raw, "suite case")
        if case.case_id != reference.case_id:
            raise DiagnosisSuiteError(DiagnosisSuiteReason.CASE_ID_MISMATCH, reference.path)
        gold = _parse(DiagnosisGoldCase, _required_file(files, case.gold_path), "Human Gold")
        if gold.case_id != case.case_id:
            raise DiagnosisSuiteError(DiagnosisSuiteReason.CASE_ID_MISMATCH, case.gold_path)
        cases.append(case)
        gold_by_case[case.case_id] = gold
        if case.expected_route is DiagnosisRoute.SEMANTIC_DIAGNOSIS:
            blind = _parse(DiagnosisEvidenceBundle,
                           _required_file(files, case.blind_bundle_path), "Blind Bundle")
            contrastive = _parse(DiagnosisEvidenceBundle,
                                 _required_file(files, case.contrastive_bundle_path),
                                 "Contrastive Bundle")
            selection_raw = _required_file(files, case.peer_selection_path)
            if _sha256(selection_raw) != case.peer_selection_sha256:
                raise DiagnosisSuiteError(DiagnosisSuiteReason.INVALID_CASE,
                                          "peer selection raw hash differs")
            selection = _parse(ContrastivePeerSelection, selection_raw, "peer selection")
            support_root = root / case.peer_artifact_store_path
            try:
                support_mode = support_root.lstat().st_mode
            except OSError as error:
                raise DiagnosisSuiteError(DiagnosisSuiteReason.MISSING_FILE,
                                          case.peer_artifact_store_path) from error
            if not stat.S_ISDIR(support_mode) or stat.S_ISLNK(support_mode):
                raise DiagnosisSuiteError(DiagnosisSuiteReason.UNSAFE_FILE,
                                          case.peer_artifact_store_path)
            verify_semantic_validation_case(case, gold, blind, contrastive,
                peer_selection=selection,
                peer_artifact_store=FilesystemArtifactStore(support_root))
        else:
            run = _parse(RunRecord, _required_file(files, case.run_record_path), "Run record")
            decision = route_run_diagnosis(run)
            if (compute_diagnosis_gold_sha256(gold) != case.gold_sha256
                    or compute_run_record_sha256(run) != case.run_record_sha256
                    or decision.route is not case.expected_route
                    or decision.reason is not case.expected_routing_reason):
                raise DiagnosisSuiteError(DiagnosisSuiteReason.INVALID_CASE,
                                          f"operational linkage differs for {case.case_id}")
    if len({case.case_id for case in cases}) != len(cases):
        raise DiagnosisSuiteError(DiagnosisSuiteReason.CASE_ID_MISMATCH,
                                  "loaded case IDs must be unique")
    if enforce_v1_composition:
        verify_diagnosis_validation_v1_composition(cases, gold_by_case)
    return suite
