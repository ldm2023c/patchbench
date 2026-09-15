"""Offline integrity and composition verification for Diagnosis validation suites."""

from collections import Counter
from contextlib import contextmanager
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from patchbench.application.diagnosis_contrastive import (
    ContrastiveCompilationError,
    compile_contrastive_diagnosis_evidence,
)
from patchbench.application.diagnosis_gold_lock import (
    OPERATIONAL_CASE_IDS,
    SELECTED_CASE_IDS,
    SEMANTIC_CASE_IDS,
    verify_diagnosis_gold_lock,
)
from patchbench.application.diagnosis_validation import (
    DiagnosisValidationError,
    compute_diagnosis_gold_sha256,
    compute_subject_evidence_sha256,
    validate_semantic_gold_evidence,
)
from patchbench.application.diagnosis_evidence import _snapshot_hash
from patchbench.application.diagnosis_peer import (
    ContrastivePeerSelection, DiagnosisPeerError, select_contrastive_peer,
    verify_contrastive_peer_selection,
)
from patchbench.config.task_loader import TaskLoadError, load_task
from patchbench.domain.diagnosis import (
    DiagnosisEvidenceBundle,
    DiagnosisMode,
    DiagnosisRoute,
    DiagnosisRoutingReason,
    DiagnosisSourcePolicy,
    EvidenceOwner,
    EvidenceKind,
    FailureFamily,
    route_run_diagnosis,
)
from patchbench.domain.diagnosis_integrity import canonical_json_bytes, compute_bundle_sha256
from patchbench.domain.diagnosis_gold_lock import DiagnosisGoldLockCase
from patchbench.domain.diagnosis_suite import (
    ContrastiveFairnessReview,
    ContrastiveFairnessReviewCase,
    DiagnosisValidationFreezeManifest,
    DiagnosisValidationSuite,
    DiagnosisValidationSuiteCase,
    DiagnosisValidationSuiteCaseFile,
    FrozenValidationFile,
    compute_diagnosis_validation_suite_sha256,
)
from patchbench.domain.diagnosis_gold_lock import DiagnosisGoldLockManifest
from patchbench.domain.diagnosis_validation import DiagnosisGoldCase
from patchbench.domain.models import RunRecord, Sha256Hex
from patchbench.repository.git_repository import GitRepositoryManager, RepositoryError
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
    CONTRASTIVE_FAIRNESS_FAILED = "contrastive_fairness_failed"
    HUMAN_FAIRNESS_PENDING = "human_fairness_pending"
    HUMAN_FAIRNESS_REJECTED = "human_fairness_rejected"


class DiagnosisSuiteError(ValueError):
    def __init__(self, reason: DiagnosisSuiteReason, detail: str):
        self.reason = reason
        super().__init__(f"{reason.value}: {detail}")


def _sha256(data: bytes) -> Sha256Hex:
    return hashlib.sha256(data).hexdigest()


def _disk_json_bytes(value) -> bytes:
    raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


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


def _verify_embedded_gold_lock(root: Path):
    """Verify protected D6.3b-1 files while allowing Phase A/B extensions."""
    files = _read_tree(Path(root))
    manifest_raw = _required_file(files, "gold-lock-manifest.json")
    manifest = _parse(DiagnosisGoldLockManifest, manifest_raw, "Gold lock manifest")
    with TemporaryDirectory(prefix="patchbench-gold-lock-verify-") as temporary:
        stage = Path(temporary)
        for item in manifest.files:
            data = _required_file(files, item.path)
            if len(data) != item.byte_length:
                raise DiagnosisSuiteError(
                    DiagnosisSuiteReason.FILE_LENGTH_MISMATCH, item.path)
            if _sha256(data) != item.sha256:
                raise DiagnosisSuiteError(
                    DiagnosisSuiteReason.FILE_HASH_MISMATCH, item.path)
            _write_output_file(stage, item.path, data)
        (stage / "gold-lock-manifest.json").write_bytes(manifest_raw)
        return verify_diagnosis_gold_lock(stage)


