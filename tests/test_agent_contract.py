from patchbench.agents.base import (
    AgentInfrastructureError,
    AgentRunStatus,
    AgentSetupError,
)


def test_agent_run_status_contains_only_execution_outcomes() -> None:
    assert [(status.name, status.value) for status in AgentRunStatus] == [
        ("COMPLETED", "completed"),
        ("COMMAND_FAILED", "command_failed"),
        ("TIMED_OUT", "timed_out"),
    ]


def test_agent_setup_and_infrastructure_failures_are_exceptions() -> None:
    assert issubclass(AgentSetupError, RuntimeError)
    assert issubclass(AgentInfrastructureError, RuntimeError)
    assert not isinstance(AgentSetupError("invalid setup"), AgentRunStatus)
    assert not isinstance(
        AgentInfrastructureError("infrastructure failed"), AgentRunStatus
    )
