"""Deterministic, complete Blind evidence compilation; no Agent or evaluator runs."""

from enum import Enum
from dataclasses import dataclass
import hashlib
from pathlib import Path
import stat
import re
from tempfile import TemporaryDirectory

from pydantic import TypeAdapter, ValidationError

from patchbench.domain.diagnosis import (
    BundleProvenance, DiagnosisEvidenceBundle, DiagnosisMode, DiagnosisRoute,
    DiagnosisSourcePolicy, EvidenceItem, EvidenceKind, EvidenceOwner,
    EvidenceSourceState, SubjectProvenance, route_run_diagnosis,
)
from patchbench.domain.models import RunRecord, RunStatus, Sha256Hex, TaskSpec
from patchbench.domain.diagnosis_integrity import (
    canonical_json_bytes as _canonical_json, compute_bundle_sha256,
)
from patchbench.domain.provenance import compute_task_fingerprint
from patchbench.domain.patch_evidence import summarize_patch
from patchbench.domain.evaluation_evidence import summarize_evaluation_log
from patchbench.domain.evidence_errors import EvidenceParsingError
from patchbench.config.task_loader import load_task, TaskLoadError
from patchbench.repository.git_repository import GitRepositoryManager, RepositoryError
from patchbench.storage.filesystem import FilesystemArtifactStore, ArtifactStoreError


class DiagnosisCompilationReason(str, Enum):
    NOT_SEMANTIC_RUN = "not_semantic_run"
    MISSING_RUN_EVIDENCE = "missing_run_evidence"
    RUN_EVIDENCE_MISMATCH = "run_evidence_mismatch"
    TASK_CONTRACT_MISMATCH = "task_contract_mismatch"
    RUN_PROVENANCE_MISMATCH = "run_provenance_mismatch"
    UNSUPPORTED_EVALUATOR = "unsupported_evaluator"
    SOURCE_UNAVAILABLE = "source_unavailable"
    UNSUPPORTED_SOURCE = "unsupported_source"
    PATCH_RECONSTRUCTION_FAILED = "patch_reconstruction_failed"
    BUNDLE_TOO_LARGE = "bundle_too_large"


