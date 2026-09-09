from pathlib import Path

import pytest

from patchbench.agents.base import AgentRunStatus
from patchbench.domain import (
    AgentExecutionMetadata,
    ArtifactPaths,
    FailureCategory,
    PassFailComparisonError,
    RunRecord,
    RunStatus,
    compare_pass_fail_runs,
)


def make_run(
    run_id: str,
    *,
    evaluation_passed: bool,
    agent_status: AgentRunStatus = AgentRunStatus.COMPLETED,
    task_id: str = "example_bug",
    duration_seconds: float = 10.0,
    agent_name: str = "codex",
    requested_model: str | None = "test-model",
) -> RunRecord:
    artifact_directory = Path("/results") / run_id
    artifact_paths = {
        name: artifact_directory / name for name in ArtifactPaths.model_fields
    }
    exit_code = {
        AgentRunStatus.COMPLETED: 0,
        AgentRunStatus.COMMAND_FAILED: 7,
        AgentRunStatus.TIMED_OUT: None,
    }[agent_status]
    return RunRecord(
        run_id=run_id,
        task_id=task_id,
        status=RunStatus.PASSED if evaluation_passed else RunStatus.FAILED,
        evaluation_passed=evaluation_passed,
        duration_seconds=duration_seconds,
        agent=AgentExecutionMetadata(
            name=agent_name,
            backend="host",
            status=agent_status,
            exit_code=exit_code,
            duration_seconds=duration_seconds / 2,
            timeout_seconds=30,
            requested_model=requested_model,
        ),
        artifacts=ArtifactPaths(**artifact_paths),
    )


def test_compare_ordinary_pass_and_fail_runs() -> None:
    pass_run = make_run("pass-1", evaluation_passed=True, duration_seconds=10)
    fail_run = make_run("fail-1", evaluation_passed=False, duration_seconds=12)

    comparison = compare_pass_fail_runs(
        pass_run,
        fail_run,
        pass_patch_text="patch A",
        fail_patch_text="patch B",
    )

    assert comparison.model_dump(mode="json") == {
        "task_id": "example_bug",
        "pass_run_id": "pass-1",
        "fail_run_id": "fail-1",
        "pass_agent_status": "completed",
        "fail_agent_status": "completed",
        "pass_failure_categories": [],
        "fail_failure_categories": ["test_failed"],
        "pass_has_patch": True,
        "fail_has_patch": True,
        "patches_equal": False,
        "fail_minus_pass_duration_seconds": 2.0,
    }


def test_comparison_preserves_timed_out_fail_status_and_categories() -> None:
    pass_run = make_run("pass-1", evaluation_passed=True)
    fail_run = make_run(
        "fail-1",
        evaluation_passed=False,
        agent_status=AgentRunStatus.TIMED_OUT,
    )

    comparison = compare_pass_fail_runs(
        pass_run,
        fail_run,
        pass_patch_text="pass patch",
        fail_patch_text="fail patch",
    )

    assert comparison.pass_agent_status is AgentRunStatus.COMPLETED
    assert comparison.fail_agent_status is AgentRunStatus.TIMED_OUT
    assert comparison.fail_failure_categories == [
        FailureCategory.AGENT_TIMED_OUT,
        FailureCategory.TEST_FAILED,
    ]


def test_comparison_classifies_whitespace_only_fail_patch_as_missing() -> None:
    comparison = compare_pass_fail_runs(
        make_run("pass-1", evaluation_passed=True),
        make_run("fail-1", evaluation_passed=False),
        pass_patch_text="pass patch",
        fail_patch_text=" \n\t",
    )

    assert comparison.fail_has_patch is False
    assert comparison.fail_failure_categories == [
        FailureCategory.NO_PATCH,
        FailureCategory.TEST_FAILED,
    ]


def test_pass_run_may_contain_agent_failure_observation() -> None:
    comparison = compare_pass_fail_runs(
        make_run(
            "pass-1",
            evaluation_passed=True,
            agent_status=AgentRunStatus.COMMAND_FAILED,
        ),
        make_run("fail-1", evaluation_passed=False),
        pass_patch_text="pass patch",
        fail_patch_text="fail patch",
    )

    assert comparison.pass_failure_categories == [
        FailureCategory.AGENT_COMMAND_FAILED
    ]
    assert comparison.fail_failure_categories == [FailureCategory.TEST_FAILED]


def test_exactly_equal_patch_text_is_reported_equal() -> None:
    comparison = compare_pass_fail_runs(
        make_run("pass-1", evaluation_passed=True),
        make_run("fail-1", evaluation_passed=False),
        pass_patch_text="same patch\n",
        fail_patch_text="same patch\n",
    )

    assert comparison.patches_equal is True


def test_empty_and_whitespace_patches_are_absent_but_not_equal() -> None:
    comparison = compare_pass_fail_runs(
        make_run("pass-1", evaluation_passed=True),
        make_run("fail-1", evaluation_passed=False),
        pass_patch_text="",
        fail_patch_text=" \n",
    )

    assert comparison.pass_has_patch is False
    assert comparison.fail_has_patch is False
    assert comparison.patches_equal is False


@pytest.mark.parametrize(
    ("pass_run", "fail_run", "message"),
    [
        (
            make_run("pass-1", evaluation_passed=False),
            make_run("fail-1", evaluation_passed=False),
            "pass_run",
        ),
        (
            make_run("pass-1", evaluation_passed=True),
            make_run("fail-1", evaluation_passed=True),
            "fail_run",
        ),
        (
            make_run("pass-1", evaluation_passed=True, task_id="task-a"),
            make_run("fail-1", evaluation_passed=False, task_id="task-b"),
            "task_id",
        ),
        (
            make_run("same-run", evaluation_passed=True),
            make_run("same-run", evaluation_passed=False),
            "different run_ids",
        ),
    ],
)
def test_comparison_rejects_invalid_pairs(
    pass_run: RunRecord,
    fail_run: RunRecord,
    message: str,
) -> None:
    with pytest.raises(PassFailComparisonError, match=message):
        compare_pass_fail_runs(
            pass_run,
            fail_run,
            pass_patch_text="pass patch",
            fail_patch_text="fail patch",
        )


def test_comparison_allows_different_agent_configurations() -> None:
    comparison = compare_pass_fail_runs(
        make_run(
            "pass-1",
            evaluation_passed=True,
            agent_name="fake",
            requested_model=None,
        ),
        make_run(
            "fail-1",
            evaluation_passed=False,
            agent_name="codex",
            requested_model="other-model",
        ),
        pass_patch_text="pass patch",
        fail_patch_text="fail patch",
    )

    assert comparison.task_id == "example_bug"


def test_comparison_is_repeatable() -> None:
    pass_run = make_run(
        "pass-1",
        evaluation_passed=True,
        agent_status=AgentRunStatus.COMMAND_FAILED,
        duration_seconds=12,
    )
    fail_run = make_run(
        "fail-1",
        evaluation_passed=False,
        agent_status=AgentRunStatus.TIMED_OUT,
        duration_seconds=10,
    )

    observed = [
        compare_pass_fail_runs(
            pass_run,
            fail_run,
            pass_patch_text="same patch",
            fail_patch_text="same patch",
        ).model_dump(mode="json")
        for _ in range(5)
    ]

    assert observed == [observed[0]] * 5
    assert observed[0]["pass_failure_categories"] == ["agent_command_failed"]
    assert observed[0]["fail_failure_categories"] == [
        "agent_timed_out",
        "test_failed",
    ]
    assert observed[0]["fail_minus_pass_duration_seconds"] == -2.0
