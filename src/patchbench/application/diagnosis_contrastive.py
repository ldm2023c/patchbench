"""Augment exact Blind evidence with one frozen, verified same-cell PASS peer."""

from enum import Enum
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from patchbench.application.diagnosis_peer import ContrastivePeerSelection, verify_contrastive_peer_selection, DiagnosisPeerError
from patchbench.application.diagnosis_evidence import (
    _VerifiedInputs, _reconstruct, _policy_identity, _snapshot_hash, _descriptor, _sha,
    DiagnosisCompilationError,
)
from patchbench.config.task_loader import load_task, TaskLoadError
from patchbench.domain.diagnosis import (
    DiagnosisEvidenceBundle, DiagnosisMode, DiagnosisSourcePolicy, EvidenceItem, EvidenceKind,
    EvidenceOwner, EvidenceSourceState, BundleProvenance, PeerProvenance,
)
from patchbench.domain.diagnosis_integrity import canonical_json_bytes, compute_bundle_sha256
from patchbench.domain.models import Sha256Hex
from patchbench.domain.provenance import compute_task_fingerprint
from patchbench.domain.patch_evidence import summarize_patch
from patchbench.domain.evaluation_evidence import summarize_evaluation_log
from patchbench.domain.evidence_errors import EvidenceParsingError
from patchbench.repository.git_repository import GitRepositoryManager
from patchbench.storage.filesystem import FilesystemArtifactStore, ArtifactStoreError


class ContrastiveCompilationReason(str, Enum):
    INVALID_BLIND_BUNDLE = "invalid_blind_bundle"
    PEER_SELECTION_MISMATCH = "peer_selection_mismatch"
    PEER_EVIDENCE_MISSING = "peer_evidence_missing"
    PEER_EVIDENCE_MISMATCH = "peer_evidence_mismatch"
    PEER_CELL_MISMATCH = "peer_cell_mismatch"
    TASK_CONTRACT_MISMATCH = "task_contract_mismatch"
    PEER_RECONSTRUCTION_FAILED = "peer_reconstruction_failed"
    BUNDLE_TOO_LARGE = "bundle_too_large"


class ContrastiveCompilationError(ValueError):
    def __init__(self, reason: ContrastiveCompilationReason, detail: str):
        self.reason = reason
        super().__init__(f"{reason.value}: {detail}")