@contextmanager
def _without_inherited_git_environment():
    saved = {key: os.environ.pop(key) for key in list(os.environ) if key.startswith("GIT_")}
    try:
        yield
    finally:
        os.environ.update(saved)


def _git(repository: Path, *arguments: str) -> str:
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("GIT_")}
    environment.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "PatchBench Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@patchbench.invalid",
        "GIT_COMMITTER_NAME": "PatchBench Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@patchbench.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
    })
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            capture_output=True,
            text=True,
            check=True,
            env=environment,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.INVALID_CASE,
            f"Git command failed for {repository}: {detail.strip()}",
        ) from error
    return completed.stdout.strip()


def _restore_candidate_repository(case_root: Path) -> None:
    repository = case_root / "repository"
    if repository.exists() or repository.is_symlink():
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.INVALID_CASE,
            f"{case_root.name}: staged repository already exists",
        )
    shutil.copytree(case_root / "base", repository)
    _git(repository, "init", "-q")
    _git(repository, "config", "core.autocrlf", "false")
    _git(repository, "add", "-A")
    _git(repository, "-c", "user.name=PatchBench Test",
         "-c", "user.email=test@patchbench.invalid",
         "-c", "commit.gpgsign=false", "commit", "-qm", "controlled base")
    try:
        task = load_task(case_root / "task.yaml")
    except TaskLoadError as error:
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.INVALID_CASE,
            f"{case_root.name}: invalid TaskSpec",
        ) from error
    commit = _git(repository, "rev-parse", "HEAD")
    if task.repository.base_commit != commit:
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.INVALID_CASE,
            f"{case_root.name}: restored base commit differs",
        )


def _write_output_file(root: Path, relative: str, data: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _copy_tree_bytes(source_root: Path, output_root: Path, relative_root: str) -> dict[str, bytes]:
    files = _read_tree(source_root)
    copied = {}
    for source_relative, data in files.items():
        relative = f"{relative_root}/{source_relative}"
        _write_output_file(output_root, relative, data)
        copied[relative] = data
    return copied


def _verify_contrastive_fairness(
    case: DiagnosisValidationSuiteCase,
    gold: DiagnosisGoldCase,
    blind: DiagnosisEvidenceBundle,
    contrastive: DiagnosisEvidenceBundle,
) -> None:
    """Peer evidence must not change the already locked subject-Gold contract."""
    try:
        if compute_subject_evidence_sha256(contrastive) != compute_subject_evidence_sha256(blind):
            raise ValueError("Contrastive subject evidence differs from Blind")
        if compute_diagnosis_gold_sha256(gold) != case.gold_sha256:
            raise ValueError("locked Gold hash changed")
        validate_semantic_gold_evidence(blind, gold)
        validate_semantic_gold_evidence(contrastive, gold)
        if any(locator.owner is EvidenceOwner.PEER
               for requirement in gold.semantic_gold.required_evidence
               for locator in requirement.acceptable_locators):
            raise ValueError("locked Gold cites peer evidence")
    except (ValueError, DiagnosisValidationError) as error:
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.CONTRASTIVE_FAIRNESS_FAILED,
            f"{case.case_id}: {error}",
        ) from error


def _compile_locked_contrastive(
    case_id: str,
    blind: DiagnosisEvidenceBundle,
    *,
    candidate_root: Path,
    support_store: FilesystemArtifactStore,
    max_bundle_json_bytes: int,
) -> tuple[ContrastivePeerSelection, DiagnosisEvidenceBundle]:
    case_source = candidate_root / case_id
    try:
        selection = select_contrastive_peer(
            blind.subject_run_id,
            f"{case_id}-peers",
            artifact_store=support_store,
        )
        verify_contrastive_peer_selection(selection, artifact_store=support_store)
        with TemporaryDirectory(prefix="patchbench-diagnosis-freeze-") as temporary:
            stage = Path(temporary) / case_id
            shutil.copytree(case_source, stage)
            _restore_candidate_repository(stage)
            task_path = stage / "task.yaml"
            task_sha = _sha256(task_path.read_bytes())
            manager = GitRepositoryManager(stage / "workspaces")
            with _without_inherited_git_environment():
                bundle = compile_contrastive_diagnosis_evidence(
                    blind,
                    selection,
                    task_path=task_path,
                    expected_task_contract_sha256=task_sha,
                    source_policy=DiagnosisSourcePolicy(production_roots=["src"]),
                    max_bundle_json_bytes=max_bundle_json_bytes,
                    artifact_store=support_store,
                    repository_manager=manager,
                )
    except (OSError, DiagnosisPeerError, ContrastiveCompilationError,
            RepositoryError) as error:
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.INVALID_CASE,
            f"{case_id}: Contrastive compilation failed",
        ) from error
    return selection, bundle


