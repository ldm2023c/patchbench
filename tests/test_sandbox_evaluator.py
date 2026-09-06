import pytest

from patchbench.domain.models import EvaluationConfig
from patchbench.evaluators.command import EvaluationError
from patchbench.evaluators.sandbox import SandboxCommandEvaluator
from patchbench.sandbox.base import SandboxExecResult, SandboxHandle
from patchbench.sandbox.docker import DockerSandboxError, DockerSandboxTimeoutError


class StubSandbox:
    def __init__(
        self,
        result: SandboxExecResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[SandboxHandle, list[str], float | None]] = []

    def exec(
        self,
        handle: SandboxHandle,
        command: list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> SandboxExecResult:
        self.calls.append((handle, command, timeout_seconds))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def evaluation_config(command: str, timeout_seconds: int = 12) -> EvaluationConfig:
    return EvaluationConfig(command=command, timeout_seconds=timeout_seconds)


def test_evaluator_parses_argv_forwards_timeout_and_returns_success(
    monkeypatch,
) -> None:
    sandbox = StubSandbox(
        SandboxExecResult(
            exit_code=0,
            stdout="tests passed",
            stderr="warning",
        )
    )
    handle = SandboxHandle(identifier="sandbox-123")
    times = iter([10.0, 10.25])
    monkeypatch.setattr(
        "patchbench.evaluators.sandbox.perf_counter",
        lambda: next(times),
    )

    result = SandboxCommandEvaluator(sandbox).evaluate(
        handle,
        evaluation_config('python -c "print(123)"'),
    )

    assert sandbox.calls == [
        (handle, ["python", "-c", "print(123)"], 12)
    ]
    assert result.exit_code == 0
    assert result.passed is True
    assert result.duration_seconds == 0.25
    assert result.stdout == "tests passed"
    assert result.stderr == "warning"


def test_evaluator_returns_nonzero_as_failed_result() -> None:
    sandbox = StubSandbox(
        SandboxExecResult(
            exit_code=3,
            stdout="one failure",
            stderr="assertion failed",
        )
    )

    result = SandboxCommandEvaluator(sandbox).evaluate(
        SandboxHandle(identifier="sandbox-123"),
        evaluation_config("python -m unittest"),
    )

    assert result.exit_code == 3
    assert result.passed is False
    assert result.duration_seconds >= 0
    assert result.stdout == "one failure"
    assert result.stderr == "assertion failed"


@pytest.mark.parametrize(
    "error",
    [
        DockerSandboxError("daemon unavailable"),
        DockerSandboxTimeoutError("evaluation timed out"),
    ],
)
def test_evaluator_propagates_sandbox_infrastructure_error(error) -> None:
    sandbox = StubSandbox(error=error)

    with pytest.raises(type(error)) as raised:
        SandboxCommandEvaluator(sandbox).evaluate(
            SandboxHandle(identifier="sandbox-123"),
            evaluation_config("python -m unittest"),
        )

    assert raised.value is error


@pytest.mark.parametrize("command", ['"', '""'])
def test_evaluator_rejects_invalid_or_empty_parsed_command(command) -> None:
    sandbox = StubSandbox(
        SandboxExecResult(exit_code=0, stdout="", stderr="")
    )

    with pytest.raises(EvaluationError, match="Invalid evaluation command"):
        SandboxCommandEvaluator(sandbox).evaluate(
            SandboxHandle(identifier="sandbox-123"),
            evaluation_config(command),
        )

    assert sandbox.calls == []