def compile_contrastive_diagnosis_evidence(
    blind_bundle: DiagnosisEvidenceBundle, peer_selection: ContrastivePeerSelection, *,
    task_path: str | Path, expected_task_contract_sha256: str, source_policy: DiagnosisSourcePolicy,
    max_bundle_json_bytes: int, artifact_store: FilesystemArtifactStore,
    repository_manager: GitRepositoryManager,
) -> DiagnosisEvidenceBundle:
    """Append P items sorted by kind, source state, path; never replace a selected peer.

    Original E items and subject provenance are copied exactly. Raw evidence is
    opaque text, including any absolute-path strings already present in it.
    """
    if (blind_bundle.mode is not DiagnosisMode.BLIND
            or compute_bundle_sha256(blind_bundle) != blind_bundle.bundle_sha256
            or blind_bundle.subject_run_id != peer_selection.subject_run_id):
        raise ContrastiveCompilationError(ContrastiveCompilationReason.INVALID_BLIND_BUNDLE,
                                         "Requires exact verified Blind subject Bundle")
    if type(max_bundle_json_bytes) is not int or max_bundle_json_bytes <= 0:
        raise ValueError("max_bundle_json_bytes must be a positive integer")
    policy = DiagnosisSourcePolicy.model_validate(source_policy.model_dump())
    try:
        subject, peer = verify_contrastive_peer_selection(peer_selection, artifact_store=artifact_store)
    except DiagnosisPeerError as error:
        raise ContrastiveCompilationError(ContrastiveCompilationReason.PEER_SELECTION_MISMATCH,
                                         "Frozen peer selection no longer verifies") from error
    assert subject.provenance is not None and peer.provenance is not None
    assert subject.patch_summary is not None and subject.evaluation_evidence is not None
    subject_hashes = blind_bundle.provenance.subject
    if (blind_bundle.task_id != subject.task_id
            or blind_bundle.base_commit != subject.provenance.base_commit_used
            or blind_bundle.task_fingerprint_sha256 != subject.provenance.task_fingerprint_sha256
            or subject_hashes.canonical_patch_sha256 != subject.patch_summary.patch_sha256
            or subject_hashes.evaluation_log_sha256 != subject.evaluation_evidence.test_log_sha256
            or blind_bundle.source_snapshot_policy != _policy_identity(policy)):
        raise ContrastiveCompilationError(ContrastiveCompilationReason.PEER_CELL_MISMATCH,
                                         "Blind identity/evidence differs from frozen subject cell")
    try:
        patch = artifact_store.load_run_patch(peer.run_id)
        log = artifact_store.load_run_test_log(peer.run_id)
    except ArtifactStoreError as error:
        raise ContrastiveCompilationError(ContrastiveCompilationReason.PEER_EVIDENCE_MISSING,
                                         "Selected peer raw artifacts are unavailable") from error
    try:
        patch_summary = summarize_patch(patch)
        evaluation = summarize_evaluation_log(log)
    except (EvidenceParsingError, ValidationError) as error:
        raise ContrastiveCompilationError(ContrastiveCompilationReason.PEER_EVIDENCE_MISMATCH,
                                         "Selected peer raw evidence cannot be parsed") from error
    if (patch_summary != peer.patch_summary or evaluation != peer.evaluation_evidence
            or not evaluation.passed or not log.startswith(f"Command: {peer.provenance.evaluation_command}\n")):
        raise ContrastiveCompilationError(ContrastiveCompilationReason.PEER_EVIDENCE_MISMATCH,
                                         "Selected peer raw evidence differs from persisted PASS evidence")
    path = Path(task_path)
    try:
        TypeAdapter(Sha256Hex).validate_python(expected_task_contract_sha256)
        task_bytes = path.read_bytes()
        task_bytes.decode("utf-8")
        if _sha(task_bytes) != expected_task_contract_sha256 or _sha(task_bytes) != subject_hashes.task_contract_sha256:
            raise ValueError("Task bytes differ from frozen identity")
        task = load_task(path)
        if path.read_bytes() != task_bytes:
            raise ValueError("Task bytes changed while loading")
    except (OSError, UnicodeError, ValueError, TaskLoadError) as error:
        raise ContrastiveCompilationError(ContrastiveCompilationReason.TASK_CONTRACT_MISMATCH,
                                         "Requires exact frozen TaskSpec bytes") from error
    if (task.evaluation.frozen_unittest is None or task.id != peer.task_id
            or compute_task_fingerprint(task, base_commit_used=peer.provenance.base_commit_used)
            != peer.provenance.task_fingerprint_sha256
            or task.evaluation.command != peer.provenance.evaluation_command
            or task.evaluation.timeout_seconds != peer.provenance.evaluation_timeout_seconds):
        raise ContrastiveCompilationError(ContrastiveCompilationReason.PEER_CELL_MISMATCH,
                                         "Task/evaluation contract differs from peer cell")
    try:
        base, candidate, frozen = _reconstruct(_VerifiedInputs(peer, task, task_bytes, patch, log), policy, repository_manager)
    except DiagnosisCompilationError as error:
        raise ContrastiveCompilationError(ContrastiveCompilationReason.PEER_RECONSTRUCTION_FAILED,
                                         f"Selected peer reconstruction failed: {error.reason.value}") from error
    if (_snapshot_hash(base) != subject_hashes.base_source_snapshot_sha256
            or _snapshot_hash(frozen, order=task.evaluation.frozen_unittest.test_files)
            != subject_hashes.frozen_tests_snapshot_sha256):
        raise ContrastiveCompilationError(ContrastiveCompilationReason.PEER_CELL_MISMATCH,
                                         "Peer base or frozen-test bytes differ from Blind subject evidence")
    descriptors = [
        _descriptor(patch.encode("utf-8"), EvidenceKind.PEER_PATCH, EvidenceOwner.PEER, path="patch.diff"),
        _descriptor(log.encode("utf-8"), EvidenceKind.PEER_EVALUATION, EvidenceOwner.PEER, path="test.log"),
        *(_descriptor(data, EvidenceKind.PEER_SOURCE, EvidenceOwner.PEER,
                      state=EvidenceSourceState.CANDIDATE, path=name) for name, data in candidate.items()),
    ]
    descriptors.sort(key=lambda d: (d["kind"].value, d["source_state"].value if d["source_state"] else "", d["path"] or ""))
    items = [EvidenceItem(evidence_id=f"P{index:03d}", **descriptor) for index, descriptor in enumerate(descriptors, 1)]
    if {item.evidence_id for item in items} & {item.evidence_id for item in blind_bundle.evidence_items}:
        raise ContrastiveCompilationError(ContrastiveCompilationReason.INVALID_BLIND_BUNDLE, "Blind IDs collide with P namespace")
    identity = dict(schema_version=1, mode="contrastive", subject_run_id=blind_bundle.subject_run_id,
        peer_experiment_id=peer_selection.peer_experiment_id, peer_run_index=peer_selection.peer_run_index,
        peer_run_id=peer.run_id, blind_bundle_sha256=blind_bundle.bundle_sha256,
        benchmark_definition_sha256=blind_bundle.benchmark_definition_sha256,
        task_fingerprint_sha256=blind_bundle.task_fingerprint_sha256, source_snapshot_policy=blind_bundle.source_snapshot_policy)
    data = blind_bundle.model_dump(mode="json")
    data.update(mode="contrastive", peer_run_id=peer.run_id,
        bundle_id="contrastive-" + _sha(canonical_json_bytes(identity)), bundle_sha256="0" * 64,
        evidence_items=[*blind_bundle.evidence_items, *items],
        provenance=BundleProvenance(subject=subject_hashes, peer=PeerProvenance(peer_run_id=peer.run_id,
            peer_experiment_id=peer_selection.peer_experiment_id, peer_run_index=peer_selection.peer_run_index,
            peer_patch_sha256=_sha(patch.encode("utf-8")), peer_evaluation_log_sha256=_sha(log.encode("utf-8")),
            peer_candidate_snapshot_sha256=_snapshot_hash(candidate))))
    bundle = DiagnosisEvidenceBundle(**data).model_copy(deep=True)
    bundle.bundle_sha256 = compute_bundle_sha256(bundle)
    if len(canonical_json_bytes(bundle.model_dump(mode="json"))) > max_bundle_json_bytes:
        raise ContrastiveCompilationError(ContrastiveCompilationReason.BUNDLE_TOO_LARGE, "Complete Contrastive Bundle exceeds byte bound")
    return bundle
