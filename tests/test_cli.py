import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from patchbench.agents.base import AgentInfrastructureError, AgentRunStatus
from patchbench.agents.fake import FakeAgent
from patchbench.cli import app
from patchbench.domain import (
    ExperimentAggregate,
    ExperimentConfiguration,
    ExperimentRecord,
)
from patchbench.storage import ArtifactStoreError, FilesystemArtifactStore
from tests.helpers import create_fixture_repository, git, write_run_task
from tests.test_task_loader import VALID_TASK


runner = CliRunner()


def completed_experiment(
    *,
    configuration: ExperimentConfiguration | None = None,
    evaluation_pass_count: int = 2,
    agent_command_failure_count: int = 0,
    agent_timeout_count: int = 0,
) -> ExperimentRecord:
    run_count = 3
    return ExperimentRecord(
        experiment_id="experiment-123",
        task_id="calculator_bug",
        requested_runs=run_count,
        run_ids=["run-1", "run-2", "run-3"],
        configuration=configuration
        or ExperimentConfiguration(
            agent_name="fake",
            requested_model=None,
            agent_timeout_seconds=None,
            evaluation_backend="host",
        ),
        aggregate=ExperimentAggregate(
            run_count=run_count,
            evaluation_pass_count=evaluation_pass_count,
            evaluation_fail_count=run_count - evaluation_pass_count,
            evaluation_pass_rate=evaluation_pass_count / run_count,
            agent_command_failure_count=agent_command_failure_count,
            agent_timeout_count=agent_timeout_count,
            total_duration_seconds=6.0,
            mean_duration_seconds=2.0,
            min_duration_seconds=1.0,
            max_duration_seconds=3.0,
        ),
        duration_seconds=6.5,
    )


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


def test_experiment_with_fake_agent_persists_three_runs_and_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(tmp_path, source, base_commit)
    source_contents = (source / "calculator.py").read_text(encoding="utf-8")
    created_agents: list[FakeAgent] = []

    class RecordingFakeAgent(FakeAgent):
        def __init__(self) -> None:
            created_agents.append(self)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("patchbench.cli.FakeAgent", RecordingFakeAgent)
    monkeypatch.setattr(
        "patchbench.cli.DockerSandbox",
        lambda: pytest.fail("DockerSandbox must not be created by default"),
    )

    result = runner.invoke(
        app,
        [
            "experiment",
            "--task",
            str(task_path),
            "--agent",
            "fake",
            "--runs",
            "3",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(created_agents) == 3
    assert len({id(agent) for agent in created_agents}) == 3
    assert "Runs:          3" in result.output
    assert "Evaluation:" in result.output
    assert "PASS:      3" in result.output
    assert "FAIL:      0" in result.output
    assert "Agent:" in result.output
    assert "Command failed: 0" in result.output
    assert "Timed out:      0" in result.output
    assert "Duration:" in result.output
    assert "Artifacts:" in result.output

    experiment_metadata = list(
        (tmp_path / "results" / "experiments").glob("*/metadata.json")
    )
    assert len(experiment_metadata) == 1
    metadata = json.loads(experiment_metadata[0].read_text(encoding="utf-8"))
    assert set(metadata) == {
        "experiment_id",
        "task_id",
        "requested_runs",
        "run_ids",
        "configuration",
        "aggregate",
        "duration_seconds",
    }
    assert metadata["requested_runs"] == 3
    assert metadata["configuration"] == {
        "agent_name": "fake",
        "requested_model": None,
        "agent_timeout_seconds": None,
        "evaluation_backend": "host",
    }
    assert metadata["aggregate"]["evaluation_pass_count"] == 3
    assert len(metadata["run_ids"]) == len(set(metadata["run_ids"])) == 3
    assert all(
        (tmp_path / "results" / run_id / "metadata.json").is_file()
        for run_id in metadata["run_ids"]
    )
    assert not any(key in metadata for key in ("runs", "run_records"))
    assert (source / "calculator.py").read_text(encoding="utf-8") == source_contents
    assert git(source, "status", "--porcelain") == ""
    assert list((tmp_path / ".workspaces").iterdir()) == []


def test_experiment_codex_docker_composition_uses_fresh_agents(
    tmp_path: Path, monkeypatch
) -> None:
    sandbox = object()
    constructed_agents: list[object] = []
    models: list[str] = []
    received: dict[str, object] = {}

    def fake_codex_adapter(*, model: str) -> object:
        selected_agent = object()
        models.append(model)
        constructed_agents.append(selected_agent)
        return selected_agent

    def fake_run_experiment(
        task_path: Path,
        *,
        requested_runs: int,
        configuration: ExperimentConfiguration,
        agent_factory,
        results_root: Path,
        sandbox,
    ) -> ExperimentRecord:
        agents = [agent_factory() for _ in range(requested_runs)]
        received.update(
            {
                "requested_runs": requested_runs,
                "configuration": configuration,
                "agents": agents,
                "sandbox": sandbox,
            }
        )
        return completed_experiment(configuration=configuration)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("patchbench.cli.CodexAdapter", fake_codex_adapter)
    monkeypatch.setattr("patchbench.cli.DockerSandbox", lambda: sandbox)
    monkeypatch.setattr("patchbench.cli.run_experiment", fake_run_experiment)
    monkeypatch.setattr(
        "patchbench.cli.FilesystemArtifactStore.save_experiment",
        lambda self, record: tmp_path / "experiment-metadata.json",
    )

    result = runner.invoke(
        app,
        [
            "experiment",
            "--task",
            str(tmp_path / "task.yaml"),
            "--agent",
            "codex",
            "--model",
            "test-model",
            "--runs",
            "3",
            "--agent-timeout",
            "12.5",
            "--docker",
        ],
    )

    assert result.exit_code == 0, result.output
    configuration = received["configuration"]
    assert isinstance(configuration, ExperimentConfiguration)
    assert configuration == ExperimentConfiguration(
        agent_name="codex",
        requested_model="test-model",
        agent_timeout_seconds=12.5,
        evaluation_backend="docker",
    )
    assert received["requested_runs"] == 3
    assert received["sandbox"] is sandbox
    assert received["agents"] == constructed_agents
    assert len({id(agent) for agent in constructed_agents}) == 3
    assert models == ["test-model", "test-model", "test-model"]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--agent", "fake", "--runs", "0"], "--runs"),
        (["--agent", "fake", "--runs", "-2"], "--runs"),
        (["--agent", "fake", "--runs", "1.5"], "--runs"),
        (["--agent", "fake", "--runs", "two"], "--runs"),
        (
            ["--agent", "fake", "--runs", "1", "--model", "unused"],
            "--model is only valid",
        ),
        (["--agent", "codex", "--runs", "1"], "--model is required"),
        (
            ["--agent", "codex", "--runs", "1", "--model", ""],
            "--model is required",
        ),
        (
            ["--agent", "fake", "--runs", "1", "--agent-timeout", "0"],
            "--agent-timeout must be a finite positive number",
        ),
        (
            ["--agent", "fake", "--runs", "1", "--agent-timeout", "nan"],
            "--agent-timeout must be a finite positive number",
        ),
    ],
)
def test_experiment_rejects_invalid_cli_input_before_execution(
    arguments: list[str], message: str, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "patchbench.cli.run_experiment",
        lambda *args, **kwargs: pytest.fail("run_experiment must not be called"),
    )

    result = runner.invoke(
        app,
        [
            "experiment",
            "--task",
            str(tmp_path / "task.yaml"),
            *arguments,
        ],
    )

    assert result.exit_code != 0
    assert message in result.output


