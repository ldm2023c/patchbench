from pathlib import Path

import pytest
from pydantic import ValidationError

from patchbench.agents.base import AgentRunStatus
from patchbench.domain import (
    AgentExecutionMetadata,
    ArtifactPaths,
    ExperimentAggregate,
    ExperimentAggregationError,
    ExperimentConfiguration,
    ExperimentRecord,
    RunRecord,
    RunStatus,
    aggregate_runs,
)


def make_run(
    run_id: str,
    *,
    evaluation_passed: bool,
    agent_status: AgentRunStatus = AgentRunStatus.COMPLETED,
    duration_seconds: float = 1.0,
) -> RunRecord:
    artifact_directory = Path("/results") / run_id
    artifact_paths = {
        name: artifact_directory / name for name in ArtifactPaths.model_fields
    }
    exit_code = {
        AgentRunStatus.COMPLETED: 0,
        AgentRunStatus.COMMAND_FAILED: 7,
        AgentRunStatus.TIMED_OUT: None,
    }[agent_status]
    return RunRecord(
        run_id=run_id,
        task_id="example_bug",
        status=RunStatus.PASSED if evaluation_passed else RunStatus.FAILED,
        evaluation_passed=evaluation_passed,
        duration_seconds=duration_seconds,
        agent=AgentExecutionMetadata(
            name="codex",
            backend="host",
            status=agent_status,
            exit_code=exit_code,
            duration_seconds=duration_seconds / 2,
            timeout_seconds=30,
            requested_model="test-model",
        ),
        artifacts=ArtifactPaths(**artifact_paths),
    )


def aggregate_data(run_count: int = 1) -> dict[str, object]:
    return {
        "run_count": run_count,
        "evaluation_pass_count": run_count,
        "evaluation_fail_count": 0,
        "evaluation_pass_rate": 1.0,
        "agent_command_failure_count": 0,
        "agent_timeout_count": 0,
        "total_duration_seconds": float(run_count),
        "mean_duration_seconds": 1.0,
        "min_duration_seconds": 1.0,
        "max_duration_seconds": 1.0,
    }


def make_configuration() -> ExperimentConfiguration:
    return ExperimentConfiguration(
        agent_name="codex",
        requested_model="test-model",
        agent_timeout_seconds=30,
        evaluation_backend="docker",
    )


def test_aggregate_single_all_pass_run() -> None:
    aggregate = aggregate_runs(
        [make_run("run-1", evaluation_passed=True, duration_seconds=2.5)]
    )

    assert aggregate.model_dump() == {
        "run_count": 1,
        "evaluation_pass_count": 1,
        "evaluation_fail_count": 0,
        "evaluation_pass_rate": 1.0,
        "agent_command_failure_count": 0,
        "agent_timeout_count": 0,
        "total_duration_seconds": 2.5,
        "mean_duration_seconds": 2.5,
        "min_duration_seconds": 2.5,
        "max_duration_seconds": 2.5,
    }


def test_aggregate_multiple_all_pass_runs() -> None:
    aggregate = aggregate_runs(
        [
            make_run("run-1", evaluation_passed=True),
            make_run("run-2", evaluation_passed=True),
        ]
    )

    assert (
        aggregate.evaluation_pass_count,
        aggregate.evaluation_fail_count,
        aggregate.evaluation_pass_rate,
    ) == (2, 0, 1.0)


def test_aggregate_keeps_agent_and_evaluation_outcomes_independent() -> None:
    aggregate = aggregate_runs(
        [
            make_run(
                "run-command-failed-pass",
                evaluation_passed=True,
                agent_status=AgentRunStatus.COMMAND_FAILED,
                duration_seconds=2,
            ),
            make_run(
                "run-timed-out-fail",
                evaluation_passed=False,
                agent_status=AgentRunStatus.TIMED_OUT,
                duration_seconds=4,
            ),
            make_run(
                "run-timed-out-pass",
                evaluation_passed=True,
                agent_status=AgentRunStatus.TIMED_OUT,
                duration_seconds=6,
            ),
        ]
    )

    assert aggregate.evaluation_pass_count == 2
    assert aggregate.evaluation_fail_count == 1
    assert aggregate.evaluation_pass_rate == pytest.approx(2 / 3)
    assert aggregate.agent_command_failure_count == 1
    assert aggregate.agent_timeout_count == 2
    assert aggregate.total_duration_seconds == 12
    assert aggregate.mean_duration_seconds == 4
    assert aggregate.min_duration_seconds == 2
    assert aggregate.max_duration_seconds == 6


def test_aggregate_rejects_empty_run_collection() -> None:
    with pytest.raises(ExperimentAggregationError, match="empty"):
        aggregate_runs([])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("agent_name", "   "),
        ("requested_model", "   "),
        ("agent_timeout_seconds", 0),
        ("agent_timeout_seconds", -1),
        ("agent_timeout_seconds", float("inf")),
        ("agent_timeout_seconds", float("nan")),
        ("evaluation_backend", "remote"),
    ],
)
def test_experiment_configuration_rejects_invalid_values(field, value) -> None:
    data = make_configuration().model_dump()
    data[field] = value

    with pytest.raises(ValidationError, match=field):
        ExperimentConfiguration.model_validate(data)


@pytest.mark.parametrize(
    "updates",
    [
        {"evaluation_fail_count": 1},
        {"agent_command_failure_count": 2},
        {"agent_timeout_count": 2},
    ],
)
def test_experiment_aggregate_rejects_inconsistent_counts(updates) -> None:
    data = aggregate_data()
    data.update(updates)

    with pytest.raises(ValidationError):
        ExperimentAggregate.model_validate(data)


def make_experiment_record(**updates) -> ExperimentRecord:
    data = {
        "experiment_id": "experiment-1",
        "task_id": "example_bug",
        "requested_runs": 2,
        "run_ids": ["run-1", "run-2"],
        "configuration": make_configuration(),
        "aggregate": ExperimentAggregate(**aggregate_data(run_count=2)),
        "duration_seconds": 2.5,
    }
    data.update(updates)
    return ExperimentRecord.model_validate(data)


def test_valid_completed_experiment_is_accepted() -> None:
    record = make_experiment_record()

    assert record.requested_runs == len(record.run_ids) == record.aggregate.run_count
    assert record.run_ids == ["run-1", "run-2"]
    assert set(record.model_dump()) == {
        "experiment_id",
        "task_id",
        "requested_runs",
        "run_ids",
        "configuration",
        "aggregate",
        "duration_seconds",
    }


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"requested_runs": 0}, "requested_runs"),
        ({"requested_runs": -1}, "requested_runs"),
        ({"requested_runs": True}, "requested_runs"),
        ({"requested_runs": 1.0}, "requested_runs"),
        ({"requested_runs": "2"}, "requested_runs"),
        ({"run_ids": []}, "run_ids"),
        ({"run_ids": ["run-1", "run-1"]}, "unique"),
        ({"run_ids": ["run-1"]}, "number of run_ids"),
        (
            {"aggregate": ExperimentAggregate(**aggregate_data(run_count=1))},
            "aggregate.run_count",
        ),
    ],
)
def test_experiment_rejects_invalid_run_cardinality(updates, message) -> None:
    with pytest.raises(ValidationError, match=message):
        make_experiment_record(**updates)