def _semantic_case_from_lock(
    locked_case: DiagnosisGoldLockCase,
    *,
    gold_lock_root: Path,
    candidate_root: Path,
    max_bundle_json_bytes: int,
) -> tuple[DiagnosisValidationSuiteCase, dict[str, bytes]]:
    case_id = locked_case.case_id
    blind_raw = (gold_lock_root / locked_case.blind_bundle_path).read_bytes()
    gold_raw = (gold_lock_root / locked_case.gold_path).read_bytes()
    blind = _parse(DiagnosisEvidenceBundle, blind_raw, f"{case_id} Blind Bundle")
    gold = _parse(DiagnosisGoldCase, gold_raw, f"{case_id} Human Gold")
    support_source = candidate_root / "_support" / case_id / "results"
    support_relative = f"support/{case_id}/results"
    support_store = FilesystemArtifactStore(support_source)
    selection, contrastive = _compile_locked_contrastive(
        case_id,
        blind,
        candidate_root=candidate_root,
        support_store=support_store,
        max_bundle_json_bytes=max_bundle_json_bytes,
    )
    case = DiagnosisValidationSuiteCase(
        case_id=case_id,
        expected_route=DiagnosisRoute.SEMANTIC_DIAGNOSIS,
        gold_path=f"cases/{case_id}/gold.json",
        gold_sha256=locked_case.gold_sha256,
        subject_evidence_sha256=locked_case.subject_evidence_sha256,
        blind_bundle_path=f"cases/{case_id}/blind-bundle.json",
        blind_bundle_sha256=blind.bundle_sha256,
        contrastive_bundle_path=f"cases/{case_id}/contrastive-bundle.json",
        contrastive_bundle_sha256=contrastive.bundle_sha256,
        peer_selection_path=f"cases/{case_id}/peer-selection.json",
        peer_selection_sha256=_sha256(_disk_json_bytes(selection)),
        peer_artifact_store_path=support_relative,
    )
    _verify_contrastive_fairness(case, gold, blind, contrastive)
    verify_semantic_validation_case(
        case,
        gold,
        blind,
        contrastive,
        peer_selection=selection,
        peer_artifact_store=support_store,
    )
    artifacts = {
        case.gold_path: gold_raw,
        case.blind_bundle_path: blind_raw,
        case.contrastive_bundle_path: _disk_json_bytes(contrastive),
        case.peer_selection_path: _disk_json_bytes(selection),
    }
    return case, artifacts


def _review_case_from_semantic_case(
    case: DiagnosisValidationSuiteCase,
    selection: ContrastivePeerSelection,
) -> ContrastiveFairnessReviewCase:
    return ContrastiveFairnessReviewCase(
        case_id=case.case_id,
        locked_gold_sha256=case.gold_sha256,
        subject_evidence_sha256=case.subject_evidence_sha256,
        blind_bundle_sha256=case.blind_bundle_sha256,
        contrastive_bundle_sha256=case.contrastive_bundle_sha256,
        peer_run_id=selection.peer_run_id,
        peer_experiment_id=selection.peer_experiment_id,
        peer_run_index=selection.peer_run_index,
        peer_selection_sha256=case.peer_selection_sha256,
        machine_integrity_passed=True,
        human_fairness_status="pending",
    )


