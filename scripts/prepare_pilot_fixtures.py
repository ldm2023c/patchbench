"""Prepare disposable pilot Git repositories from tracked source templates.

Run from the project root: python -m scripts.prepare_pilot_fixtures
Git plumbing creates fixture history only; the parent index is never used.
"""
import os
from pathlib import Path
import shutil
import subprocess

from patchbench.config.task_loader import load_task
from scripts.prepare_example_fixture import (
    COMMIT_ENVIRONMENT, FixturePreparationError, PROJECT_ROOT, git as _example_git,
)

PILOTS = ("config_precedence", "roundtrip")
PILOT_ROOT = PROJECT_ROOT / "fixtures" / "pilot"



def git(fixture: Path, *arguments: str) -> str:
    """Keep pilot Git commands independent of inherited repository/config state."""
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("GIT_")}
    environment.update(COMMIT_ENVIRONMENT)
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_CONFIG_SYSTEM=os.devnull)
    return _example_git(fixture, *arguments, environment=environment)

def template_files(source: Path) -> list[Path]:
    """Only the deliberately small fixture source surface enters its commit."""
    return sorted([source / ".gitignore", source / "README.md", *source.rglob("*.py")])


def prepare_fixture(source: Path, destination: Path, expected_commit: str) -> str:
    """Create missing runtime state or refuse to overwrite existing dirty state."""
    if destination.exists():
        if not (destination / ".git").is_dir():
            raise FixturePreparationError(f"Not a prepared fixture: {destination}")
    else:
        destination.mkdir(parents=True)
        for path in template_files(source):
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        git(destination, "init", "--quiet", "--initial-branch=main",
            "--object-format=sha1", "--template=")
        git(destination, "config", "core.autocrlf", "false")
        # Hash raw bytes, fix file modes, and avoid commit hooks/signing/config.
        for path in template_files(source):
            relative = path.relative_to(source).as_posix()
            blob = git(destination, "hash-object", "-w", "--no-filters", relative)
            git(destination, "update-index", "--add", "--cacheinfo", f"100644,{blob},{relative}")
        tree = git(destination, "write-tree")
        commit = git(destination, "-c", "commit.gpgsign=false", "commit-tree", tree,
                     "-m", "fixture: pilot buggy base")
        git(destination, "update-ref", "HEAD", commit)
    if git(destination, "rev-parse", "--show-toplevel") != str(destination.resolve()):
        raise FixturePreparationError(f"Not a fixture repository root: {destination}")
    if git(destination, "status", "--porcelain"):
        raise FixturePreparationError(f"Fixture repository is not clean: {destination}")
    actual = git(destination, "rev-parse", "HEAD")
    if actual != expected_commit:
        raise FixturePreparationError(f"Fixture HEAD mismatch: expected {expected_commit}, found {actual}; state left unchanged")
    expected_paths = {p.relative_to(source).as_posix() for p in template_files(source)}
    if set(git(destination, "ls-files").splitlines()) != expected_paths:
        raise FixturePreparationError("Fixture file manifest differs from template")
    for relative in expected_paths:
        if (source / relative).read_bytes() != (destination / relative).read_bytes():
            raise FixturePreparationError(f"Fixture template differs: {relative}")
    return actual


def main() -> None:
    try:
        for name in PILOTS:
            task = load_task(PROJECT_ROOT / "tasks" / "pilot" / name / "task.yaml")
            destination = PILOT_ROOT / ".prepared" / name
            if Path(task.repository.path) != destination:
                raise FixturePreparationError(f"Unexpected task repository: {task.repository.path}")
            commit = prepare_fixture(PILOT_ROOT / name, destination, task.repository.base_commit)
            print(f"{name}: {commit}")
    except (FixturePreparationError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Unable to prepare pilot fixtures: {error}") from error


if __name__ == "__main__":
    main()
