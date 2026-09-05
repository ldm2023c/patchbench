from pathlib import Path

from typer.testing import CliRunner

from patchbench.cli import app
from tests.helpers import create_fixture_repository, git, write_run_task
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


def test_run_with_fake_agent_succeeds(tmp_path: Path, monkeypatch) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(tmp_path, source, base_commit)
    source_contents = (source / "calculator.py").read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app, ["run", "--task", str(task_path), "--agent", "fake"]
    )

    assert result.exit_code == 0
    assert "Task ID:   calculator_bug" in result.output
    assert "Result:    PASS" in result.output
    assert "Artifacts:" in result.output
    assert (source / "calculator.py").read_text(encoding="utf-8") == source_contents
    assert git(source, "status", "--porcelain") == ""
    assert list((tmp_path / "results").iterdir())
    assert list((tmp_path / ".workspaces").iterdir()) == []