def _human_review_packet(review: ContrastiveFairnessReview, root: Path) -> bytes:
    lines = [
        "# Contrastive Fairness Review",
        "",
        "Question: Does the canonical PASS peer make the already-locked Human Gold unfair or invalid?",
        "",
        "Do not relabel, replace cases, or edit Gold in this packet. Record human confirmation only in contrastive-fairness-review.json.",
        "",
    ]
    for case in review.cases:
        bundle = DiagnosisEvidenceBundle.model_validate_json(
            (root / f"cases/{case.case_id}/contrastive-bundle.json").read_bytes())
        peer_items = [item for item in bundle.evidence_items if item.owner is EvidenceOwner.PEER]
        lines.extend([
            f"## {case.case_id}",
            "",
            f"- locked_gold_sha256: {case.locked_gold_sha256}",
            f"- subject_evidence_sha256: {case.subject_evidence_sha256}",
            f"- blind_bundle_sha256: {case.blind_bundle_sha256}",
            f"- contrastive_bundle_sha256: {case.contrastive_bundle_sha256}",
            f"- peer: {case.peer_experiment_id}[{case.peer_run_index}] -> {case.peer_run_id}",
            f"- peer_selection_sha256: {case.peer_selection_sha256}",
            f"- subject evidence identity unchanged: {case.machine_integrity_passed}",
            f"- human_fairness_status: {case.human_fairness_status}",
            "",
            "Peer evidence added by the Contrastive Bundle:",
            "",
        ])
        for item in peer_items:
            lines.extend([
                f"### {item.evidence_id} {item.kind.value} {item.path or ''}".rstrip(),
                "",
                f"- artifact_sha256: {item.artifact_sha256}",
                f"- source_state: {item.source_state.value if item.source_state else None}",
                "",
                "```text",
                item.content,
                "```",
                "",
            ])
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _operational_case_from_lock(
    locked_case: DiagnosisGoldLockCase,
    *,
    gold_lock_root: Path,
) -> tuple[DiagnosisValidationSuiteCase, dict[str, bytes]]:
    case_id = locked_case.case_id
    run_raw = (gold_lock_root / locked_case.run_record_path).read_bytes()
    gold_raw = (gold_lock_root / locked_case.route_gold_path).read_bytes()
    run = _parse(RunRecord, run_raw, f"{case_id} RunRecord")
    gold = _parse(DiagnosisGoldCase, gold_raw, f"{case_id} route Gold")
    if (compute_run_record_sha256(run) != locked_case.run_record_sha256
            or compute_diagnosis_gold_sha256(gold) != locked_case.route_gold_sha256):
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.INVALID_CASE,
            f"{case_id}: pre-Contrastive operational linkage changed",
        )
    case = DiagnosisValidationSuiteCase(
        case_id=case_id,
        expected_route=DiagnosisRoute.OPERATIONAL_ONLY,
        gold_path=f"cases/{case_id}/gold.json",
        gold_sha256=locked_case.route_gold_sha256,
        expected_routing_reason=locked_case.expected_routing_reason,
        run_record_path=f"cases/{case_id}/run-record.json",
        run_record_sha256=locked_case.run_record_sha256,
    )
    return case, {case.gold_path: gold_raw, case.run_record_path: run_raw}


