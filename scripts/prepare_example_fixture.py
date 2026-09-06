"""Create the deterministic Git commit used by the built-in example Task."""

import os
from pathlib import Path
import subprocess

from patchbench.config.task_loader import load_task


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_PATH = PROJECT_ROOT / "tasks" / "example" / "task.yaml"
COMMIT_ENVIRONMENT = {
    "GIT_AUTHOR_NAME": "PatchBench Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@patchbench.invalid",
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
    "GIT_COMMITTER_NAME": "PatchBench Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@patchbench.invalid",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
}


class FixturePreparationError(RuntimeError):
    """Raised when existing fixture state cannot be safely prepared."""


def git(
    fixture: Path,
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> str:
    completed = subprocess.run(
        ["git", "-C", str(fixture), *arguments],
        capture_output=True,
        text=True,
        check=True,
        env=environment,
    )
    return completed.stdout.strip()


def prepare_fixture(fixture: Path, expected_commit: str) -> str:
    """Prepare a missing fixture repository or verify existing Git metadata."""

    created_repository = not (fixture / ".git").exists()
    if created_repository:
        subprocess.run(
            [
                "git",
                "-C",
                str(fixture),
                "init",
                "--quiet",
                "--initial-branch=main",
                "--object-format=sha1",
                "--template=",
            ],
            check=True,
        )
        git(fixture, "config", "core.autocrlf", "false")
        git(fixture, "add", "calculator.py", "test_calculator.py")
        git(
            fixture,
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "fixture: add calculator bug",
            environment={**os.environ, **COMMIT_ENVIRONMENT},
        )

    if git(fixture, "status", "--porcelain"):
        raise FixturePreparationError(f"Fixture repository is not clean: {fixture}")

    actual_commit = git(fixture, "rev-parse", "HEAD")
    if actual_commit != expected_commit:
        if created_repository:
            action = "Check that the tracked fixture files match the example Task."
        else:
            action = (
                "Existing Git metadata was left unchanged. Move or remove its .git "
                "directory only if safe, then rerun this script."
            )
        raise FixturePreparationError(
            f"Fixture HEAD mismatch: expected {expected_commit}, found "
            f"{actual_commit}. {action}"
        )

    return actual_commit


def main() -> None:
    task = load_task(TASK_PATH)
    fixture = Path(task.repository.path)

    try:
        commit = prepare_fixture(fixture, task.repository.base_commit)
    except (FixturePreparationError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Unable to prepare example fixture: {error}") from error

    print(commit)


if __name__ == "__main__":
    main()
