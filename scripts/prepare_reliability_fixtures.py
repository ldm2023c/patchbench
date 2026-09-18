"""Prepare reliability candidates using the established hardened fixture workflow.

Run from the PatchBench root: python -m scripts.prepare_reliability_fixtures
Only ignored reliability repositories are created; Pilot state is never prepared.
"""
from pathlib import Path
import subprocess

from patchbench.config.task_loader import load_task
from scripts.prepare_pilot_fixtures import (
    FixturePreparationError, PROJECT_ROOT, git, prepare_fixture, template_files,
)

CANDIDATES = ("streaming_events", "request_signing", "atomic_batch", "cache_revalidation",
              "env_config", "byte_ranges", "config_resolution", "message_codec")
FIXTURE_ROOT = PROJECT_ROOT / "fixtures" / "reliability"


def main() -> None:
    try:
        for name in CANDIDATES:
            task = load_task(PROJECT_ROOT / "tasks" / "reliability" / name / "task.yaml")
            destination = FIXTURE_ROOT / ".prepared" / name
            if Path(task.repository.path) != destination:
                raise FixturePreparationError(f"Unexpected task repository: {task.repository.path}")
            commit = prepare_fixture(FIXTURE_ROOT / name, destination, task.repository.base_commit)
            print(f"{name}: {commit}")
    except (FixturePreparationError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Unable to prepare reliability fixtures: {error}") from error


if __name__ == "__main__":
    main()
