import subprocess
import sys
from pathlib import Path

import yaml


BUGGY_CALCULATOR = """\
def add(a: int, b: int) -> int:
    return a - b
"""

CALCULATOR_TEST = """\
from calculator import add


def test_adds_two_numbers() -> None:
    assert add(2, 3) == 5
"""


def git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def create_fixture_repository(parent: Path) -> tuple[Path, str]:
    repository = parent / "fixture_repo"
    repository.mkdir()
    (repository / "calculator.py").write_text(BUGGY_CALCULATOR, encoding="utf-8")
    (repository / "test_calculator.py").write_text(
        CALCULATOR_TEST, encoding="utf-8"
    )

    git(repository, "init", "--quiet", "--initial-branch=main")
    git(repository, "add", "calculator.py", "test_calculator.py")
    git(
        repository,
        "-c",
        "user.name=PatchBench Test",
        "-c",
        "user.email=test@patchbench.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        "fixture base",
    )
    return repository, git(repository, "rev-parse", "HEAD")


def write_run_task(
    parent: Path,
    repository: Path,
    base_commit: str,
    *,
    command: str | None = None,
) -> Path:
    task_path = parent / "run-task.yaml"
    task_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "id": "calculator_bug",
                "repository": {
                    "type": "local",
                    "path": str(repository),
                    "base_commit": base_commit,
                },
                "task": {"prompt": "Fix the calculator bug."},
                "evaluation": {
                    "command": command or f"{sys.executable} -m pytest -q",
                    "timeout_seconds": 30,
                },
                "metadata": {"language": "python"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return task_path
