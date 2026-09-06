from collections.abc import Sequence
import json
from pathlib import Path
import sys

import pytest

from patchbench.application.local_run import run_task
from patchbench.domain.models import RunStatus
from patchbench.sandbox.base import (
    SandboxExecResult,
    SandboxHandle,
    SandboxResourceLimits,
)
from patchbench.sandbox.docker import DockerSandboxError
from tests.helpers import create_fixture_repository, git, write_run_task


class RecordingSandbox:
    def __init__(
        self,
        *,
        exit_code: int = 0,
        error: Exception | None = None,
    ) -> None:
        self.exit_code = exit_code
        self.error = error
        self.events: list[str] = []
        self.workspace: Path | None = None
        self.saw_agent_fix = False
        self.command: list[str] | None = None
        self.timeout_seconds: float | None = None

    def create(
        self,
        workspace: Path | None = None,
        resource_limits: SandboxResourceLimits | None = None,
    ) -> SandboxHandle:
        assert workspace is not None
        self.workspace = workspace
        self.saw_agent_fix = "return a + b" in (
            workspace / "calculator.py"
        ).read_text(encoding="utf-8")
        self.events.append("create")
        return SandboxHandle(identifier="sandbox-123")

    def exec(
        self,
        handle: SandboxHandle,
        command: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> SandboxExecResult:
        self.events.append("exec")
        self.command = list(command)
        self.timeout_seconds = timeout_seconds
        assert self.workspace is not None
        (self.workspace / "evaluation-side-effect.txt").write_text(
            "created during evaluation\n",
            encoding="utf-8",
        )
        if self.error is not None:
            raise self.error
        return SandboxExecResult(
            exit_code=self.exit_code,
            stdout="sandbox evaluation",
            stderr="" if self.exit_code == 0 else "evaluation failed",
        )

    def destroy(self, handle: SandboxHandle) -> None:
        self.events.append("destroy")


def test_local_run_passes_persists_artifacts_and_preserves_source(tmp_path) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(tmp_path, source, base_commit)
    workspace_root = tmp_path / "workspaces"
    results_root = tmp_path / "results"
    source_contents = (source / "calculator.py").read_text(encoding="utf-8")
    source_status = git(source, "status", "--porcelain")

    record = run_task(
        task_path, workspace_root=workspace_root, results_root=results_root
    )

    assert record.task_id == "calculator_bug"
    assert record.status is RunStatus.PASSED
    assert record.evaluation_passed is True
    assert record.duration_seconds > 0
    assert not (workspace_root / record.run_id).exists()
    assert (source / "calculator.py").read_text(encoding="utf-8") == source_contents
    assert git(source, "status", "--porcelain") == source_status
    assert git(source, "rev-parse", "HEAD") == base_commit

    expected_artifacts = {"metadata.json", "agent.log", "test.log", "patch.diff"}
    assert {path.name for path in record.artifacts.directory.iterdir()} == expected_artifacts

    metadata = json.loads(record.artifacts.metadata.read_text(encoding="utf-8"))
    assert metadata["run_id"] == record.run_id
    assert metadata["task_id"] == record.task_id
    assert metadata["status"] == "passed"
    assert metadata["evaluation_passed"] is True
    assert metadata["duration_seconds"] == record.duration_seconds
    assert metadata["artifacts"]["directory"] == str(record.artifacts.directory)

    assert "FakeAgent processed task" in record.artifacts.agent_log.read_text()
    assert "1 passed" in record.artifacts.test_log.read_text()
    patch = record.artifacts.patch.read_text()
    assert "-    return a - b" in patch
    assert "+    return a + b" in patch


def test_local_run_records_failed_evaluation(tmp_path) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(
        tmp_path,
        source,
        base_commit,
        command=f'{sys.executable} -c "raise SystemExit(1)"',
    )

    record = run_task(
        task_path,
        workspace_root=tmp_path / "workspaces",
        results_root=tmp_path / "results",
    )

    assert record.status is RunStatus.FAILED
    assert record.evaluation_passed is False
    assert "Exit code: 1" in record.artifacts.test_log.read_text()
    assert not (tmp_path / "workspaces" / record.run_id).exists()


def test_local_run_uses_supplied_sandbox_after_capturing_agent_patch(
    tmp_path,
) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(
        tmp_path,
        source,
        base_commit,
        command='python -c "print(123)"',
    )
    workspace_root = tmp_path / "workspaces"
    sandbox = RecordingSandbox()

    record = run_task(
        task_path,
        workspace_root=workspace_root,
        results_root=tmp_path / "results",
        sandbox=sandbox,
    )

    assert record.status is RunStatus.PASSED
    assert sandbox.events == ["create", "exec", "destroy"]
    assert sandbox.workspace == workspace_root / record.run_id
    assert sandbox.saw_agent_fix
    assert sandbox.command == ["python", "-c", "print(123)"]
    assert sandbox.timeout_seconds == 30
    assert not sandbox.workspace.exists()
    patch = record.artifacts.patch.read_text(encoding="utf-8")
    assert "-    return a - b" in patch
    assert "+    return a + b" in patch
    assert "evaluation-side-effect.txt" not in patch
    assert "sandbox evaluation" in record.artifacts.test_log.read_text()


def test_local_run_records_nonzero_sandbox_evaluation(tmp_path) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(tmp_path, source, base_commit)
    sandbox = RecordingSandbox(exit_code=2)

    record = run_task(
        task_path,
        workspace_root=tmp_path / "workspaces",
        results_root=tmp_path / "results",
        sandbox=sandbox,
    )

    assert record.status is RunStatus.FAILED
    assert record.evaluation_passed is False
    assert "Exit code: 2" in record.artifacts.test_log.read_text()
    assert sandbox.events == ["create", "exec", "destroy"]


def test_local_run_cleans_sandbox_and_worktree_on_infrastructure_error(
    tmp_path,
) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(tmp_path, source, base_commit)
    workspace_root = tmp_path / "workspaces"
    error = DockerSandboxError("simulated infrastructure failure")
    sandbox = RecordingSandbox(error=error)

    with pytest.raises(DockerSandboxError) as raised:
        run_task(
            task_path,
            workspace_root=workspace_root,
            results_root=tmp_path / "results",
            sandbox=sandbox,
        )

    assert raised.value is error
    assert sandbox.events == ["create", "exec", "destroy"]
    assert sandbox.workspace is not None
    assert not sandbox.workspace.exists()
    assert git(source, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert not (tmp_path / "results").exists()


def test_relative_repository_path_is_resolved_from_task_directory(
    tmp_path, monkeypatch
) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    task_directory = tmp_path / "task-definitions"
    task_directory.mkdir()
    task_path = write_run_task(task_directory, source, base_commit)
    task_path.write_text(
        task_path.read_text().replace(str(source), "../fixture_repo"),
        encoding="utf-8",
    )
    different_cwd = tmp_path / "different-working-directory"
    different_cwd.mkdir()
    monkeypatch.chdir(different_cwd)

    record = run_task(
        task_path,
        workspace_root=tmp_path / "workspaces",
        results_root=tmp_path / "results",
    )

    assert record.status is RunStatus.PASSED
    assert git(source, "status", "--porcelain") == ""
