"""Command-line interface for PatchBench."""

from pathlib import Path
from typing import Annotated

import typer

from patchbench.config.task_loader import TaskLoadError, load_task


app = typer.Typer(
    help="Validate PatchBench coding-agent task definitions.",
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


if __name__ == "__main__":
    app()
