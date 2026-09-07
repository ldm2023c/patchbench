from pathlib import Path

import pytest

from patchbench.agents.base import (
    Agent,
    AgentInfrastructureError,
    AgentRunRequest,
    AgentRunStatus,
    AgentSetupError,
)
from patchbench.agents.fake import FakeAgent, FakeAgentError
from patchbench.domain.models import RepositoryConfig, TaskSpec
from patchbench.repository.git_repository import GitRepositoryManager
from tests.helpers import create_fixture_repository


def test_fake_agent_makes_expected_change_and_patch(tmp_path) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    manager = GitRepositoryManager(tmp_path / "workspaces")
    task = TaskSpec.model_validate(
        {
            "schema_version": 1,
            "id": "calculator_bug",
            "repository": {
                "type": "local",
                "path": str(source),
                "base_commit": base_commit,
            },
            "task": {"prompt": "Fix the bug."},
            "evaluation": {"command": "pytest -q", "timeout_seconds": 30},
        }
    )

    with manager.workspace(task.repository, "agent-run") as workspace:
        agent: Agent = FakeAgent()
        result = agent.run(
            AgentRunRequest(
                workspace=workspace.path,
                prompt=task.task.prompt,
                timeout_seconds=None,
            )
        )
        patch = manager.capture_diff(workspace)

        assert result.status is AgentRunStatus.COMPLETED
        assert result.exit_code == 0
        assert result.duration_seconds == 0.0
        assert result.stderr == ""
        assert result.stdout == (
            "FakeAgent processed task.\n"
            "Replaced the known subtraction bug in calculator.py with addition.\n"
        )
        assert task.id not in result.stdout
        assert "return a + b" in (workspace.path / "calculator.py").read_text()
        assert "-    return a - b" in patch
        assert "+    return a + b" in patch


def test_fake_agent_fixture_mismatch_is_a_setup_error(tmp_path) -> None:
    (tmp_path / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )

    with pytest.raises(FakeAgentError) as raised:
        FakeAgent().run(AgentRunRequest(tmp_path, "Fix the bug."))

    assert isinstance(raised.value, AgentSetupError)
    assert not isinstance(raised.value, AgentInfrastructureError)


def test_fake_agent_read_error_is_an_infrastructure_error(tmp_path) -> None:
    missing_workspace = tmp_path / "missing"

    with pytest.raises(AgentInfrastructureError) as raised:
        FakeAgent().run(AgentRunRequest(missing_workspace, "Fix the bug."))

    assert not isinstance(raised.value, AgentSetupError)
    assert isinstance(raised.value.__cause__, FileNotFoundError)


def test_fake_agent_write_error_is_an_infrastructure_error(
    tmp_path, monkeypatch
) -> None:
    target = tmp_path / "calculator.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    def fail_write(self: Path, *args, **kwargs) -> int:
        raise OSError("simulated write failure")

    monkeypatch.setattr(Path, "write_text", fail_write)

    with pytest.raises(AgentInfrastructureError) as raised:
        FakeAgent().run(AgentRunRequest(tmp_path, "Fix the bug."))

    assert not isinstance(raised.value, AgentSetupError)
    assert isinstance(raised.value.__cause__, OSError)
