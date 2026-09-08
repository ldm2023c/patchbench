from collections.abc import Sequence
import json
from pathlib import Path

import pytest

from patchbench.agents.base import (
    AgentInfrastructureError,
    AgentRunRequest,
    AgentRunResult,
    AgentRunStatus,
)
from patchbench.agents.fake import FakeAgent
from patchbench.application import experiment as experiment_module
from patchbench.application.experiment import (
    ExperimentOrchestrationError,
    run_experiment,
)
from patchbench.domain import ExperimentConfiguration
from patchbench.sandbox.base import SandboxExecResult, SandboxHandle
from tests.helpers import create_fixture_repository, git, write_run_task


class WorkspaceCheckingAgent:
    def __init__(
        self,
        *,
        label: str,
        status: AgentRunStatus,
        fixes_bug: bool,
        events: list[str],
        workspace_starts: list[tuple[bool, bool]],
        workspace_names: list[str],
        error: AgentInfrastructureError | None = None,
    ) -> None:
        self.label = label
        self.status = status
        self.fixes_bug = fixes_bug
        self.events = events
        self.workspace_starts = workspace_starts
        self.workspace_names = workspace_names
        self.error = error

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.events.append(f"start-{self.label}")
        marker = request.workspace / "previous-run-marker.txt"
        target = request.workspace / "calculator.py"
        contents = target.read_text(encoding="utf-8")
        self.workspace_starts.append((marker.exists(), "return a - b" in contents))
        self.workspace_names.append(request.workspace.name)
        marker.write_text(self.label, encoding="utf-8")

        if self.error is not None:
            raise self.error
        if self.fixes_bug:
            target.write_text(
                contents.replace("return a - b", "return a + b"),
                encoding="utf-8",
            )

        self.events.append(f"end-{self.label}")
        return AgentRunResult(
            status=self.status,
            exit_code=(
                None
                if self.status is AgentRunStatus.TIMED_OUT
                else 7
                if self.status is AgentRunStatus.COMMAND_FAILED
                else 0
            ),
            stdout=f"{self.label} stdout\n",
            stderr=f"{self.label} stderr\n",
            duration_seconds=0.01,
        )


