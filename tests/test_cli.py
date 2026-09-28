import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.text import Text
from typer.testing import CliRunner

from patchbench.agents.base import AgentInfrastructureError, AgentRunStatus
from patchbench.agents.fake import FakeAgent
from patchbench.application.replay import ReplayExecution
from patchbench.cli import app
from patchbench.domain import (
    EvaluationResult,
    ExperimentAggregate,
    ExperimentConfiguration,
    ExperimentRecord,
    ReplayRecord,
)
from patchbench.storage import ArtifactStoreError, FilesystemArtifactStore
from tests.helpers import create_fixture_repository, git, write_run_task
from tests.test_replay import FIX_PATCH, make_run, persist_source
from tests.test_task_loader import VALID_TASK


runner = CliRunner()


def plain_cli_output(value: str) -> str:
    """Remove terminal presentation codes before semantic CLI assertions."""
    return Text.from_ansi(value).plain


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


def test_run_codex_normalizes_model_for_agent_and_metadata(
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
            "  test-model  ",
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


def test_experiment_codex_normalizes_model_and_uses_fresh_agents(
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
            "  test-model  ",
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
    assert message in plain_cli_output(result.output)


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


def completed_replay(
    *,
    source_passed: bool = True,
    replay_passed: bool = True,
) -> ReplayExecution:
    record = ReplayRecord(
        replay_id="replay-123",
        source_run_id="source-run",
        task_id="calculator_bug",
        base_commit_used="abc123",
        evaluation_backend="host",
        source_evaluation_passed=source_passed,
        replay_evaluation_passed=replay_passed,
        outcome_matches=source_passed == replay_passed,
        duration_seconds=1.25,
    )
    return ReplayExecution(
        record=record,
        evaluation_result=EvaluationResult(
            exit_code=0 if replay_passed else 1,
            passed=replay_passed,
            duration_seconds=1.0,
            stdout="evaluation output",
            stderr="",
        ),
    )


def test_replay_cli_surface_has_only_replay_options() -> None:
    result = runner.invoke(app, ["replay", "--help"])

    assert result.exit_code == 0
    output = plain_cli_output(result.output)
    assert "--task" in output
    assert "--run-id" in output
    assert "--docker" in output
    unsupported_options = (
        "--agent",
        "--model",
        "--agent-timeout",
        "--runs",
        "--retry",
    )
    for unsupported in unsupported_options:
        assert unsupported not in output


def test_replay_host_cli_persists_result_and_never_constructs_agent(
    tmp_path: Path, monkeypatch
) -> None:
    source_repository, base_commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(tmp_path, source_repository, base_commit)
    results_root = tmp_path / "results"
    source = make_run(results_root)
    persist_source(source, FIX_PATCH)
    metadata_before = source.artifacts.metadata.read_bytes()
    patch_before = source.artifacts.patch.read_bytes()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "patchbench.cli.FakeAgent",
        lambda: pytest.fail("Replay must not construct FakeAgent"),
    )
    monkeypatch.setattr(
        "patchbench.cli.CodexAdapter",
        lambda **kwargs: pytest.fail("Replay must not construct CodexAdapter"),
    )
    monkeypatch.setattr(
        "patchbench.cli.DockerSandbox",
        lambda: pytest.fail("host Replay must not construct DockerSandbox"),
    )

    result = runner.invoke(
        app,
        ["replay", "--task", str(task_path), "--run-id", source.run_id],
    )

    assert result.exit_code == 0, result.output
    assert "Source Run ID:  source-run" in result.output
    assert "Source Evaluation: PASS" in result.output
    assert "Replay Evaluation: PASS" in result.output
    assert "Outcome Match:     YES" in result.output
    assert "Evaluation Backend: host" in result.output
    assert "Agent:" not in result.output
    replay_metadata = list(results_root.glob("replays/*/metadata.json"))
    assert len(replay_metadata) == 1
    replay_directory = replay_metadata[0].parent
    assert {path.name for path in replay_directory.iterdir()} == {
        "metadata.json",
        "test.log",
    }
    assert source.artifacts.metadata.read_bytes() == metadata_before
    assert source.artifacts.patch.read_bytes() == patch_before
    assert list((tmp_path / ".workspaces").iterdir()) == []
    assert git(source_repository, "status", "--porcelain") == ""


def test_replay_docker_flag_supplies_sandbox_without_agent_options(
    tmp_path: Path, monkeypatch
) -> None:
    sandbox = object()
    source_run = make_run(tmp_path / "results")
    execution = completed_replay()
    received: dict[str, object] = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "patchbench.cli.load_task",
        lambda path: SimpleNamespace(
            evaluation=SimpleNamespace(command="pytest -q")
        ),
    )
    monkeypatch.setattr(
        "patchbench.cli.FilesystemArtifactStore.load_run_record",
        lambda self, run_id: source_run,
    )
    monkeypatch.setattr(
        "patchbench.cli.FilesystemArtifactStore.load_run_patch",
        lambda self, run_id: FIX_PATCH,
    )
    monkeypatch.setattr("patchbench.cli.DockerSandbox", lambda: sandbox)

    def fake_replay_run(task, source, patch, *, sandbox=None):
        received.update(
            {"task": task, "source": source, "patch": patch, "sandbox": sandbox}
        )
        return execution

    monkeypatch.setattr("patchbench.cli.replay_run", fake_replay_run)
    monkeypatch.setattr(
        "patchbench.cli.FilesystemArtifactStore.save_replay",
        lambda self, record, evaluation, command: tmp_path / "metadata.json",
    )

    result = runner.invoke(
        app,
        [
            "replay",
            "--task",
            str(tmp_path / "task.yaml"),
            "--run-id",
            "source-run",
            "--docker",
        ],
    )

    assert result.exit_code == 0, result.output
    assert received["source"] is source_run
    assert received["patch"] == FIX_PATCH
    assert received["sandbox"] is sandbox


