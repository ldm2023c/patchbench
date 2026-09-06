"""Orchestrate one deterministic local PatchBench Run."""

from pathlib import Path
from time import perf_counter
from uuid import uuid4

from patchbench.agents.fake import FakeAgent
from patchbench.config.task_loader import load_task
from patchbench.domain.models import RunRecord, RunStatus
from patchbench.evaluators.command import CommandEvaluator
from patchbench.evaluators.sandbox import SandboxCommandEvaluator
from patchbench.repository.git_repository import GitRepositoryManager
from patchbench.sandbox.base import Sandbox, sandbox_scope
from patchbench.storage.filesystem import FilesystemArtifactStore


def run_task(
    task_path: str | Path,
    *,
    workspace_root: Path | None = None,
    results_root: Path | None = None,
    sandbox: Sandbox | None = None,
) -> RunRecord:
    """Execute one Task with FakeAgent in an isolated local Git worktree."""

    started = perf_counter()
    task = load_task(task_path)
    run_id = uuid4().hex
    repository_manager = GitRepositoryManager(
        workspace_root or Path.cwd() / ".workspaces"
    )
    artifact_store = FilesystemArtifactStore(results_root or Path.cwd() / "results")

    with repository_manager.workspace(task.repository, run_id) as workspace:
        agent_result = FakeAgent().run(workspace.path, task)
        patch = repository_manager.capture_diff(workspace)
        if sandbox is None:
            evaluation_result = CommandEvaluator().evaluate(
                workspace.path, task.evaluation
            )
        else:
            with sandbox_scope(sandbox, workspace=workspace.path) as handle:
                evaluation_result = SandboxCommandEvaluator(sandbox).evaluate(
                    handle, task.evaluation
                )
        artifact_paths = artifact_store.create_paths(run_id)
        record = RunRecord(
            run_id=run_id,
            task_id=task.id,
            status=(
                RunStatus.PASSED if evaluation_result.passed else RunStatus.FAILED
            ),
            evaluation_passed=evaluation_result.passed,
            duration_seconds=perf_counter() - started,
            artifacts=artifact_paths,
        )
        artifact_store.persist(
            record,
            agent_result,
            evaluation_result,
            task.evaluation.command,
            patch,
        )

    return record
