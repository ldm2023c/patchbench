"""Evaluate a task command in an isolated local workspace."""

from pathlib import Path
import shlex
import subprocess
from time import perf_counter

from patchbench.domain.models import EvaluationConfig, EvaluationResult


class EvaluationError(RuntimeError):
    """Raised when an evaluation command cannot be parsed."""


class CommandEvaluator:
    """Execute a configured command without invoking a shell."""

    def evaluate(
        self, workspace: Path, configuration: EvaluationConfig
    ) -> EvaluationResult:
        """Run the configured evaluation and capture its actual result."""

        try:
            arguments = shlex.split(configuration.command)
        except ValueError as error:
            raise EvaluationError(f"Invalid evaluation command: {error}") from error

        started = perf_counter()
        try:
            completed = subprocess.run(
                arguments,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=configuration.timeout_seconds,
                check=False,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as error:
            exit_code = 124
            stdout = self._timeout_text(error.stdout)
            stderr = self._timeout_text(error.stderr)
            stderr += (
                f"\nEvaluation timed out after {configuration.timeout_seconds} seconds.\n"
            )
        except OSError as error:
            exit_code = 127
            stdout = ""
            stderr = f"Unable to execute evaluation command: {error}\n"

        return EvaluationResult(
            exit_code=exit_code,
            passed=exit_code == 0,
            duration_seconds=perf_counter() - started,
            stdout=stdout,
            stderr=stderr,
        )

    @staticmethod
    def _timeout_text(output: str | bytes | None) -> str:
        if output is None:
            return ""
        if isinstance(output, bytes):
            return output.decode(errors="replace")
        return output
