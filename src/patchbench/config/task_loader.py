"""Load and validate PatchBench task definitions from YAML."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from patchbench.domain.models import TaskSpec


class TaskLoadError(ValueError):
    """Raised when a task file cannot be read, parsed, or validated."""


def load_task(path: str | Path) -> TaskSpec:
    """Read a YAML task file and validate it as a :class:`TaskSpec`."""

    task_path = Path(path)

    try:
        contents = task_path.read_text(encoding="utf-8")
    except OSError as error:
        raise TaskLoadError(f"Unable to read task file '{task_path}': {error}") from error

    try:
        raw_task = yaml.safe_load(contents)
    except yaml.YAMLError as error:
        raise TaskLoadError(f"Invalid YAML in task file '{task_path}': {error}") from error

    try:
        return TaskSpec.model_validate(raw_task)
    except ValidationError as error:
        raise TaskLoadError(
            f"Invalid task configuration in '{task_path}':\n{error}"
        ) from error