def prepare_contrastive_fairness_review(
    gold_lock_root: Path,
    candidate_root: Path,
    *,
    max_bundle_json_bytes: int = 1_000_000,
) -> ContrastiveFairnessReview:
    """Phase A: add Contrastive bundles and pending human fairness review only."""
    if type(max_bundle_json_bytes) is not int or max_bundle_json_bytes <= 0:
        raise ValueError("max_bundle_json_bytes must be a positive integer")
    gold_lock_root = Path(gold_lock_root)
    candidate_root = Path(candidate_root)
    lock = verify_diagnosis_gold_lock(gold_lock_root)
    if tuple(case.case_id for case in lock.cases) != SELECTED_CASE_IDS:
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.INVALID_COMPOSITION,
            "pre-Contrastive lock selection differs",
        )
    if (gold_lock_root / "freeze-manifest.json").exists():
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.INVALID_MANIFEST,
            "Phase A must not start from an already frozen tree",
        )

    written: list[Path] = []
    try:
        review_cases: list[ContrastiveFairnessReviewCase] = []
        for locked_case in lock.cases:
            if locked_case.expected_route is DiagnosisRoute.SEMANTIC_DIAGNOSIS:
                if locked_case.case_id not in SEMANTIC_CASE_IDS:
                    raise DiagnosisSuiteError(
                        DiagnosisSuiteReason.INVALID_COMPOSITION,
                        f"{locked_case.case_id}: unexpected semantic case",
                    )
                case_id = locked_case.case_id
                blind_raw = (gold_lock_root / locked_case.blind_bundle_path).read_bytes()
                gold_raw = (gold_lock_root / locked_case.gold_path).read_bytes()
                blind = _parse(DiagnosisEvidenceBundle, blind_raw, f"{case_id} Blind Bundle")
                gold = _parse(DiagnosisGoldCase, gold_raw, f"{case_id} Human Gold")
                support_store = FilesystemArtifactStore(
                    candidate_root / "_support" / case_id / "results")
                selection, contrastive = _compile_locked_contrastive(
                    case_id,
                    blind,
                    candidate_root=candidate_root,
                    support_store=support_store,
                    max_bundle_json_bytes=max_bundle_json_bytes,
                )
                selection_raw = _disk_json_bytes(selection)
                case = DiagnosisValidationSuiteCase(
                    case_id=case_id,
                    expected_route=DiagnosisRoute.SEMANTIC_DIAGNOSIS,
                    gold_path=locked_case.gold_path,
                    gold_sha256=locked_case.gold_sha256,
                    subject_evidence_sha256=locked_case.subject_evidence_sha256,
                    blind_bundle_path=locked_case.blind_bundle_path,
                    blind_bundle_sha256=locked_case.blind_bundle_sha256,
                    contrastive_bundle_path=f"cases/{case_id}/contrastive-bundle.json",
                    contrastive_bundle_sha256=contrastive.bundle_sha256,
                    peer_selection_path=f"contrastive-fairness-review.json#{case_id}",
                    peer_selection_sha256=_sha256(selection_raw),
                    peer_artifact_store_path=(
                        f"fixtures/diagnosis_validation/v1_candidates/_support/{case_id}/results"
                    ),
                )
                _verify_contrastive_fairness(case, gold, blind, contrastive)
                verify_semantic_validation_case(
                    case,
                    gold,
                    blind,
                    contrastive,
                    peer_selection=selection,
                    peer_artifact_store=support_store,
                )
                path = gold_lock_root / case.contrastive_bundle_path
                _write_output_file(gold_lock_root, case.contrastive_bundle_path,
                                   _disk_json_bytes(contrastive))
                written.append(path)
                review_cases.append(_review_case_from_semantic_case(case, selection))
        review = ContrastiveFairnessReview(cases=review_cases)
        review_path = gold_lock_root / "contrastive-fairness-review.json"
        packet_path = gold_lock_root / "contrastive-fairness-review.md"
        review_path.write_bytes(_disk_json_bytes(review))
        written.append(review_path)
        packet_path.write_bytes(_human_review_packet(review, gold_lock_root))
        written.append(packet_path)
        verify_contrastive_fairness_review(gold_lock_root, candidate_root)
    except Exception:
        for path in reversed(written):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise
    return review


def build_diagnosis_validation_suite(
    gold_lock_root: Path,
    candidate_root: Path,
    output_root: Path | None = None,
    *,
    max_bundle_json_bytes: int = 1_000_000,
) -> ContrastiveFairnessReview:
    """Compatibility wrapper for Phase A preparation; it never writes a freeze manifest."""
    if output_root is not None and Path(output_root) != Path(gold_lock_root):
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.INVALID_ROOT,
            "Phase A extends the pre-Contrastive lock in place",
        )
    return prepare_contrastive_fairness_review(
        gold_lock_root,
        candidate_root,
        max_bundle_json_bytes=max_bundle_json_bytes,
    )


