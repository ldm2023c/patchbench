"""Command-line interface for PatchBench."""

from math import isfinite
from pathlib import Path
from typing import Annotated

import typer

from patchbench.agents.base import AgentInfrastructureError, AgentSetupError
from patchbench.agents.codex import CodexAdapter
from patchbench.agents.fake import FakeAgent
from patchbench.application.local_run import run_task
from patchbench.config.task_loader import TaskLoadError, load_task
from patchbench.evaluators.command import EvaluationError
from patchbench.repository.git_repository import RepositoryError
from patchbench.sandbox.docker import DockerSandbox, DockerSandboxError
from patchbench.storage.filesystem import ArtifactStoreError


app = typer.Typer(
    help="Validate tasks and execute local PatchBench Runs.",
    no_args_is_help=True,
)


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

    if agent not in {"fake", "codex"}:
        typer.echo("Error: The run command supports only 'fake' or 'codex'.", err=True)
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

    try:
        if agent == "fake":
            selected_agent = FakeAgent()
        else:
            assert model is not None
            selected_agent = CodexAdapter(model=model)
        record = run_task(
            task_path,
            agent=selected_agent,
            agent_name=agent,
            agent_timeout_seconds=agent_timeout_seconds,
            requested_model=model,
            sandbox=DockerSandbox() if docker else None,
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


if __name__ == "__main__":
    app()
