from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from patchbench.agents.base import AgentRunStatus
from patchbench.agents.fake import FakeAgent
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
    monkeypatch.setattr(
        "patchbench.cli.DockerSandbox",
        lambda: pytest.fail("DockerSandbox must not be created by default"),
    )

    result = runner.invoke(
        app, ["run", "--task", str(task_path), "--agent", "fake"]
    )

    assert result.exit_code == 0
    assert "Task ID:   calculator_bug" in result.output
    assert "Agent:     COMPLETED" in result.output
    assert "Result:    PASS" in result.output
    assert "Artifacts:" in result.output
    assert (source / "calculator.py").read_text(encoding="utf-8") == source_contents
    assert git(source, "status", "--porcelain") == ""
    assert list((tmp_path / "results").iterdir())
    assert list((tmp_path / ".workspaces").iterdir()) == []


def test_run_docker_flag_supplies_docker_sandbox(tmp_path: Path, monkeypatch) -> None:
    sandbox = object()
    received: dict[str, object] = {}

    def fake_run_task(
        task_path: Path,
        *,
        agent,
        agent_name,
        agent_timeout_seconds=None,
        requested_model=None,
        sandbox=None,
    ):
        received["task_path"] = task_path
        received["agent"] = agent
        received["agent_name"] = agent_name
        received["agent_timeout_seconds"] = agent_timeout_seconds
        received["requested_model"] = requested_model
        received["sandbox"] = sandbox
        return SimpleNamespace(
            run_id="run-123",
            task_id="example_bug",
            agent=SimpleNamespace(status=AgentRunStatus.COMPLETED),
            evaluation_passed=True,
            artifacts=SimpleNamespace(directory=tmp_path / "results" / "run-123"),
        )

    monkeypatch.setattr("patchbench.cli.DockerSandbox", lambda: sandbox)
    monkeypatch.setattr("patchbench.cli.run_task", fake_run_task)
    task_path = tmp_path / "task.yaml"

    result = runner.invoke(
        app,
        ["run", "--task", str(task_path), "--agent", "fake", "--docker"],
    )

    assert result.exit_code == 0
    assert received["task_path"] == task_path
    assert isinstance(received["agent"], FakeAgent)
    assert received["agent_name"] == "fake"
    assert received["agent_timeout_seconds"] is None
    assert received["requested_model"] is None
    assert received["sandbox"] is sandbox
    assert "Result:    PASS" in result.output


def test_run_codex_composes_model_and_agent_timeout(
    tmp_path: Path, monkeypatch
) -> None:
    selected_agent = object()
    received: dict[str, object] = {}

    def fake_codex_adapter(*, model: str):
        received["constructed_model"] = model
        return selected_agent

    def fake_run_task(
        task_path: Path,
        *,
        agent,
        agent_name,
        agent_timeout_seconds=None,
        requested_model=None,
        sandbox=None,
    ):
        received.update(
            {
                "task_path": task_path,
                "agent": agent,
                "agent_name": agent_name,
                "agent_timeout_seconds": agent_timeout_seconds,
                "requested_model": requested_model,
                "sandbox": sandbox,
            }
        )
        return SimpleNamespace(
            run_id="run-codex",
            task_id="example_bug",
            agent=SimpleNamespace(status=AgentRunStatus.COMMAND_FAILED),
            evaluation_passed=True,
            artifacts=SimpleNamespace(directory=tmp_path / "results" / "run-codex"),
        )

    monkeypatch.setattr("patchbench.cli.CodexAdapter", fake_codex_adapter)
    monkeypatch.setattr("patchbench.cli.run_task", fake_run_task)
    task_path = tmp_path / "task.yaml"

    result = runner.invoke(
        app,
        [
            "run",
            "--task",
            str(task_path),
            "--agent",
            "codex",
            "--model",
            "test-model",
            "--agent-timeout",
            "12.5",
        ],
    )

    assert result.exit_code == 0
    assert received == {
        "constructed_model": "test-model",
        "task_path": task_path,
        "agent": selected_agent,
        "agent_name": "codex",
        "agent_timeout_seconds": 12.5,
        "requested_model": "test-model",
        "sandbox": None,
    }
    assert "Agent:     COMMAND_FAILED" in result.output
    assert "Result:    PASS" in result.output


def test_run_codex_requires_model_before_composition(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "patchbench.cli.CodexAdapter",
        lambda **kwargs: pytest.fail("CodexAdapter must not be constructed"),
    )
    monkeypatch.setattr(
        "patchbench.cli.run_task",
        lambda *args, **kwargs: pytest.fail("run_task must not be called"),
    )

    result = runner.invoke(
        app,
        ["run", "--task", str(tmp_path / "task.yaml"), "--agent", "codex"],
    )

    assert result.exit_code != 0
    assert "--model is required" in result.output


def test_run_fake_rejects_model(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--task",
            str(tmp_path / "task.yaml"),
            "--agent",
            "fake",
            "--model",
            "unused-model",
        ],
    )

    assert result.exit_code != 0
    assert "--model is only valid" in result.output


def test_run_rejects_invalid_agent_timeout(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--task",
            str(tmp_path / "task.yaml"),
            "--agent",
            "fake",
            "--agent-timeout",
            "0",
        ],
    )

    assert result.exit_code != 0
    assert "--agent-timeout must be a finite positive number" in result.output