def _review_selection(case: ContrastiveFairnessReviewCase) -> ContrastivePeerSelection:
    return ContrastivePeerSelection(
        subject_run_id=f"{case.case_id}-subject",
        peer_experiment_id=case.peer_experiment_id,
        peer_run_id=case.peer_run_id,
        peer_run_index=case.peer_run_index,
    )


def verify_contrastive_fairness_review(
    root: Path,
    candidate_root: Path,
    *,
    allow_freeze_manifest: bool = False,
) -> ContrastiveFairnessReview:
    """Verify Phase A using the immutable Gold lock and canonical source support."""
    root = Path(root)
    candidate_root = Path(candidate_root)
    lock = _verify_embedded_gold_lock(root)
    if (root / "freeze-manifest.json").exists() and not allow_freeze_manifest:
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.INVALID_MANIFEST,
            "freeze-manifest.json is not allowed before Phase B finalization",
        )
    if any(part == "support" or part == "_support"
           for path in root.rglob("*") for part in path.relative_to(root).parts):
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.EXTRA_FILE,
            "validation tree must not contain copied source support",
        )
    review_raw = _required_file(_read_tree(root), "contrastive-fairness-review.json")
    review = _parse(ContrastiveFairnessReview, review_raw, "contrastive fairness review")
    if [case.case_id for case in review.cases] != list(SEMANTIC_CASE_IDS):
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.INVALID_COMPOSITION,
            "review cases differ from selected semantic cases",
        )
    locked = {case.case_id: case for case in lock.cases}
    for review_case in review.cases:
        locked_case = locked[review_case.case_id]
        blind = _parse(DiagnosisEvidenceBundle,
                       (root / locked_case.blind_bundle_path).read_bytes(),
                       f"{review_case.case_id} Blind Bundle")
        gold = _parse(DiagnosisGoldCase,
                      (root / locked_case.gold_path).read_bytes(),
                      f"{review_case.case_id} Human Gold")
        contrastive_path = root / f"cases/{review_case.case_id}/contrastive-bundle.json"
        contrastive = _parse(DiagnosisEvidenceBundle, contrastive_path.read_bytes(),
                             f"{review_case.case_id} Contrastive Bundle")
        selection = _review_selection(review_case)
        selection_raw = _disk_json_bytes(selection)
        if (review_case.locked_gold_sha256 != locked_case.gold_sha256
                or review_case.subject_evidence_sha256 != locked_case.subject_evidence_sha256
                or review_case.blind_bundle_sha256 != locked_case.blind_bundle_sha256
                or review_case.contrastive_bundle_sha256 != contrastive.bundle_sha256
                or review_case.peer_selection_sha256 != _sha256(selection_raw)
                or not review_case.machine_integrity_passed):
            raise DiagnosisSuiteError(
                DiagnosisSuiteReason.INVALID_CASE,
                f"{review_case.case_id}: review linkage differs",
            )
        case = DiagnosisValidationSuiteCase(
            case_id=review_case.case_id,
            expected_route=DiagnosisRoute.SEMANTIC_DIAGNOSIS,
            gold_path=locked_case.gold_path,
            gold_sha256=locked_case.gold_sha256,
            subject_evidence_sha256=locked_case.subject_evidence_sha256,
            blind_bundle_path=locked_case.blind_bundle_path,
            blind_bundle_sha256=locked_case.blind_bundle_sha256,
            contrastive_bundle_path=f"cases/{review_case.case_id}/contrastive-bundle.json",
            contrastive_bundle_sha256=contrastive.bundle_sha256,
            peer_selection_path=f"contrastive-fairness-review.json#{review_case.case_id}",
            peer_selection_sha256=review_case.peer_selection_sha256,
            peer_artifact_store_path=(
                f"fixtures/diagnosis_validation/v1_candidates/_support/{review_case.case_id}/results"
            ),
        )
        support_store = FilesystemArtifactStore(
            candidate_root / "_support" / review_case.case_id / "results")
        _verify_contrastive_fairness(case, gold, blind, contrastive)
        verify_semantic_validation_case(
            case,
            gold,
            blind,
            contrastive,
            peer_selection=selection,
            peer_artifact_store=support_store,
        )
    return review


