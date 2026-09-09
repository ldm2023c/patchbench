"""Pure deterministic comparison of one explicit PASS Run and FAIL Run."""

from patchbench.agents.base import AgentRunStatus
from patchbench.domain.failure import FailureCategory, classify_run_failure
from patchbench.domain.models import DomainModel, NonEmptyString, RunRecord


class PassFailComparisonError(ValueError):
    """Raised when supplied Runs do not satisfy the PASS-vs-FAIL contract."""


class PassFailComparison(DomainModel):
    """Directly observable differences between an explicit PASS and FAIL Run."""

    task_id: NonEmptyString
    pass_run_id: NonEmptyString
    fail_run_id: NonEmptyString
    pass_agent_status: AgentRunStatus
    fail_agent_status: AgentRunStatus
    pass_failure_categories: list[FailureCategory]
    fail_failure_categories: list[FailureCategory]
    pass_has_patch: bool
    fail_has_patch: bool
    patches_equal: bool
    fail_minus_pass_duration_seconds: float


def compare_pass_fail_runs(
    pass_run: RunRecord,
    fail_run: RunRecord,
    *,
    pass_patch_text: str,
    fail_patch_text: str,
) -> PassFailComparison:
    """Compare explicitly assigned PASS and FAIL Runs using already-loaded evidence."""

    if not pass_run.evaluation_passed:
        raise PassFailComparisonError("pass_run must have a passing evaluation")
    if fail_run.evaluation_passed:
        raise PassFailComparisonError("fail_run must have a failing evaluation")
    if pass_run.task_id != fail_run.task_id:
        raise PassFailComparisonError("PASS and FAIL Runs must have the same task_id")
    if pass_run.run_id == fail_run.run_id:
        raise PassFailComparisonError("PASS and FAIL Runs must have different run_ids")

    pass_analysis = classify_run_failure(pass_run, patch_text=pass_patch_text)
    fail_analysis = classify_run_failure(fail_run, patch_text=fail_patch_text)

    return PassFailComparison(
        task_id=pass_run.task_id,
        pass_run_id=pass_run.run_id,
        fail_run_id=fail_run.run_id,
        pass_agent_status=pass_run.agent.status,
        fail_agent_status=fail_run.agent.status,
        pass_failure_categories=pass_analysis.categories,
        fail_failure_categories=fail_analysis.categories,
        pass_has_patch=bool(pass_patch_text.strip()),
        fail_has_patch=bool(fail_patch_text.strip()),
        patches_equal=pass_patch_text == fail_patch_text,
        fail_minus_pass_duration_seconds=(
            fail_run.duration_seconds - pass_run.duration_seconds
        ),
    )
