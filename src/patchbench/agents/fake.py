"""Deterministic agent used to verify local Run orchestration."""

from patchbench.agents.base import (
    AgentInfrastructureError,
    AgentRunRequest,
    AgentRunResult,
    AgentRunStatus,
    AgentSetupError,
)


class FakeAgentError(AgentSetupError):
    """Raised when the fixture does not contain the expected deterministic bug."""


class FakeAgent:
    """Repair the known calculator fixture without network or AI services."""

    _BUG = "return a - b"
    _FIX = "return a + b"

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        """Apply the one deterministic fixture edit and return its result."""

        target = request.workspace / "calculator.py"

        try:
            contents = target.read_text(encoding="utf-8")
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to read FakeAgent target '{target}': {error}"
            ) from error

        if contents.count(self._BUG) != 1:
            raise FakeAgentError(
                f"Expected exactly one known calculator bug in '{target}'"
            )

        try:
            target.write_text(contents.replace(self._BUG, self._FIX), encoding="utf-8")
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to update FakeAgent target '{target}': {error}"
            ) from error

        log = (
            "FakeAgent processed task.\n"
            "Replaced the known subtraction bug in calculator.py with addition.\n"
        )
        return AgentRunResult(
            status=AgentRunStatus.COMPLETED,
            exit_code=0,
            stdout=log,
            stderr="",
            duration_seconds=0.0,
        )
