"""Sequential orchestration for completed PatchBench Experiments."""

from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from patchbench.agents.base import Agent
from patchbench.application.local_run import _execute_single_run
from patchbench.config.task_loader import load_task
from patchbench.domain import (
    ExperimentConfiguration,
    ExperimentRecord,
    aggregate_runs,
)
from patchbench.sandbox.base import Sandbox


class ExperimentOrchestrationError(ValueError):
    """Raised when an Experiment cannot start with the supplied configuration."""


def run_experiment(
    task_path: str | Path,
    *,
    requested_runs: int,
    configuration: ExperimentConfiguration,
    agent_factory: Callable[[], Agent],
    workspace_root: Path | None = None,
    results_root: Path | None = None,
    sandbox: Sandbox | None = None,
) -> ExperimentRecord:
    """Execute independent Runs sequentially and return their completed aggregate."""

    _validate_requested_runs(requested_runs)
    frozen_configuration = configuration.model_copy(deep=True)
    _validate_evaluation_backend(frozen_configuration, sandbox)

    started = perf_counter()
    experiment_id = uuid4().hex
    task = load_task(task_path)
    runs = []

    for _ in range(requested_runs):
        agent = agent_factory()
        runs.append(
            _execute_single_run(
                task,
                agent=agent,
                agent_name=frozen_configuration.agent_name,
                agent_timeout_seconds=(
                    frozen_configuration.agent_timeout_seconds
                ),
                requested_model=frozen_configuration.requested_model,
                agent_identity_binding=frozen_configuration.identity_binding,
                workspace_root=workspace_root,
                results_root=results_root,
                sandbox=sandbox,
            )
        )

    aggregate = aggregate_runs(runs)
    return ExperimentRecord(
        experiment_id=experiment_id,
        task_id=task.id,
        requested_runs=requested_runs,
        run_ids=[run.run_id for run in runs],
        configuration=frozen_configuration,
        aggregate=aggregate,
        duration_seconds=perf_counter() - started,
    )


def _validate_requested_runs(requested_runs: int) -> None:
    if (
        isinstance(requested_runs, bool)
        or not isinstance(requested_runs, int)
        or requested_runs < 1
    ):
        raise ExperimentOrchestrationError(
            "requested_runs must be a positive integer"
        )


def _validate_evaluation_backend(
    configuration: ExperimentConfiguration,
    sandbox: Sandbox | None,
) -> None:
    actual_backend = "docker" if sandbox is not None else "host"
    if configuration.evaluation_backend != actual_backend:
        raise ExperimentOrchestrationError(
            "evaluation_backend does not match the supplied sandbox"
        )