class PassingSandbox:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.workspace: Path | None = None

    def create(self, workspace=None, resource_limits=None) -> SandboxHandle:
        assert workspace is not None
        self.workspace = workspace
        self.events.append("create")
        return SandboxHandle(identifier="sandbox-1")

    def exec(
        self,
        handle: SandboxHandle,
        command: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> SandboxExecResult:
        self.events.append("exec")
        assert self.workspace is not None
        assert "return a + b" in (self.workspace / "calculator.py").read_text()
        return SandboxExecResult(exit_code=0, stdout="passed", stderr="")

    def destroy(self, handle: SandboxHandle) -> None:
        self.events.append("destroy")


def configuration(backend: str = "host") -> ExperimentConfiguration:
    return ExperimentConfiguration(
        agent_name="recording",
        requested_model="test-model",
        agent_timeout_seconds=12.5,
        evaluation_backend=backend,
    )


@pytest.mark.parametrize("requested_runs", [0, -1, True, 1.0, "2"])
def test_requested_runs_is_rejected_before_execution(
    requested_runs, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        experiment_module,
        "load_task",
        lambda path: pytest.fail("task must not be loaded"),
    )

    with pytest.raises(ExperimentOrchestrationError, match="positive integer"):
        run_experiment(
            tmp_path / "missing.yaml",
            requested_runs=requested_runs,
            configuration=configuration(),
            agent_factory=lambda: pytest.fail("agent factory must not be called"),
        )


@pytest.mark.parametrize(
    ("backend", "sandbox"),
    [("docker", None), ("host", PassingSandbox())],
)
def test_evaluation_backend_mismatch_is_rejected_before_execution(
    backend, sandbox, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        experiment_module,
        "load_task",
        lambda path: pytest.fail("task must not be loaded"),
    )

    with pytest.raises(ExperimentOrchestrationError, match="evaluation_backend"):
        run_experiment(
            tmp_path / "missing.yaml",
            requested_runs=1,
            configuration=configuration(backend),
            agent_factory=lambda: pytest.fail("agent factory must not be called"),
            sandbox=sandbox,
        )


def test_single_docker_backed_run_is_accepted(tmp_path: Path) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(tmp_path, source, base_commit)
    sandbox = PassingSandbox()
    agents = []

    def agent_factory() -> FakeAgent:
        agent = FakeAgent()
        agents.append(agent)
        return agent

    record = run_experiment(
        task_path,
        requested_runs=1,
        configuration=ExperimentConfiguration(
            agent_name="fake",
            requested_model=None,
            agent_timeout_seconds=None,
            evaluation_backend="docker",
        ),
        agent_factory=agent_factory,
        workspace_root=tmp_path / "workspaces",
        results_root=tmp_path / "results",
        sandbox=sandbox,
    )

    assert len(agents) == 1
    assert sandbox.events == ["create", "exec", "destroy"]
    assert (
        record.requested_runs == len(record.run_ids) == record.aggregate.run_count == 1
    )
    assert record.aggregate.evaluation_pass_count == 1
    assert record.configuration.evaluation_backend == "docker"


def test_experiment_runs_sequentially_with_frozen_task_and_fresh_workspaces(
    tmp_path: Path, monkeypatch
) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(tmp_path, source, base_commit)
    workspace_root = tmp_path / "workspaces"
    results_root = tmp_path / "results"
    task_loads = []
    events: list[str] = []
    workspace_starts: list[tuple[bool, bool]] = []
    workspace_names: list[str] = []
    agents: list[WorkspaceCheckingAgent] = []
    plans = [
        (AgentRunStatus.COMMAND_FAILED, True),
        (AgentRunStatus.TIMED_OUT, False),
        (AgentRunStatus.COMPLETED, True),
    ]
    real_load_task = experiment_module.load_task

    def recording_load_task(path):
        task_loads.append(path)
        return real_load_task(path)

    def agent_factory() -> WorkspaceCheckingAgent:
        index = len(agents)
        status, fixes_bug = plans[index]
        label = str(index + 1)
        events.append(f"factory-{label}")
        agent = WorkspaceCheckingAgent(
            label=label,
            status=status,
            fixes_bug=fixes_bug,
            events=events,
            workspace_starts=workspace_starts,
            workspace_names=workspace_names,
        )
        agents.append(agent)
        return agent

    monkeypatch.setattr(experiment_module, "load_task", recording_load_task)
    frozen_configuration = configuration()

    record = run_experiment(
        task_path,
        requested_runs=3,
        configuration=frozen_configuration,
        agent_factory=agent_factory,
        workspace_root=workspace_root,
        results_root=results_root,
    )

    assert task_loads == [task_path]
    assert len(agents) == 3
    assert len({id(agent) for agent in agents}) == 3
    assert events == [
        "factory-1",
        "start-1",
        "end-1",
        "factory-2",
        "start-2",
        "end-2",
        "factory-3",
        "start-3",
        "end-3",
    ]
    assert workspace_starts == [(False, True), (False, True), (False, True)]
    assert record.run_ids == workspace_names
    assert (
        record.requested_runs == len(record.run_ids) == record.aggregate.run_count == 3
    )
    assert record.configuration == frozen_configuration
    assert record.configuration is not frozen_configuration
    assert record.aggregate.evaluation_pass_count == 2
    assert record.aggregate.evaluation_fail_count == 1
    assert record.aggregate.agent_command_failure_count == 1
    assert record.aggregate.agent_timeout_count == 1
    assert record.duration_seconds >= 0

    child_metadata = [
        json.loads((results_root / run_id / "metadata.json").read_text())
        for run_id in record.run_ids
    ]
    assert [metadata["agent"]["status"] for metadata in child_metadata] == [
        "command_failed",
        "timed_out",
        "completed",
    ]
    assert [metadata["evaluation_passed"] for metadata in child_metadata] == [
        True,
        False,
        True,
    ]
    for metadata in child_metadata:
        assert metadata["agent"]["name"] == frozen_configuration.agent_name
        assert (
            metadata["agent"]["requested_model"]
            == frozen_configuration.requested_model
        )
        assert (
            metadata["agent"]["timeout_seconds"]
            == frozen_configuration.agent_timeout_seconds
        )
    assert record.aggregate.total_duration_seconds == pytest.approx(
        sum(metadata["duration_seconds"] for metadata in child_metadata)
    )
    assert {path.name for path in results_root.iterdir()} == set(record.run_ids)
    assert git(source, "status", "--porcelain") == ""
    assert git(source, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert not any(workspace_root.iterdir())


def test_hard_failure_aborts_without_starting_later_runs(tmp_path: Path) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(tmp_path, source, base_commit)
    workspace_root = tmp_path / "workspaces"
    results_root = tmp_path / "results"
    error = AgentInfrastructureError("third Run infrastructure failure")
    events: list[str] = []
    workspace_starts: list[tuple[bool, bool]] = []
    workspace_names: list[str] = []
    agents: list[WorkspaceCheckingAgent] = []

    def agent_factory() -> WorkspaceCheckingAgent:
        index = len(agents)
        label = str(index + 1)
        events.append(f"factory-{label}")
        agent = WorkspaceCheckingAgent(
            label=label,
            status=AgentRunStatus.COMPLETED,
            fixes_bug=True,
            events=events,
            workspace_starts=workspace_starts,
            workspace_names=workspace_names,
            error=error if index == 2 else None,
        )
        agents.append(agent)
        return agent

    record = None
    with pytest.raises(AgentInfrastructureError) as raised:
        record = run_experiment(
            task_path,
            requested_runs=5,
            configuration=configuration(),
            agent_factory=agent_factory,
            workspace_root=workspace_root,
            results_root=results_root,
        )

    assert raised.value is error
    assert record is None
    assert len(agents) == 3
    assert events == [
        "factory-1",
        "start-1",
        "end-1",
        "factory-2",
        "start-2",
        "end-2",
        "factory-3",
        "start-3",
    ]
    assert len(list(results_root.iterdir())) == 2
    assert git(source, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert not any(workspace_root.iterdir())