def test_completed_reliability_failures_remain_cli_success(
    tmp_path: Path, monkeypatch
) -> None:
    record = completed_experiment(
        evaluation_pass_count=0,
        agent_command_failure_count=1,
        agent_timeout_count=1,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("patchbench.cli.run_experiment", lambda *args, **kwargs: record)

    result = runner.invoke(
        app,
        [
            "experiment",
            "--task",
            str(tmp_path / "task.yaml"),
            "--agent",
            "fake",
            "--runs",
            "3",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "PASS:      0" in result.output
    assert "FAIL:      3" in result.output
    assert "Pass rate: 0.0%" in result.output
    assert "Command failed: 1" in result.output
    assert "Timed out:      1" in result.output
    metadata = (
        tmp_path
        / "results"
        / "experiments"
        / "experiment-123"
        / "metadata.json"
    )
    assert json.loads(metadata.read_text(encoding="utf-8")) == record.model_dump(
        mode="json"
    )


def test_hard_experiment_failure_does_not_create_metadata_store(
    tmp_path: Path, monkeypatch
) -> None:
    error = AgentInfrastructureError("simulated hard Experiment failure")
    monkeypatch.setattr(
        "patchbench.cli.run_experiment",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        "patchbench.cli.FilesystemArtifactStore",
        lambda *args, **kwargs: pytest.fail("artifact store must not be created"),
    )

    result = runner.invoke(
        app,
        [
            "experiment",
            "--task",
            str(tmp_path / "task.yaml"),
            "--agent",
            "fake",
            "--runs",
            "3",
        ],
    )

    assert result.exit_code == 1
    assert "simulated hard Experiment failure" in result.output
    assert not (tmp_path / "results" / "experiments").exists()


def test_experiment_storage_failure_is_cli_failure(
    tmp_path: Path, monkeypatch
) -> None:
    record = completed_experiment()
    error = ArtifactStoreError("simulated Experiment persistence failure")
    monkeypatch.setattr("patchbench.cli.run_experiment", lambda *args, **kwargs: record)
    monkeypatch.setattr(
        "patchbench.cli.FilesystemArtifactStore.save_experiment",
        lambda self, completed: (_ for _ in ()).throw(error),
    )

    result = runner.invoke(
        app,
        [
            "experiment",
            "--task",
            str(tmp_path / "task.yaml"),
            "--agent",
            "fake",
            "--runs",
            "3",
        ],
    )

    assert result.exit_code == 1
    assert "simulated Experiment persistence failure" in result.output
    assert "Evaluation:" not in result.output


def test_experiment_metadata_collision_is_rejected_without_overwrite(
    tmp_path: Path,
) -> None:
    record = completed_experiment()
    store = FilesystemArtifactStore(tmp_path / "results")
    metadata = store.save_experiment(record)
    original = metadata.read_text(encoding="utf-8")

    with pytest.raises(ArtifactStoreError, match="Unable to persist Experiment"):
        store.save_experiment(record)

    assert metadata.read_text(encoding="utf-8") == original