@pytest.mark.parametrize(
    ("source_passed", "replay_passed", "source_text", "replay_text", "match"),
    [
        (False, False, "FAIL", "FAIL", "YES"),
        (True, False, "PASS", "FAIL", "NO"),
        (False, True, "FAIL", "PASS", "NO"),
    ],
)
def test_completed_failures_and_mismatches_are_cli_success(
    tmp_path: Path,
    monkeypatch,
    source_passed: bool,
    replay_passed: bool,
    source_text: str,
    replay_text: str,
    match: str,
) -> None:
    execution = completed_replay(
        source_passed=source_passed,
        replay_passed=replay_passed,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("patchbench.cli.load_task", lambda path: SimpleNamespace(
        evaluation=SimpleNamespace(command="pytest -q")
    ))
    monkeypatch.setattr(
        "patchbench.cli.FilesystemArtifactStore.load_run_record",
        lambda self, run_id: object(),
    )
    monkeypatch.setattr(
        "patchbench.cli.FilesystemArtifactStore.load_run_patch",
        lambda self, run_id: "",
    )
    monkeypatch.setattr("patchbench.cli.replay_run", lambda *args, **kwargs: execution)
    monkeypatch.setattr(
        "patchbench.cli.FilesystemArtifactStore.save_replay",
        lambda self, record, evaluation, command: tmp_path / "metadata.json",
    )

    result = runner.invoke(
        app,
        ["replay", "--task", "task.yaml", "--run-id", "source-run"],
    )

    assert result.exit_code == 0, result.output
    assert f"Source Evaluation: {source_text}" in result.output
    assert f"Replay Evaluation: {replay_text}" in result.output
    assert f"Outcome Match:     {match}" in result.output


def test_replay_artifact_failure_is_nonzero_without_completed_summary(
    tmp_path: Path, monkeypatch
) -> None:
    source_repository, base_commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(tmp_path, source_repository, base_commit)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["replay", "--task", str(task_path), "--run-id", "missing-run"],
    )

    assert result.exit_code == 1
    assert "Unable to load Run metadata" in result.output
    assert "Replay ID:" not in result.output
    assert not (tmp_path / "results/replays").exists()


