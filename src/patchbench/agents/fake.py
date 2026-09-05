"""Deterministic agent used to verify local Run orchestration."""

from pathlib import Path
from time import perf_counter

from patchbench.domain.models import AgentResult, TaskSpec


class FakeAgentError(RuntimeError):
    """Raised when the fixture does not contain the expected deterministic bug."""


class FakeAgent:
    """Repair the known calculator fixture without network or AI services."""

    _BUG = "return a - b"
    _FIX = "return a + b"

    def run(self, workspace: Path, task: TaskSpec) -> AgentResult:
        """Apply the one deterministic fixture edit and return its measured result."""

        started = perf_counter()
        target = workspace / "calculator.py"

        try:
            contents = target.read_text(encoding="utf-8")
        except OSError as error:
            raise FakeAgentError(
                f"Unable to read FakeAgent target '{target}': {error}"
            ) from error

        if contents.count(self._BUG) != 1:
            raise FakeAgentError(
                f"Expected exactly one known calculator bug in '{target}'"
            )

        try:
            target.write_text(contents.replace(self._BUG, self._FIX), encoding="utf-8")
        except OSError as error:
            raise FakeAgentError(
                f"Unable to update FakeAgent target '{target}': {error}"
            ) from error

        duration = perf_counter() - started
        log = (
            f"FakeAgent processed task '{task.id}'.\n"
            "Replaced the known subtraction bug in calculator.py with addition.\n"
        )
        return AgentResult(succeeded=True, duration_seconds=duration, log=log)
