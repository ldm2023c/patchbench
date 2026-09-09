"""Pure deterministic classification of directly observable Run failures."""

from enum import Enum

from patchbench.agents.base import AgentRunStatus
from patchbench.domain.models import DomainModel, NonEmptyString, RunRecord


class FailureCategory(str, Enum):
    """Directly observable failure conditions for one completed Run."""

    AGENT_COMMAND_FAILED = "agent_command_failed"
    AGENT_TIMED_OUT = "agent_timed_out"
    NO_PATCH = "no_patch"
    TEST_FAILED = "test_failed"


class FailureAnalysis(DomainModel):
    """Ordered failure categories observed for one completed Run."""

    run_id: NonEmptyString
    categories: list[FailureCategory]


def classify_run_failure(
    run: RunRecord,
    *,
    patch_text: str,
) -> FailureAnalysis:
    """Classify a completed Run using only its record and loaded patch evidence."""

    categories: list[FailureCategory] = []

    if run.agent.status is AgentRunStatus.COMMAND_FAILED:
        categories.append(FailureCategory.AGENT_COMMAND_FAILED)
    if run.agent.status is AgentRunStatus.TIMED_OUT:
        categories.append(FailureCategory.AGENT_TIMED_OUT)
    if not run.evaluation_passed and not patch_text.strip():
        categories.append(FailureCategory.NO_PATCH)
    if not run.evaluation_passed:
        categories.append(FailureCategory.TEST_FAILED)

    return FailureAnalysis(run_id=run.run_id, categories=categories)
