"""Command-line interface for PatchBench."""

from collections.abc import Callable
from math import isfinite
from pathlib import Path
from typing import Annotated

import typer

from patchbench.agents.base import Agent, AgentInfrastructureError, AgentSetupError
from patchbench.agents.codex import CodexAdapter
from patchbench.agents.fake import FakeAgent
from patchbench.application.experiment import (
    ExperimentOrchestrationError,
    run_experiment,
)
from patchbench.application.local_run import run_task
from patchbench.config.task_loader import TaskLoadError, load_task
from patchbench.domain import ExperimentConfiguration, ExperimentRecord
from patchbench.evaluators.command import EvaluationError
from patchbench.repository.git_repository import RepositoryError
from patchbench.sandbox.base import Sandbox
from patchbench.sandbox.docker import DockerSandbox, DockerSandboxError
from patchbench.storage.filesystem import ArtifactStoreError, FilesystemArtifactStore


app = typer.Typer(
    help="Validate tasks and execute PatchBench Runs and Experiments.",
    no_args_is_help=True,
)


def _validate_execution_options(
    command_name: str,
    *,
    agent: str,
    model: str | None,
    agent_timeout_seconds: float | None,
) -> None:
    """Apply the same execution-option rules to Runs and Experiments."""

    if agent not in {"fake", "codex"}:
        typer.echo(
            f"Error: The {command_name} command supports only 'fake' or 'codex'.",
            err=True,
        )
        raise typer.Exit(code=1)
    if agent_timeout_seconds is not None and (
        not isfinite(agent_timeout_seconds) or agent_timeout_seconds <= 0
    ):
        typer.echo("Error: --agent-timeout must be a finite positive number.", err=True)
        raise typer.Exit(code=1)
    if agent == "fake" and model is not None:
        typer.echo("Error: --model is only valid with '--agent codex'.", err=True)
        raise typer.Exit(code=1)
    if agent == "codex" and (model is None or not model.strip()):
        typer.echo("Error: --model is required with '--agent codex'.", err=True)
        raise typer.Exit(code=1)


def _agent_factory(agent: str, model: str | None) -> Callable[[], Agent]:
    """Return a factory that constructs one fresh selected Agent per call."""

    if agent == "fake":
        return FakeAgent

    assert model is not None
    return lambda: CodexAdapter(model=model)


def _sandbox_for(docker: bool) -> Sandbox | None:
    """Compose the selected evaluation backend."""

    return DockerSandbox() if docker else None


def _echo_experiment_summary(record: ExperimentRecord, metadata: Path) -> None:
    """Print completed Experiment reliability metrics without conflating outcomes."""

    aggregate = record.aggregate
    typer.echo(f"Experiment ID: {record.experiment_id}")
    typer.echo(f"Task ID:       {record.task_id}")
    typer.echo(f"Runs:          {record.requested_runs}")
    typer.echo()
    typer.echo("Evaluation:")
    typer.echo(f"  PASS:      {aggregate.evaluation_pass_count}")
    typer.echo(f"  FAIL:      {aggregate.evaluation_fail_count}")
    typer.echo(f"  Pass rate: {aggregate.evaluation_pass_rate:.1%}")
    typer.echo()
    typer.echo("Agent:")
    typer.echo(f"  Command failed: {aggregate.agent_command_failure_count}")
    typer.echo(f"  Timed out:      {aggregate.agent_timeout_count}")
    typer.echo()
    typer.echo("Duration:")
    typer.echo(f"  Total child: {aggregate.total_duration_seconds:.3f}s")
    typer.echo(f"  Mean run:    {aggregate.mean_duration_seconds:.3f}s")
    typer.echo(f"  Experiment:  {record.duration_seconds:.3f}s")
    typer.echo()
    typer.echo("Artifacts:")
    typer.echo(f"  {metadata}")


@app.callback()
def main() -> None:
    """PatchBench command-line interface."""


@app.command("validate-task")
def validate_task(
    path: Annotated[Path, typer.Argument(help="Path to a YAML task definition.")],
) -> None:
    """Validate a PatchBench task definition."""

    try:
        task = load_task(path)
    except TaskLoadError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"Task '{task.id}' is valid.")


