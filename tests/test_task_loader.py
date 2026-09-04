from pathlib import Path

import pytest

from patchbench.config.task_loader import TaskLoadError, load_task


VALID_TASK = """\
schema_version: 1
id: example_bug
repository:
  type: local
  path: fixtures/example_repo
  base_commit: abc123
task:
  prompt: Fix the bug.
evaluation:
  command: pytest -q
  timeout_seconds: 120
metadata:
  language: python
"""


def write_task(tmp_path: Path, contents: str) -> Path:
    task_path = tmp_path / "task.yaml"
    task_path.write_text(contents, encoding="utf-8")
    return task_path


def test_load_valid_task(tmp_path: Path) -> None:
    task = load_task(write_task(tmp_path, VALID_TASK))

    assert task.id == "example_bug"
    assert task.repository.type == "local"
    assert task.evaluation.timeout_seconds == 120
    assert task.metadata.language == "python"


def test_rejects_malformed_yaml(tmp_path: Path) -> None:
    task_path = write_task(tmp_path, "id: [unterminated")

    with pytest.raises(TaskLoadError, match="Invalid YAML"):
        load_task(task_path)


def test_rejects_missing_required_field(tmp_path: Path) -> None:
    task_path = write_task(tmp_path, VALID_TASK.replace("id: example_bug\n", ""))

    with pytest.raises(TaskLoadError, match="Invalid task configuration") as error:
        load_task(task_path)

    assert "id" in str(error.value)


def test_rejects_unknown_configuration_field(tmp_path: Path) -> None:
    task_path = write_task(tmp_path, f"{VALID_TASK}unknown_field: typo\n")

    with pytest.raises(TaskLoadError, match="unknown_field"):
        load_task(task_path)


def test_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    task_path = write_task(
        tmp_path, VALID_TASK.replace("schema_version: 1", "schema_version: 2")
    )

    with pytest.raises(TaskLoadError, match="schema_version"):
        load_task(task_path)


@pytest.mark.parametrize(
    ("original", "replacement", "field"),
    [
        ("id: example_bug", "id: '   '", "id"),
        ("prompt: Fix the bug.", "prompt: '   '", "prompt"),
    ],
)
def test_rejects_blank_required_text(
    tmp_path: Path, original: str, replacement: str, field: str
) -> None:
    task_path = write_task(tmp_path, VALID_TASK.replace(original, replacement))

    with pytest.raises(TaskLoadError, match=field):
        load_task(task_path)


@pytest.mark.parametrize("timeout", [0, -1])
def test_rejects_non_positive_timeout(tmp_path: Path, timeout: int) -> None:
    task_path = write_task(
        tmp_path,
        VALID_TASK.replace("timeout_seconds: 120", f"timeout_seconds: {timeout}"),
    )

    with pytest.raises(TaskLoadError, match="timeout_seconds"):
        load_task(task_path)