class DiagnosisCompilationError(ValueError):
    def __init__(self, reason: DiagnosisCompilationReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")


# Version-one selection semantics. Changes require a new policy version.
_TECHNICAL_DENYLIST = (
    ".git", ".patchbench-eval", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _policy_identity(policy: DiagnosisSourcePolicy) -> str:
    payload = dict(schema_version=policy.schema_version,
                   production_roots=sorted(policy.production_roots),
                   excluded_paths=sorted(policy.excluded_paths),
                   technical_denylist=sorted(_TECHNICAL_DENYLIST),
                   auto_exclude_frozen_tests=True)
    return "full_bounded_production_v1:" + _sha(_canonical_json(payload))


def _snapshot_hash(files: dict[str, bytes], *, order: list[str] | None = None) -> str:
    paths = sorted(files) if order is None else order
    return _sha(_canonical_json(dict(snapshot_version=1, files=[
        dict(path=path, sha256=_sha(files[path]), byte_length=len(files[path])) for path in paths
    ])))


def _excluded(path: str, policy: DiagnosisSourcePolicy, frozen_tests: list[str]) -> bool:
    return (any(part in _TECHNICAL_DENYLIST for part in path.split("/"))
            or any(excluded == "." or path == excluded or path.startswith(excluded + "/")
                   for excluded in [*policy.excluded_paths, *frozen_tests]))


def _validate_source_locator(relative: str) -> None:
    """Reject locators outside the exact repo-relative POSIX contract; never normalize."""
    try:
        relative.encode("utf-8")
    except UnicodeEncodeError as error:
        raise DiagnosisCompilationError(DiagnosisCompilationReason.UNSUPPORTED_SOURCE,
                                        "Included source path is not UTF-8") from error
    if (not relative or relative.startswith("/") or relative != relative.strip()
            or "\\" in relative or ":" in relative
            or any(ord(char) < 32 or ord(char) == 127 for char in relative)
            or any(part in {"", ".", ".."} for part in relative.split("/"))):
        raise DiagnosisCompilationError(DiagnosisCompilationReason.UNSUPPORTED_SOURCE,
                                        "Included source path is not canonical repo-relative POSIX")


def _read_source(path: Path, relative: str) -> bytes:
    _validate_source_locator(relative)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise DiagnosisCompilationError(DiagnosisCompilationReason.UNSUPPORTED_SOURCE,
                                        f"Included source is not a regular file: {relative}")
    data = path.read_bytes()
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DiagnosisCompilationError(DiagnosisCompilationReason.UNSUPPORTED_SOURCE,
                                        f"Included source is not UTF-8: {relative}") from error
    if b"\x00" in data:
        raise DiagnosisCompilationError(DiagnosisCompilationReason.UNSUPPORTED_SOURCE,
                                        f"Included source contains binary NUL bytes: {relative}")
    return data


def _collect_snapshot(root: Path, policy: DiagnosisSourcePolicy,
                      frozen_tests: list[str]) -> tuple[dict[str, bytes], set[str]]:
    """Traverse all selected files, checking ancestors before descending roots."""
    files: dict[str, bytes] = {}
    existing_roots: set[str] = set()

    def visit(path: Path, relative: str) -> None:
        if _excluded(relative, policy, frozen_tests):
            return
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            for child in sorted(path.iterdir(), key=lambda entry: entry.name):
                visit(child, child.relative_to(root).as_posix())
        else:
            files[relative] = _read_source(path, relative)

    try:
        for declared in sorted(policy.production_roots):
            path = root
            blocked = False
            parts = [] if declared == "." else declared.split("/")
            for index, part in enumerate(parts):
                path = path / part
                relative = "/".join(parts[:index + 1])
                try:
                    mode = path.lstat().st_mode
                except FileNotFoundError:
                    blocked = True
                    break
                if stat.S_ISLNK(mode) or (index < len(parts) - 1 and not stat.S_ISDIR(mode)):
                    if _excluded(relative, policy, frozen_tests):
                        # An excluded root still exists, but never follow an
                        # excluded symlink ancestor to infer descendant existence.
                        if index == len(parts) - 1:
                            existing_roots.add(declared)
                        blocked = True
                        break
                    raise DiagnosisCompilationError(DiagnosisCompilationReason.UNSUPPORTED_SOURCE,
                                                    f"Unsupported production root ancestor: {relative}")
            if blocked:
                continue
            existing_roots.add(declared)
            visit(path, declared)
    except OSError as error:
        raise DiagnosisCompilationError(DiagnosisCompilationReason.SOURCE_UNAVAILABLE,
                                        "Unable to read selected source snapshot") from error
    return dict(sorted(files.items())), existing_roots


@dataclass(frozen=True)
class _VerifiedInputs:
    run: RunRecord
    task: TaskSpec
    task_bytes: bytes
    patch: str
    test_log: str


def _verify_inputs(task_path: Path, run_id: str, expected_task_contract_sha256: str,
                   artifact_store: FilesystemArtifactStore) -> _VerifiedInputs:
    try:
        run = artifact_store.load_run_record(run_id)
    except ArtifactStoreError as error:
        raise DiagnosisCompilationError(DiagnosisCompilationReason.MISSING_RUN_EVIDENCE, str(error)) from error
    if route_run_diagnosis(run).route is not DiagnosisRoute.SEMANTIC_DIAGNOSIS:
        raise DiagnosisCompilationError(DiagnosisCompilationReason.NOT_SEMANTIC_RUN,
                                        "Run must have official FAIL and COMPLETED Agent execution")
    if run.provenance is None or run.patch_summary is None or run.evaluation_evidence is None:
        raise DiagnosisCompilationError(DiagnosisCompilationReason.MISSING_RUN_EVIDENCE,
                                        "Run requires provenance and both persisted evidence summaries")
    try:
        patch = artifact_store.load_run_patch(run_id)
        test_log = artifact_store.load_run_test_log(run_id)
    except ArtifactStoreError as error:
        raise DiagnosisCompilationError(DiagnosisCompilationReason.MISSING_RUN_EVIDENCE, str(error)) from error
    try:
        patch_summary = summarize_patch(patch)
        evaluation = summarize_evaluation_log(test_log)
    except (EvidenceParsingError, ValidationError) as error:
        raise DiagnosisCompilationError(DiagnosisCompilationReason.RUN_EVIDENCE_MISMATCH,
                                        "Raw Run evidence could not be parsed") from error
    if (patch_summary != run.patch_summary or evaluation != run.evaluation_evidence
            or evaluation.passed != run.evaluation_passed or run.status is not RunStatus.FAILED):
        raise DiagnosisCompilationError(DiagnosisCompilationReason.RUN_EVIDENCE_MISMATCH,
                                        "Raw artifacts disagree with persisted Run evidence/outcome")
    try:
        TypeAdapter(Sha256Hex).validate_python(expected_task_contract_sha256)
        task_bytes = task_path.read_bytes()
        task_bytes.decode("utf-8")
        if _sha(task_bytes) != expected_task_contract_sha256:
            raise DiagnosisCompilationError(DiagnosisCompilationReason.TASK_CONTRACT_MISMATCH,
                                            "Task contract bytes differ from externally frozen hash")
        task = load_task(task_path)
        if task_path.read_bytes() != task_bytes:
            raise DiagnosisCompilationError(DiagnosisCompilationReason.TASK_CONTRACT_MISMATCH,
                                            "Task contract changed while loading")
    except (OSError, UnicodeError, ValidationError, TaskLoadError) as error:
        raise DiagnosisCompilationError(DiagnosisCompilationReason.TASK_CONTRACT_MISMATCH,
                                        "Unable to load the frozen UTF-8 TaskSpec") from error
    if task.evaluation.frozen_unittest is None:
        raise DiagnosisCompilationError(DiagnosisCompilationReason.UNSUPPORTED_EVALUATOR,
                                        "Diagnosis requires frozen unittest evaluation")
    provenance = run.provenance
    if (task.id != run.task_id
            or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", provenance.base_commit_used) is None
            or compute_task_fingerprint(task, base_commit_used=provenance.base_commit_used)
            != provenance.task_fingerprint_sha256
            or task.evaluation.command != provenance.evaluation_command
            or task.evaluation.timeout_seconds != provenance.evaluation_timeout_seconds
            or not test_log.startswith(f"Command: {provenance.evaluation_command}\n")):
        raise DiagnosisCompilationError(DiagnosisCompilationReason.RUN_PROVENANCE_MISMATCH,
                                        "Task semantics or historical commit disagree with Run provenance")
    return _VerifiedInputs(run, task, task_bytes, patch, test_log)


def _reconstruct(inputs: _VerifiedInputs, policy: DiagnosisSourcePolicy,
                 manager: GitRepositoryManager) -> tuple[dict[str, bytes], dict[str, bytes], dict[str, bytes]]:
    assert inputs.run.provenance is not None
    assert inputs.task.evaluation.frozen_unittest is not None
    commit = inputs.run.provenance.base_commit_used
    repository = inputs.task.repository.model_copy(update={"base_commit": commit})
    frozen_names = inputs.task.evaluation.frozen_unittest.test_files
    try:
        # Random scratch directory names are lifecycle-only, never bundle identity
        # or evidence locators. The supplied manager owns worktree creation/cleanup.
        manager.workspace_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="diagnosis-", dir=manager.workspace_root) as scratch:
            name = Path(scratch).name + "/source"
            with manager.workspace(repository, name) as workspace:
                if workspace.base_commit != commit:
                    raise DiagnosisCompilationError(DiagnosisCompilationReason.RUN_PROVENANCE_MISMATCH,
                                                    "Resolved worktree base differs from historical commit")
                base, base_roots = _collect_snapshot(workspace.path, policy, frozen_names)
                frozen = {name: _read_source(workspace.path / name, name) for name in frozen_names}
                try:
                    manager.apply_patch(workspace, inputs.patch)
                    if manager.capture_diff(workspace) != inputs.patch:
                        raise DiagnosisCompilationError(DiagnosisCompilationReason.PATCH_RECONSTRUCTION_FAILED,
                                                        "Reconstructed diff differs from canonical historical patch")
                except (RepositoryError, UnicodeError) as error:
                    raise DiagnosisCompilationError(DiagnosisCompilationReason.PATCH_RECONSTRUCTION_FAILED,
                                                    "Unable to apply/capture historical patch") from error
                candidate, candidate_roots = _collect_snapshot(workspace.path, policy, frozen_names)
                missing = set(policy.production_roots) - base_roots - candidate_roots
                if missing:
                    raise DiagnosisCompilationError(DiagnosisCompilationReason.SOURCE_UNAVAILABLE,
                                                    f"Production roots absent in both states: {sorted(missing)}")
                return base, candidate, frozen
    except (OSError, RepositoryError) as error:
        raise DiagnosisCompilationError(DiagnosisCompilationReason.SOURCE_UNAVAILABLE,
                                        "Unable to reconstruct or clean historical source worktree") from error


def _descriptor(data: bytes, kind: EvidenceKind, owner: EvidenceOwner, *,
                state: EvidenceSourceState | None = None, path: str | None = None) -> dict:
    content = data.decode("utf-8")
    lines = content.count("\n") + int(bool(content) and not content.endswith("\n"))
    return dict(kind=kind, owner=owner, artifact_sha256=_sha(data), path=path,
                source_state=state, start_line=1 if content else None,
                end_line=lines if content else None, content=content)


def compile_diagnosis_evidence(
    task_path: str | Path,
    run_id: str,
    *,
    benchmark_definition_sha256: str,
    expected_task_contract_sha256: str,
    source_policy: DiagnosisSourcePolicy,
    max_bundle_json_bytes: int,
    artifact_store: FilesystemArtifactStore,
    repository_manager: GitRepositoryManager,
) -> DiagnosisEvidenceBundle:
    """Compile complete Blind evidence from verified historical inputs, in memory.

    Caller supplies frozen benchmark/task identities and a source policy. The
    final compact JSON byte bound is a PatchBench eligibility limit, not a model
    token limit. No truncation or alternate source selection is permitted.
    Original artifact contents are preserved exactly, including any absolute
    paths already present. Compiler-generated structure must not introduce
    host-specific paths; EvidenceItem.path is a repo-relative POSIX identity.
    Given identical frozen input bytes, benchmark identities, historical Git
    state, and source policy, compilation is host-independent and deterministic.
    """
    TypeAdapter(Sha256Hex).validate_python(benchmark_definition_sha256)
    if type(max_bundle_json_bytes) is not int or max_bundle_json_bytes <= 0:
        raise ValueError("max_bundle_json_bytes must be a positive integer")
    # Revalidate/copy once so all phases share one policy value.
    policy = DiagnosisSourcePolicy.model_validate(source_policy.model_dump())
    inputs = _verify_inputs(Path(task_path), run_id, expected_task_contract_sha256, artifact_store)
    base, candidate, frozen = _reconstruct(inputs, policy, repository_manager)
    run, task = inputs.run, inputs.task
    assert run.provenance is not None
    assert task.evaluation.frozen_unittest is not None
    descriptors = [
        _descriptor(inputs.task_bytes, EvidenceKind.TASK_CONTRACT, EvidenceOwner.BENCHMARK),
        _descriptor(inputs.patch.encode("utf-8"), EvidenceKind.CANONICAL_PATCH, EvidenceOwner.SUBJECT,
                    path="patch.diff"),
        _descriptor(inputs.test_log.encode("utf-8"), EvidenceKind.EVALUATION_OUTPUT, EvidenceOwner.SUBJECT,
                    path="test.log"),
    ]
    for files, kind, owner, state in (
        (base, EvidenceKind.PRODUCTION_SOURCE, EvidenceOwner.BENCHMARK, EvidenceSourceState.BASE),
        (candidate, EvidenceKind.PRODUCTION_SOURCE, EvidenceOwner.SUBJECT, EvidenceSourceState.CANDIDATE),
        (frozen, EvidenceKind.FROZEN_TEST, EvidenceOwner.BENCHMARK, EvidenceSourceState.FROZEN),
    ):
        descriptors.extend(_descriptor(data, kind, owner, state=state, path=path)
                           for path, data in files.items())
    descriptors.sort(key=lambda item: (item["owner"].value, item["kind"].value,
        item["source_state"].value if item["source_state"] else "", item["path"] or ""))
    items = [EvidenceItem(evidence_id=f"E{index:03d}", **item)
             for index, item in enumerate(descriptors, start=1)]
    provenance = BundleProvenance(subject=SubjectProvenance(
        canonical_patch_sha256=_sha(inputs.patch.encode("utf-8")),
        evaluation_log_sha256=_sha(inputs.test_log.encode("utf-8")),
        task_contract_sha256=_sha(inputs.task_bytes),
        base_source_snapshot_sha256=_snapshot_hash(base),
        candidate_source_snapshot_sha256=_snapshot_hash(candidate),
        frozen_tests_snapshot_sha256=_snapshot_hash(frozen, order=task.evaluation.frozen_unittest.test_files),
        benchmark_definition_sha256=benchmark_definition_sha256,
    ))
    identity = dict(schema_version=1, mode=DiagnosisMode.BLIND.value, subject_run_id=run.run_id,
                    benchmark_definition_sha256=benchmark_definition_sha256,
                    task_fingerprint_sha256=run.provenance.task_fingerprint_sha256,
                    source_snapshot_policy=_policy_identity(policy))
    bundle = DiagnosisEvidenceBundle(**identity, bundle_id="blind-" + _sha(_canonical_json(identity)),
        bundle_sha256="0" * 64, task_id=task.id, base_commit=run.provenance.base_commit_used,
        official_evaluation_passed=run.evaluation_passed, agent_status=run.agent.status,
        evidence_items=items, provenance=provenance)
    bundle.bundle_sha256 = compute_bundle_sha256(bundle)
    size = len(_canonical_json(bundle.model_dump(mode="json")))
    if size > max_bundle_json_bytes:
        raise DiagnosisCompilationError(DiagnosisCompilationReason.BUNDLE_TOO_LARGE,
                                        f"Complete bundle is {size} bytes; bound is {max_bundle_json_bytes}")
    return bundle
