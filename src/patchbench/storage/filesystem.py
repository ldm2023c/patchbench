"""Filesystem persistence for completed Runs, Experiments, and Replays."""

import json
from pathlib import Path

from pydantic import ValidationError

from patchbench.agents.base import AgentRunResult
from patchbench.domain.models import (
    ArtifactPaths,
    EvaluationResult,
    ExperimentRecord,
    ReplayRecord,
    RunRecord,
)


class ArtifactStoreError(RuntimeError):
    """Raised when completed artifacts cannot be created or written."""


class FilesystemArtifactStore:
    """Load Run evidence and persist completed Run, Experiment, or Replay data."""

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

    def load_run_record(self, run_id: str) -> RunRecord:
        """Load one canonical Run metadata document by safe direct-child ID."""

        metadata = self._run_directory(run_id) / "metadata.json"
        try:
            raw_record = json.loads(metadata.read_text(encoding="utf-8"))
            record = RunRecord.model_validate(raw_record)
        except (OSError, UnicodeError) as error:
            raise ArtifactStoreError(
                f"Unable to load Run metadata '{metadata}': {error}"
            ) from error
        except (json.JSONDecodeError, ValidationError) as error:
            raise ArtifactStoreError(
                f"Invalid Run metadata '{metadata}': {error}"
            ) from error

        if record.run_id != run_id:
            raise ArtifactStoreError(
                f"Run metadata ID '{record.run_id}' does not match requested "
                f"run ID '{run_id}'"
            )
        return record

    def load_run_patch(self, run_id: str) -> str:
        """Load one canonical historical patch by safe direct-child Run ID."""

        patch = self._run_directory(run_id) / "patch.diff"
        try:
            return patch.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ArtifactStoreError(
                f"Unable to load Run patch '{patch}': {error}"
            ) from error

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

        test_log = self._evaluation_log(evaluation_result, evaluation_command)
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

    def save_experiment(self, record: ExperimentRecord) -> Path:
        """Persist one completed Experiment metadata document and return its path."""

        directory = self.results_root / "experiments" / record.experiment_id
        metadata = directory / "metadata.json"
        try:
            directory.mkdir(parents=True, exist_ok=False)
            metadata.write_text(
                json.dumps(record.model_dump(mode="json"), indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as error:
            raise ArtifactStoreError(
                f"Unable to persist Experiment metadata '{metadata}': {error}"
            ) from error
        return metadata

    def save_replay(
        self,
        record: ReplayRecord,
        evaluation_result: EvaluationResult,
        evaluation_command: str,
    ) -> Path:
        """Persist one completed Replay and return its metadata path."""

        directory = self.results_root / "replays" / record.replay_id
        metadata = directory / "metadata.json"
        test_log = directory / "test.log"
        try:
            directory.mkdir(parents=True, exist_ok=False)
            test_log.write_text(
                self._evaluation_log(evaluation_result, evaluation_command),
                encoding="utf-8",
            )
            metadata.write_text(
                json.dumps(record.model_dump(mode="json"), indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as error:
            raise ArtifactStoreError(
                f"Unable to persist Replay artifacts '{directory}': {error}"
            ) from error
        return metadata

    def _run_directory(self, run_id: str) -> Path:
        candidate = (self.results_root / run_id).resolve()
        if candidate.parent != self.results_root or candidate.name != run_id:
            raise ArtifactStoreError(f"Unsafe Run ID for artifact lookup: '{run_id}'")
        return candidate

    @staticmethod
    def _evaluation_log(
        evaluation_result: EvaluationResult,
        evaluation_command: str,
    ) -> str:
        return (
            f"Command: {evaluation_command}\n"
            f"Exit code: {evaluation_result.exit_code}\n"
            f"Duration seconds: {evaluation_result.duration_seconds:.6f}\n\n"
            f"STDOUT:\n{evaluation_result.stdout}\n"
            f"STDERR:\n{evaluation_result.stderr}"
        )
