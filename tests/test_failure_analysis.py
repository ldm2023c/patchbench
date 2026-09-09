from pathlib import Path

import pytest

from patchbench.agents.base import AgentRunStatus
from patchbench.domain import (
    AgentExecutionMetadata,
    ArtifactPaths,
    FailureCategory,
    RunRecord,
    RunStatus,
    classify_run_failure,
)


def make_run(
    *,
    agent_status: AgentRunStatus,
    evaluation_passed: bool,
) -> RunRecord:
    artifact_directory = Path("/results/run-1")
    artifact_paths = {
        name: artifact_directory / name for name in ArtifactPaths.model_fields
    }
    exit_code = {
        AgentRunStatus.COMPLETED: 0,
        AgentRunStatus.COMMAND_FAILED: 7,
        AgentRunStatus.TIMED_OUT: None,
    }[agent_status]
    return RunRecord(
        run_id="run-1",
        task_id="example_bug",
        status=RunStatus.PASSED if evaluation_passed else RunStatus.FAILED,
        evaluation_passed=evaluation_passed,
        duration_seconds=1.0,
        agent=AgentExecutionMetadata(
            name="codex",
            backend="host",
            status=agent_status,
            exit_code=exit_code,
            duration_seconds=0.5,
            timeout_seconds=30,
            requested_model="test-model",
        ),
        artifacts=ArtifactPaths(**artifact_paths),
    )


@pytest.mark.parametrize(
    ("agent_status", "evaluation_passed", "patch_text", "expected"),
    [
        (AgentRunStatus.COMPLETED, True, "diff --git a/a b/a", []),
        (
            AgentRunStatus.COMMAND_FAILED,
            True,
            "diff --git a/a b/a",
            [FailureCategory.AGENT_COMMAND_FAILED],
        ),
        (
            AgentRunStatus.TIMED_OUT,
            False,
            "diff --git a/a b/a",
            [FailureCategory.AGENT_TIMED_OUT, FailureCategory.TEST_FAILED],
        ),
        (
            AgentRunStatus.COMPLETED,
            False,
            "",
            [FailureCategory.NO_PATCH, FailureCategory.TEST_FAILED],
        ),
        (
            AgentRunStatus.COMMAND_FAILED,
            False,
            "  \n\t",
            [
                FailureCategory.AGENT_COMMAND_FAILED,
                FailureCategory.NO_PATCH,
                FailureCategory.TEST_FAILED,
            ],
        ),
        (AgentRunStatus.COMPLETED, True, "", []),
    ],
)
def test_classify_run_failure_cases(
    agent_status: AgentRunStatus,
    evaluation_passed: bool,
    patch_text: str,
    expected: list[FailureCategory],
) -> None:
    run = make_run(
        agent_status=agent_status,
        evaluation_passed=evaluation_passed,
    )

    analysis = classify_run_failure(run, patch_text=patch_text)

    assert analysis.run_id == run.run_id
    assert analysis.categories == expected


def test_classification_order_is_repeatable() -> None:
    run = make_run(
        agent_status=AgentRunStatus.COMMAND_FAILED,
        evaluation_passed=False,
    )
    expected = [
        FailureCategory.AGENT_COMMAND_FAILED,
        FailureCategory.NO_PATCH,
        FailureCategory.TEST_FAILED,
    ]

    observed = [
        classify_run_failure(run, patch_text="\n").categories for _ in range(5)
    ]

    assert observed == [expected] * 5


def test_failure_category_surface_has_canonical_order() -> None:
    assert list(FailureCategory) == [
        FailureCategory.AGENT_COMMAND_FAILED,
        FailureCategory.AGENT_TIMED_OUT,
        FailureCategory.NO_PATCH,
        FailureCategory.TEST_FAILED,
    ]
