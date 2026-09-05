"""Command-line interface for PatchBench."""

from pathlib import Path
from typing import Annotated

import typer

from patchbench.agents.fake import FakeAgentError
from patchbench.application.local_run import run_task
from patchbench.config.task_loader import TaskLoadError, load_task
from patchbench.evaluators.command import EvaluationError
from patchbench.repository.git_repository import RepositoryError
from patchbench.storage.filesystem import ArtifactStoreError


app = typer.Typer(
    help="Validate tasks and execute deterministic local PatchBench Runs.",
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
        str, typer.Option("--agent", help="Agent to execute; only 'fake' is supported.")
    ],
) -> None:
    """Execute one deterministic local Run."""

    if agent != "fake":
        typer.echo("Error: Milestone 1 supports only the 'fake' agent.", err=True)
        raise typer.Exit(code=1)

    try:
        record = run_task(task_path)
    except (
        ArtifactStoreError,
        EvaluationError,
        FakeAgentError,
        RepositoryError,
        TaskLoadError,
    ) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error

    outcome = "PASS" if record.evaluation_passed else "FAIL"
    typer.echo(f"Run ID:    {record.run_id}")
    typer.echo(f"Task ID:   {record.task_id}")
    typer.echo(f"Result:    {outcome}")
    typer.echo(f"Artifacts: {record.artifacts.directory}")


if __name__ == "__main__":
    app()
