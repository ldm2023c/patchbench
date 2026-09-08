"""Pure aggregation of completed PatchBench Runs."""

from collections.abc import Sequence

from patchbench.agents.base import AgentRunStatus
from patchbench.domain.models import ExperimentAggregate, RunRecord


class ExperimentAggregationError(ValueError):
    """Raised when completed Runs cannot form an Experiment aggregate."""


def aggregate_runs(runs: Sequence[RunRecord]) -> ExperimentAggregate:
    """Calculate reliability metrics from a non-empty sequence of completed Runs."""

    if not runs:
        raise ExperimentAggregationError("cannot aggregate an empty Run collection")

    run_count = len(runs)
    evaluation_pass_count = sum(run.evaluation_passed for run in runs)
    durations = [run.duration_seconds for run in runs]
    total_duration_seconds = sum(durations)

    return ExperimentAggregate(
        run_count=run_count,
        evaluation_pass_count=evaluation_pass_count,
        evaluation_fail_count=run_count - evaluation_pass_count,
        evaluation_pass_rate=evaluation_pass_count / run_count,
        agent_command_failure_count=sum(
            run.agent.status is AgentRunStatus.COMMAND_FAILED for run in runs
        ),
        agent_timeout_count=sum(
            run.agent.status is AgentRunStatus.TIMED_OUT for run in runs
        ),
        total_duration_seconds=total_duration_seconds,
        mean_duration_seconds=total_duration_seconds / run_count,
        min_duration_seconds=min(durations),
        max_duration_seconds=max(durations),
    )