def test_replay_persistence_failure_is_cli_failure(
    tmp_path: Path, monkeypatch
) -> None:
    execution = completed_replay()
    error = ArtifactStoreError("simulated Replay persistence failure")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "patchbench.cli.load_task",
        lambda path: SimpleNamespace(
            evaluation=SimpleNamespace(command="pytest -q")
        ),
    )
    monkeypatch.setattr(
        "patchbench.cli.FilesystemArtifactStore.load_run_record",
        lambda self, run_id: object(),
    )
    monkeypatch.setattr(
        "patchbench.cli.FilesystemArtifactStore.load_run_patch",
        lambda self, run_id: FIX_PATCH,
    )
    monkeypatch.setattr("patchbench.cli.replay_run", lambda *args, **kwargs: execution)
    monkeypatch.setattr(
        "patchbench.cli.FilesystemArtifactStore.save_replay",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    result = runner.invoke(
        app,
        ["replay", "--task", "task.yaml", "--run-id", "source-run"],
    )

    assert result.exit_code == 1
    assert "simulated Replay persistence failure" in result.output
    assert "Replay ID:" not in result.output


def test_analyze_help_exposes_options():
    result = runner.invoke(app, ["analyze", "--help"])
    assert result.exit_code == 0
    output = plain_cli_output(result.output)
    assert "--experiment" in output and "--json" in output


@pytest.mark.parametrize("outcomes", [(True, True), (True, False), (False, False)])
@pytest.mark.parametrize("json_output", [False, True])
def test_analyze_cli_success_and_read_only(tmp_path, monkeypatch, outcomes, json_output):
    from tests.test_analysis import write_experiment, snapshot
    _, experiment = write_experiment(tmp_path / "results", outcomes)
    monkeypatch.chdir(tmp_path)
    before = snapshot(tmp_path)
    args = ["analyze", "--experiment", experiment.experiment_id]
    if json_output:
        args.append("--json")
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    if json_output:
        payload = json.loads(result.stdout)
        assert payload["experiment_id"] == experiment.experiment_id
        assert set(payload) == {"experiment_id", "task_id", "configuration", "aggregate", "provenance",
                                "exact_patch_variant_count", "failure_category_counts", "runs", "example_pair"}
        assert [r["run_id"] for r in payload["runs"]] == experiment.run_ids
        assert payload["aggregate"]["evaluation_pass_count"] == outcomes.count(True)
        assert payload["aggregate"]["evaluation_fail_count"] == outcomes.count(False)
    else:
        for label in ("Experiment:", "Task:", "Evaluation:", "Configuration:", "Provenance:",
                      "Exact patch variants:", "Runs:", "Failure observations:", "Example PASS/FAIL pair:",
                      "agent_command_failed:", "agent_timed_out:", "no_patch:", "test_failed:"):
            assert label in result.output
        assert f"PASS: {outcomes.count(True)}" in result.output
        assert f"FAIL: {outcomes.count(False)}" in result.output
        assert "Model: -" in result.output and "Timeout: -" in result.output
        assert "Task SHA256: " + "b" * 64 in result.output
        assert all(run_id in result.output for run_id in experiment.run_ids)
    assert snapshot(tmp_path) == before


def test_analyze_cli_historical_unknown_output(tmp_path, monkeypatch):
    from tests.test_analysis import write_experiment
    _, experiment = write_experiment(tmp_path / "results", historical=True, provenance=False, unknown=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["analyze", "--experiment", experiment.experiment_id])
    assert result.exit_code == 0, result.output
    assert "unavailable (historical Run metadata)" in result.output
    assert "tests=?" in result.output


@pytest.mark.parametrize("experiment_id", ["missing", "../x", "a/b", "/absolute"])
def test_analyze_cli_bad_lookup(tmp_path, monkeypatch, experiment_id):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["analyze", "--experiment", experiment_id, "--json"])
    assert result.exit_code == 1
    assert result.stderr.startswith("Error:")
    assert result.stdout == ""
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("problem", ["missing_patch", "missing_log", "bad_summary", "bad_experiment", "bad_log"])
def test_analyze_cli_input_errors(tmp_path, monkeypatch, problem):
    from tests.test_analysis import write_experiment, mutate
    _, experiment = write_experiment(tmp_path / "results")
    directory = tmp_path / "results" / experiment.run_ids[0]
    if problem == "missing_patch":
        (directory / "patch.diff").unlink()
    elif problem == "missing_log":
        (directory / "test.log").unlink()
    elif problem == "bad_summary":
        mutate(directory / "metadata.json", lambda r: r["patch_summary"].update(patch_sha256="c" * 64))
    elif problem == "bad_experiment":
        (tmp_path / "results" / "experiments" / experiment.experiment_id / "metadata.json").write_text("{")
    else:
        (directory / "test.log").write_text("invalid")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["analyze", "--experiment", experiment.experiment_id])
    assert result.exit_code == 1
    assert result.stderr.startswith("Error:") and result.stdout == ""


def test_analyze_available_through_python_module():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-m", "patchbench.cli", "analyze", "--help"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    output = plain_cli_output(result.stdout)
    assert "--experiment" in output and "--json" in output
