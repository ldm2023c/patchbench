"""Filesystem persistence for completed local Runs."""

import json
from pathlib import Path

from patchbench.agents.base import AgentRunResult
from patchbench.domain.models import (
    ArtifactPaths,
    EvaluationResult,
    RunRecord,
)


class ArtifactStoreError(RuntimeError):
    """Raised when Run artifacts cannot be created or written."""


class FilesystemArtifactStore:
    """Persist the six required artifacts for one Run."""

    def __init__(self, results_root: Path) -> None:
        self.results_root = results_root.resolve()

    def create_paths(self, run_id: str) -> ArtifactPaths:
        """Create a unique artifact directory and describe its files."""

        directory = self.results_root / run_id
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except OSError as error:
            raise ArtifactStoreError(
                f"Unable to create artifact directory '{directory}': {error}"
            ) from error

        return ArtifactPaths(
            directory=directory,
            metadata=directory / "metadata.json",
            prompt=directory / "prompt.txt",
            agent_log=directory / "agent.log",
            agent_stderr_log=directory / "agent.stderr.log",
            test_log=directory / "test.log",
            patch=directory / "patch.diff",
        )

    def persist(
        self,
        record: RunRecord,
        agent_result: AgentRunResult,
        evaluation_result: EvaluationResult,
        evaluation_command: str,
        patch: str,
        effective_prompt: str,
    ) -> None:
        """Write measured Run data and captured logs to their artifact files."""

        test_log = (
            f"Command: {evaluation_command}\n"
            f"Exit code: {evaluation_result.exit_code}\n"
            f"Duration seconds: {evaluation_result.duration_seconds:.6f}\n\n"
            f"STDOUT:\n{evaluation_result.stdout}\n"
            f"STDERR:\n{evaluation_result.stderr}"
        )
        try:
            record.artifacts.metadata.write_text(
                json.dumps(record.model_dump(mode="json"), indent=2) + "\n",
                encoding="utf-8",
            )
            record.artifacts.prompt.write_text(effective_prompt, encoding="utf-8")
            record.artifacts.agent_log.write_text(
                agent_result.stdout, encoding="utf-8"
            )
            record.artifacts.agent_stderr_log.write_text(
                agent_result.stderr, encoding="utf-8"
            )
            record.artifacts.test_log.write_text(test_log, encoding="utf-8")
            record.artifacts.patch.write_text(patch, encoding="utf-8")
        except OSError as error:
            raise ArtifactStoreError(f"Unable to persist Run artifacts: {error}") from error
