from pathlib import Path

from typer.testing import CliRunner

from patchbench.cli import app
from tests.test_task_loader import VALID_TASK


runner = CliRunner()


def test_validate_task_succeeds(tmp_path: Path) -> None:
    task_path = tmp_path / "task.yaml"
    task_path.write_text(VALID_TASK, encoding="utf-8")

    result = runner.invoke(app, ["validate-task", str(task_path)])

    assert result.exit_code == 0
    assert "example_bug" in result.stdout
    assert "valid" in result.stdout


def test_validate_task_fails(tmp_path: Path) -> None:
    task_path = tmp_path / "task.yaml"
    task_path.write_text(
        VALID_TASK.replace("prompt: Fix the bug.", "prompt: ''"), encoding="utf-8"
    )

    result = runner.invoke(app, ["validate-task", str(task_path)])

    assert result.exit_code != 0
    assert "Error:" in result.output
    assert "prompt" in result.output