def finalize_diagnosis_validation_freeze(
    root: Path,
    candidate_root: Path,
) -> DiagnosisValidationFreezeManifest:
    """Phase B: write freeze-manifest.json only after all human statuses are confirmed."""
    root = Path(root)
    review = verify_contrastive_fairness_review(root, candidate_root)
    for case in review.cases:
        if case.human_fairness_status == "pending":
            raise DiagnosisSuiteError(
                DiagnosisSuiteReason.HUMAN_FAIRNESS_PENDING,
                f"{case.case_id}: human fairness is still pending",
            )
        if case.human_fairness_status == "rejected":
            raise DiagnosisSuiteError(
                DiagnosisSuiteReason.HUMAN_FAIRNESS_REJECTED,
                f"{case.case_id}: human fairness was rejected",
            )
    lock = _verify_embedded_gold_lock(root)
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()
                       and item.name != "freeze-manifest.json"):
        raw = path.read_bytes()
        files.append(FrozenValidationFile(
            path=path.relative_to(root).as_posix(),
            sha256=_sha256(raw),
            byte_length=len(raw),
        ))
    manifest = DiagnosisValidationFreezeManifest(
        suite_path="suite.json",
        suite_sha256=hashlib.sha256(canonical_json_bytes(lock.model_dump(mode="json"))).hexdigest(),
        files=files,
    )
    (root / "freeze-manifest.json").write_bytes(_disk_json_bytes(manifest))
    return manifest


def _verify_final_freeze_manifest(
    root: Path,
    candidate_root: Path,
) -> DiagnosisValidationFreezeManifest:
    files = _read_tree(root)
    manifest_raw = files.pop("freeze-manifest.json", None)
    if manifest_raw is None:
        raise DiagnosisSuiteError(DiagnosisSuiteReason.MISSING_FILE,
                                  "freeze-manifest.json is missing")
    manifest = _parse(DiagnosisValidationFreezeManifest, manifest_raw, "freeze manifest")
    expected, actual = {item.path for item in manifest.files}, set(files)
    if expected - actual:
        raise DiagnosisSuiteError(DiagnosisSuiteReason.MISSING_FILE,
                                  repr(sorted(expected - actual)))
    if actual - expected:
        raise DiagnosisSuiteError(DiagnosisSuiteReason.EXTRA_FILE,
                                  repr(sorted(actual - expected)))
    for item in manifest.files:
        data = files[item.path]
        if len(data) != item.byte_length:
            raise DiagnosisSuiteError(DiagnosisSuiteReason.FILE_LENGTH_MISMATCH, item.path)
        if _sha256(data) != item.sha256:
            raise DiagnosisSuiteError(DiagnosisSuiteReason.FILE_HASH_MISMATCH, item.path)
    lock = _verify_embedded_gold_lock(root)
    if manifest.suite_sha256 != hashlib.sha256(
            canonical_json_bytes(lock.model_dump(mode="json"))).hexdigest():
        raise DiagnosisSuiteError(DiagnosisSuiteReason.SUITE_HASH_MISMATCH, "suite.json")
    review = verify_contrastive_fairness_review(
        root, candidate_root, allow_freeze_manifest=True)
    if any(case.human_fairness_status != "confirmed" for case in review.cases):
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.HUMAN_FAIRNESS_PENDING,
            "final freeze requires all human fairness statuses confirmed",
        )
    return manifest


def verify_diagnosis_validation_freeze(
    root: Path,
    candidate_root: Path,
) -> DiagnosisValidationFreezeManifest:
    """Verify a Phase B freeze without copied raw support."""
    return _verify_final_freeze_manifest(root, candidate_root)


