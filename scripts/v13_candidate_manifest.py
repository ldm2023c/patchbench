"""Build and verify the PatchBench V1.3 candidate benchmark identity."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from patchbench.config.task_loader import TaskLoadError, load_task
from patchbench.domain.benchmark import (
    BenchmarkCandidateFile,
    BenchmarkCandidateManifest,
    BenchmarkCandidateTask,
    BenchmarkDesignManifest,
    compute_benchmark_candidate_sha256,
    compute_benchmark_design_sha256,
)
from patchbench.domain.provenance import compute_task_fingerprint
from scripts.prepare_pilot_fixtures import (
    FixturePreparationError,
    PROJECT_ROOT,
    git,
    prepare_fixture,
)


DESIGN_PATH = Path("tasks/reliability/v1.3-design.json")
CANDIDATE_PATH = Path("tasks/reliability/v1.3-candidate.json")
ACCEPTED_DESIGN_SHA256 = "dc48fdac627abe9fcd95303d3042b5f0c822abbb0bb53a4dfba17dcc2f99f931"
RESERVED_COMPONENTS = {
    ".git", ".patchbench-eval", ".prepared", "reference", "references",
    "solution", "solutions", "gold", "answer", "answers", "expected_patch",
    "reference_patch",
}


class BenchmarkCandidateIntegrityError(RuntimeError):
    """Current repository state does not match a valid candidate identity."""


def _load_model(path: Path, model_type, category: str):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return model_type.model_validate(data)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise BenchmarkCandidateIntegrityError(
            f"Unable to load {category} '{path}': {error}"
        ) from error


def load_design(project_root: Path = PROJECT_ROOT) -> BenchmarkDesignManifest:
    """Load the checked-in design and require its accepted identity."""
    path = project_root / DESIGN_PATH
    design = _load_model(path, BenchmarkDesignManifest, "benchmark design")
    actual = compute_benchmark_design_sha256(design)
    if actual != ACCEPTED_DESIGN_SHA256:
        raise BenchmarkCandidateIntegrityError(
            f"Design SHA mismatch: expected {ACCEPTED_DESIGN_SHA256}, found {actual}"
        )
    return design


def load_candidate_manifest(
    project_root: Path = PROJECT_ROOT,
) -> BenchmarkCandidateManifest:
    """Load and validate the checked-in candidate artifact."""
    return _load_model(
        project_root / CANDIDATE_PATH, BenchmarkCandidateManifest, "candidate manifest"
    )


def _audit_tracked_paths(task_id: str, tracked_paths: list[str]) -> None:
    for path_text in tracked_paths:
        path = PurePosixPath(path_text)
        for component in path.parts:
            normalized = component.casefold()
            stem = PurePosixPath(component).stem.casefold()
            if normalized in RESERVED_COMPONENTS or stem in RESERVED_COMPONENTS:
                raise BenchmarkCandidateIntegrityError(
                    f"Task '{task_id}' contains reserved artifact path '{path_text}'"
                )


def build_candidate_manifest(
    project_root: Path = PROJECT_ROOT,
    *,
    temporary_root: Path | None = None,
) -> BenchmarkCandidateManifest:
    """Rebuild candidate identity from checked-in TaskSpecs and fixture templates."""
    project_root = project_root.resolve()
    design = load_design(project_root)
    fixture_root = project_root / "fixtures/reliability"
    task_root = project_root / "tasks/reliability"

    temp_kwargs = {"prefix": "patchbench-v13-candidate-"}
    if temporary_root is not None:
        temporary_root.mkdir(parents=True, exist_ok=True)
        temp_kwargs["dir"] = str(temporary_root)

    candidate_tasks = []
    try:
        with TemporaryDirectory(**temp_kwargs) as temporary:
            preparation_root = Path(temporary)
            for index, profile in enumerate(design.tasks):
                task_id = profile.task_id
                relative_spec = Path("tasks/reliability") / task_id / "task.yaml"
                spec_path = project_root / relative_spec
                try:
                    task = load_task(spec_path)
                except TaskLoadError as error:
                    raise BenchmarkCandidateIntegrityError(
                        f"Task '{task_id}' TaskSpec load failed: {error}"
                    ) from error
                if task.id != task_id:
                    raise BenchmarkCandidateIntegrityError(
                        f"Task '{task_id}' TaskSpec ID mismatch: found '{task.id}'"
                    )

                prepared = preparation_root / f"{index:02d}-{task_id}"
                try:
                    prepare_fixture(
                        fixture_root / task_id, prepared, task.repository.base_commit
                    )
                except FixturePreparationError as error:
                    raise BenchmarkCandidateIntegrityError(
                        f"Task '{task_id}' deterministic fixture mismatch: {error}"
                    ) from error
                resolved = git(prepared, "rev-parse", "--verify", "HEAD^{commit}")
                if resolved != task.repository.base_commit:
                    raise BenchmarkCandidateIntegrityError(
                        f"Task '{task_id}' resolved base commit mismatch: "
                        f"TaskSpec has {task.repository.base_commit}, fixture has {resolved}"
                    )
                if git(prepared, "status", "--porcelain"):
                    raise BenchmarkCandidateIntegrityError(
                        f"Task '{task_id}' prepared fixture is dirty"
                    )

                tracked_paths = git(prepared, "ls-files").splitlines()
                _audit_tracked_paths(task_id, tracked_paths)
                frozen = task.evaluation.frozen_unittest
                if frozen is None or frozen.version != 1:
                    raise BenchmarkCandidateIntegrityError(
                        f"Task '{task_id}' frozen evaluator contract must be version 1"
                    )
                if len(frozen.test_files) != 1:
                    raise BenchmarkCandidateIntegrityError(
                        f"Task '{task_id}' must declare exactly one official evaluator file"
                    )
                official_files = []
                for name in frozen.test_files:
                    if PurePosixPath(name).parent != PurePosixPath("."):
                        raise BenchmarkCandidateIntegrityError(
                            f"Task '{task_id}' official evaluator path is not root-level: {name}"
                        )
                    if name not in tracked_paths:
                        raise BenchmarkCandidateIntegrityError(
                            f"Task '{task_id}' official evaluator file is not tracked: {name}"
                        )
                    official_path = prepared / name
                    try:
                        mode = official_path.lstat().st_mode
                    except OSError as error:
                        raise BenchmarkCandidateIntegrityError(
                            f"Task '{task_id}' official evaluator file is missing: {name}"
                        ) from error
                    if not stat.S_ISREG(mode):
                        raise BenchmarkCandidateIntegrityError(
                            f"Task '{task_id}' official evaluator file is not regular: {name}"
                        )
                    official_files.append(BenchmarkCandidateFile(
                        path=name,
                        sha256=hashlib.sha256(official_path.read_bytes()).hexdigest(),
                    ))

                candidate_tasks.append(BenchmarkCandidateTask(
                    task_id=task_id,
                    task_spec_path=relative_spec.as_posix(),
                    task_spec_sha256=hashlib.sha256(spec_path.read_bytes()).hexdigest(),
                    task_fingerprint_sha256=compute_task_fingerprint(
                        task, base_commit_used=resolved
                    ),
                    resolved_base_commit=resolved,
                    official_evaluator_files=tuple(official_files),
                ))
    except (OSError, subprocess.CalledProcessError) as error:
        raise BenchmarkCandidateIntegrityError(
            f"Unable to build candidate fixture state: {error}"
        ) from error

    return BenchmarkCandidateManifest(
        schema_version=1,
        suite_id=design.suite_id,
        design_sha256=compute_benchmark_design_sha256(design),
        tasks=tuple(candidate_tasks),
    )


def _first_mismatch(
    checked: BenchmarkCandidateManifest, expected: BenchmarkCandidateManifest
) -> str:
    if checked.suite_id != expected.suite_id:
        return "suite ID mismatch"
    if checked.design_sha256 != expected.design_sha256:
        return "design SHA mismatch"
    checked_ids = tuple(task.task_id for task in checked.tasks)
    expected_ids = tuple(task.task_id for task in expected.tasks)
    if checked_ids != expected_ids:
        return "candidate task set/order mismatch"
    for actual, wanted in zip(checked.tasks, expected.tasks, strict=True):
        for field, label in (
            ("task_spec_path", "TaskSpec path"),
            ("task_spec_sha256", "TaskSpec file SHA"),
            ("task_fingerprint_sha256", "semantic task fingerprint"),
            ("resolved_base_commit", "resolved base commit"),
            ("official_evaluator_files", "official evaluator file identity"),
        ):
            if getattr(actual, field) != getattr(wanted, field):
                return f"task '{actual.task_id}' {label} mismatch"
    return "candidate manifest mismatch"


def verify_candidate_manifest(
    candidate: BenchmarkCandidateManifest,
    project_root: Path = PROJECT_ROOT,
    *,
    temporary_root: Path | None = None,
) -> BenchmarkCandidateManifest:
    """Fail closed unless candidate exactly matches rebuilt repository truth."""
    expected = build_candidate_manifest(project_root, temporary_root=temporary_root)
    if candidate != expected:
        raise BenchmarkCandidateIntegrityError(_first_mismatch(candidate, expected))
    return candidate


def write_candidate_manifest(
    candidate: BenchmarkCandidateManifest, project_root: Path = PROJECT_ROOT
) -> None:
    """Write deterministic, reviewable JSON only when explicitly requested."""
    path = project_root / CANDIDATE_PATH
    payload = json.dumps(candidate.model_dump(mode="json"), indent=2, ensure_ascii=False)
    path.write_text(payload + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify the checked-in manifest")
    mode.add_argument("--write", action="store_true", help="intentionally rewrite the manifest")
    arguments = parser.parse_args()
    try:
        if arguments.write:
            candidate = build_candidate_manifest()
            write_candidate_manifest(candidate)
        else:
            candidate = load_candidate_manifest()
            verify_candidate_manifest(candidate)
    except BenchmarkCandidateIntegrityError as error:
        raise SystemExit(f"Candidate integrity failure: {error}") from error
    print(f"candidate_sha256={compute_benchmark_candidate_sha256(candidate)}")


if __name__ == "__main__":
    main()
