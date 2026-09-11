"""Replay one historical patch without invoking an Agent."""

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from patchbench.domain import EvaluationResult, ReplayRecord, RunRecord, TaskSpec
from patchbench.application.evaluation import evaluate_patch
from patchbench.repository.git_repository import GitRepositoryManager
from patchbench.sandbox.base import Sandbox


class ReplayError(ValueError):
    """Raised when supplied Replay inputs are inconsistent."""


@dataclass(frozen=True)
class ReplayExecution:
    """Completed Replay record plus evaluation evidence for persistence."""

    record: ReplayRecord
    evaluation_result: EvaluationResult


def replay_run(
    task: TaskSpec,
    source_run: RunRecord,
    patch_text: str,
    *,
    workspace_root: Path | None = None,
    sandbox: Sandbox | None = None,
) -> ReplayExecution:
    """Apply a historical patch to a fresh Task base and evaluate the result."""

    if source_run.task_id != task.id:
        raise ReplayError(
            f"Source Run task '{source_run.task_id}' does not match "
            f"Replay task '{task.id}'"
        )

    started = perf_counter()
    replay_id = uuid4().hex
    repository_manager = GitRepositoryManager(
        workspace_root or Path.cwd() / ".workspaces"
    )

    with repository_manager.workspace(task.repository, replay_id) as workspace:
        repository_manager.apply_patch(workspace, patch_text)
        evaluation_result = evaluate_patch(
            repository_manager, workspace, task.evaluation, patch_text, sandbox=sandbox,
        )
        evaluation_backend = "host" if sandbox is None else "docker"

        replay_passed = evaluation_result.passed
        record = ReplayRecord(
            replay_id=replay_id,
            source_run_id=source_run.run_id,
            task_id=task.id,
            base_commit_used=workspace.base_commit,
            evaluation_backend=evaluation_backend,
            source_evaluation_passed=source_run.evaluation_passed,
            replay_evaluation_passed=replay_passed,
            outcome_matches=source_run.evaluation_passed == replay_passed,
            duration_seconds=perf_counter() - started,
        )

    return ReplayExecution(record=record, evaluation_result=evaluation_result)
