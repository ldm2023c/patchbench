from patchbench.agents.fake import FakeAgent
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
        result = FakeAgent().run(workspace.path, task)
        patch = manager.capture_diff(workspace)

        assert result.succeeded is True
        assert "subtraction bug" in result.log
        assert "return a + b" in (workspace.path / "calculator.py").read_text()
        assert "-    return a - b" in patch
        assert "+    return a + b" in patch