def _legacy_build_diagnosis_validation_suite(
    gold_lock_root: Path,
    candidate_root: Path,
    output_root: Path,
    *,
    max_bundle_json_bytes: int = 1_000_000,
) -> DiagnosisValidationSuite:
    """Legacy synthetic builder retained only as a reference in old review diffs."""
    if type(max_bundle_json_bytes) is not int or max_bundle_json_bytes <= 0:
        raise ValueError("max_bundle_json_bytes must be a positive integer")
    gold_lock_root = Path(gold_lock_root)
    candidate_root = Path(candidate_root)
    output_root = Path(output_root)
    lock = verify_diagnosis_gold_lock(gold_lock_root)
    if tuple(case.case_id for case in lock.cases) != SELECTED_CASE_IDS:
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.INVALID_COMPOSITION,
            "pre-Contrastive lock selection differs",
        )
    if output_root.exists() or output_root.is_symlink():
        raise DiagnosisSuiteError(
            DiagnosisSuiteReason.INVALID_ROOT,
            "output root must not exist",
        )

    try:
        output_root.mkdir(parents=True)
        cases: list[DiagnosisValidationSuiteCase] = []
        for locked_case in lock.cases:
            if locked_case.expected_route is DiagnosisRoute.SEMANTIC_DIAGNOSIS:
                if locked_case.case_id not in SEMANTIC_CASE_IDS:
                    raise DiagnosisSuiteError(
                        DiagnosisSuiteReason.INVALID_COMPOSITION,
                        f"{locked_case.case_id}: unexpected semantic case",
                    )
                case, artifacts = _semantic_case_from_lock(
                    locked_case,
                    gold_lock_root=gold_lock_root,
                    candidate_root=candidate_root,
                    max_bundle_json_bytes=max_bundle_json_bytes,
                )
                support_files = _copy_tree_bytes(
                    candidate_root / "_support" / locked_case.case_id / "results",
                    output_root,
                    case.peer_artifact_store_path,
                )
                artifacts.update(support_files)
            elif locked_case.case_id in OPERATIONAL_CASE_IDS:
                case, artifacts = _operational_case_from_lock(
                    locked_case,
                    gold_lock_root=gold_lock_root,
                )
            else:
                raise DiagnosisSuiteError(
                    DiagnosisSuiteReason.INVALID_COMPOSITION,
                    f"{locked_case.case_id}: unexpected operational case",
                )
            for relative, data in artifacts.items():
                _write_output_file(output_root, relative, data)
            case_raw = _disk_json_bytes(case)
            case_path = f"cases/{case.case_id}/case.json"
            _write_output_file(output_root, case_path, case_raw)
            cases.append(case)

        case_files = [
            DiagnosisValidationSuiteCaseFile(
                case_id=case.case_id,
                path=f"cases/{case.case_id}/case.json",
                sha256=_sha256((output_root / f"cases/{case.case_id}/case.json").read_bytes()),
            )
            for case in cases
        ]
        suite = DiagnosisValidationSuite(
            suite_id="diagnosis-validation-v1",
            case_files=sorted(case_files, key=lambda item: (item.case_id, item.path)),
        )
        suite_raw = _disk_json_bytes(suite)
        _write_output_file(output_root, "suite.json", suite_raw)

        frozen_files = []
        for path in sorted(item for item in output_root.rglob("*") if item.is_file()
                           and item.name != "freeze-manifest.json"):
            raw = path.read_bytes()
            frozen_files.append(FrozenValidationFile(
                path=path.relative_to(output_root).as_posix(),
                sha256=_sha256(raw),
                byte_length=len(raw),
            ))
        manifest = DiagnosisValidationFreezeManifest(
            suite_path="suite.json",
            suite_sha256=compute_diagnosis_validation_suite_sha256(suite),
            files=frozen_files,
        )
        _write_output_file(output_root, "freeze-manifest.json", _disk_json_bytes(manifest))
        verify_diagnosis_validation_suite(output_root)
    except Exception:
        shutil.rmtree(output_root, ignore_errors=True)
        raise
    return suite


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