@app.command("run")
def run(
    task_path: Annotated[
        Path, typer.Option("--task", help="Path to a YAML task definition.")
    ],
    agent: Annotated[
        str, typer.Option("--agent", help="Agent to execute: 'fake' or 'codex'.")
    ],
    model: Annotated[
        str | None,
        typer.Option("--model", help="Explicit model for the Codex agent."),
    ] = None,
    agent_timeout_seconds: Annotated[
        float | None,
        typer.Option(
            "--agent-timeout",
            help=(
                "Agent execution timeout in seconds; separate from evaluation "
                "timeout."
            ),
        ),
    ] = None,
    docker: Annotated[
        bool,
        typer.Option("--docker", help="Evaluate the task inside Docker."),
    ] = False,
) -> None:
    """Execute one local Run."""

    _validate_execution_options(
        "run",
        agent=agent,
        model=model,
        agent_timeout_seconds=agent_timeout_seconds,
    )

    try:
        selected_agent = _agent_factory(agent, model)()
        record = run_task(
            task_path,
            agent=selected_agent,
            agent_name=agent,
            agent_timeout_seconds=agent_timeout_seconds,
            requested_model=model,
            sandbox=_sandbox_for(docker),
        )
    except (
        ArtifactStoreError,
        DockerSandboxError,
        EvaluationError,
        AgentInfrastructureError,
        AgentSetupError,
        RepositoryError,
        TaskLoadError,
    ) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error

    outcome = "PASS" if record.evaluation_passed else "FAIL"
    typer.echo(f"Run ID:    {record.run_id}")
    typer.echo(f"Task ID:   {record.task_id}")
    typer.echo(f"Agent:     {record.agent.status.name}")
    typer.echo(f"Result:    {outcome}")
    typer.echo(f"Artifacts: {record.artifacts.directory}")


@app.command("experiment")
def experiment(
    task_path: Annotated[
        Path, typer.Option("--task", help="Path to a YAML task definition.")
    ],
    agent: Annotated[
        str, typer.Option("--agent", help="Agent to execute: 'fake' or 'codex'.")
    ],
    runs: Annotated[
        int, typer.Option("--runs", help="Number of independent sequential Runs.")
    ],
    model: Annotated[
        str | None,
        typer.Option("--model", help="Explicit model for the Codex agent."),
    ] = None,
    agent_timeout_seconds: Annotated[
        float | None,
        typer.Option(
            "--agent-timeout",
            help=(
                "Agent execution timeout in seconds; separate from evaluation "
                "timeout."
            ),
        ),
    ] = None,
    docker: Annotated[
        bool,
        typer.Option("--docker", help="Evaluate each Run inside Docker."),
    ] = False,
) -> None:
    """Execute and persist one completed repeated Experiment."""

    _validate_execution_options(
        "experiment",
        agent=agent,
        model=model,
        agent_timeout_seconds=agent_timeout_seconds,
    )
    if runs < 1:
        typer.echo("Error: --runs must be a positive integer.", err=True)
        raise typer.Exit(code=1)

    agent_factory = _agent_factory(agent, model)
    sandbox = _sandbox_for(docker)
    configuration = ExperimentConfiguration(
        agent_name=agent,
        requested_model=model,
        agent_timeout_seconds=agent_timeout_seconds,
        evaluation_backend="docker" if sandbox is not None else "host",
    )
    results_root = Path.cwd() / "results"

    try:
        record = run_experiment(
            task_path,
            requested_runs=runs,
            configuration=configuration,
            agent_factory=agent_factory,
            results_root=results_root,
            sandbox=sandbox,
        )
        metadata = FilesystemArtifactStore(results_root).save_experiment(record)
    except (
        ArtifactStoreError,
        DockerSandboxError,
        EvaluationError,
        AgentInfrastructureError,
        AgentSetupError,
        ExperimentOrchestrationError,
        RepositoryError,
        TaskLoadError,
    ) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error

    _echo_experiment_summary(record, metadata)


if __name__ == "__main__":
    app()
