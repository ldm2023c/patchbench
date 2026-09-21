"""Orchestrate one deterministic local PatchBench Run."""

from pathlib import Path
from time import perf_counter
from uuid import uuid4

from patchbench.agents.base import Agent, AgentRunRequest
from patchbench.config.task_loader import load_task
from patchbench.domain.models import (
    AgentExecutionMetadata,
    RunProvenance,
    RunRecord,
    RunStatus,
    TaskSpec,
    AgentIdentityBinding,
)
from patchbench.domain.provenance import compute_task_fingerprint
from patchbench.domain.patch_evidence import summarize_patch
from patchbench.domain.evaluation_evidence import (
    render_evaluation_log, summarize_evaluation_log,
)
from patchbench.application.evaluation import evaluate_patch
from patchbench.repository.git_repository import GitRepositoryManager
from patchbench.sandbox.base import Sandbox
from patchbench.storage.filesystem import FilesystemArtifactStore


def run_task(
    task_path: str | Path,
    *,
    agent: Agent,
    agent_name: str,
    agent_timeout_seconds: float | None = None,
    requested_model: str | None = None,
    agent_identity_binding: AgentIdentityBinding | None = None,
    workspace_root: Path | None = None,
    results_root: Path | None = None,
    sandbox: Sandbox | None = None,
) -> RunRecord:
    """Execute one Task with an agent in an isolated local Git worktree."""

    started = perf_counter()
    task = load_task(task_path)
    return _execute_single_run(
        task,
        agent=agent,
        agent_name=agent_name,
        agent_timeout_seconds=agent_timeout_seconds,
        requested_model=requested_model,
        agent_identity_binding=agent_identity_binding,
        workspace_root=workspace_root,
        results_root=results_root,
        sandbox=sandbox,
        started_at=started,
    )


def _execute_single_run(
    task: TaskSpec,
    *,
    agent: Agent,
    agent_name: str,
    agent_timeout_seconds: float | None = None,
    requested_model: str | None = None,
    agent_identity_binding: AgentIdentityBinding | None = None,
    workspace_root: Path | None = None,
    results_root: Path | None = None,
    sandbox: Sandbox | None = None,
    started_at: float | None = None,
) -> RunRecord:
    """Execute one already-loaded Task through the existing Run lifecycle."""

    started = perf_counter() if started_at is None else started_at
    run_id = uuid4().hex
    repository_manager = GitRepositoryManager(
        workspace_root or Path.cwd() / ".workspaces"
    )
    artifact_store = FilesystemArtifactStore(results_root or Path.cwd() / "results")

    with repository_manager.workspace(task.repository, run_id) as workspace:
        provenance = RunProvenance(
            base_commit_used=workspace.base_commit,
            task_fingerprint_sha256=compute_task_fingerprint(
                task, base_commit_used=workspace.base_commit,
            ),
            evaluation_command=task.evaluation.command,
            evaluation_timeout_seconds=task.evaluation.timeout_seconds,
            evaluation_backend="host" if sandbox is None else "docker",
        )
        effective_prompt = task.task.prompt
        agent_result = agent.run(
            AgentRunRequest(
                workspace=workspace.path,
                prompt=effective_prompt,
                timeout_seconds=agent_timeout_seconds,
            )
        )
        patch = repository_manager.capture_diff(workspace)
        evaluation_result = evaluate_patch(
            repository_manager, workspace, task.evaluation, patch, sandbox=sandbox,
        )
        test_log = render_evaluation_log(evaluation_result, task.evaluation.command)
        patch_summary = summarize_patch(patch)
        evaluation_evidence = summarize_evaluation_log(test_log)
        artifact_paths = artifact_store.create_paths(run_id)
        record = RunRecord(
            run_id=run_id,
            task_id=task.id,
            status=(
                RunStatus.PASSED if evaluation_result.passed else RunStatus.FAILED
            ),
            evaluation_passed=evaluation_result.passed,
            duration_seconds=perf_counter() - started,
            agent=AgentExecutionMetadata(
                name=agent_name,
                backend="host",
                status=agent_result.status,
                exit_code=agent_result.exit_code,
                duration_seconds=agent_result.duration_seconds,
                timeout_seconds=agent_timeout_seconds,
                requested_model=requested_model,
                identity_binding=agent_identity_binding,
            ),
            artifacts=artifact_paths,
            provenance=provenance,
            patch_summary=patch_summary,
            evaluation_evidence=evaluation_evidence,
        )
        artifact_store.persist(
            record,
            agent_result,
            evaluation_result,
            task.evaluation.command,
            patch,
            effective_prompt,
        )

    return record
