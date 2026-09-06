"""Evaluate a task command through an existing sandbox."""

import shlex
from time import perf_counter

from patchbench.domain.models import EvaluationConfig, EvaluationResult
from patchbench.evaluators.command import EvaluationError
from patchbench.sandbox.base import Sandbox, SandboxHandle


class SandboxCommandEvaluator:
    """Execute a configured evaluation through the Sandbox contract."""

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox

    def evaluate(
        self,
        handle: SandboxHandle,
        configuration: EvaluationConfig,
    ) -> EvaluationResult:
        """Run the configured evaluation inside an existing sandbox."""

        try:
            arguments = shlex.split(configuration.command)
        except ValueError as error:
            raise EvaluationError(f"Invalid evaluation command: {error}") from error
        if not arguments or not arguments[0]:
            raise EvaluationError("Invalid evaluation command: missing executable")

        started = perf_counter()
        completed = self._sandbox.exec(
            handle,
            arguments,
            timeout_seconds=configuration.timeout_seconds,
        )
        return EvaluationResult(
            exit_code=completed.exit_code,
            passed=completed.exit_code == 0,
            duration_seconds=perf_counter() - started,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
