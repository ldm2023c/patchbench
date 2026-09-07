import json
import os
from pathlib import Path
import subprocess

import pytest

from patchbench.agents.fake import FakeAgent
from patchbench.application.local_run import run_task
from patchbench.config.task_loader import load_task
from patchbench.domain.models import EvaluationConfig
from patchbench.domain.models import RunStatus
from patchbench.evaluators.sandbox import SandboxCommandEvaluator
from patchbench.sandbox.base import (
    SandboxHandle,
    SandboxResourceLimits,
    sandbox_scope,
)
from patchbench.sandbox.docker import DockerSandbox, DockerSandboxTimeoutError
from scripts.prepare_example_fixture import TASK_PATH, prepare_fixture
from tests.helpers import git


pytestmark = pytest.mark.docker


@pytest.fixture(autouse=True)
def require_docker_opt_in() -> None:
    if os.environ.get("PATCHBENCH_RUN_DOCKER_TESTS") != "1":
        pytest.skip("set PATCHBENCH_RUN_DOCKER_TESTS=1 to run Docker tests")

    try:
        completed = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        pytest.skip(f"Docker CLI is unavailable: {error}")
    if completed.returncode != 0:
        pytest.skip(f"Docker daemon is unavailable: {completed.stderr.strip()}")


def container_exists(handle: SandboxHandle) -> bool:
    completed = subprocess.run(
        ["docker", "container", "inspect", handle.identifier],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def container_is_running(handle: SandboxHandle) -> bool:
    completed = subprocess.run(
        [
            "docker",
            "container",
            "inspect",
            "--format",
            "{{.State.Running}}",
            handle.identifier,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip() == "true"


def container_resource_limits(handle: SandboxHandle) -> tuple[int, int]:
    completed = subprocess.run(
        [
            "docker",
            "container",
            "inspect",
            "--format",
            "{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}}",
            handle.identifier,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    nano_cpus, memory_bytes = completed.stdout.split()
    return int(nano_cpus), int(memory_bytes)


def test_docker_sandbox_creates_and_destroys_container() -> None:
    sandbox = DockerSandbox()
    handle = sandbox.create()

    try:
        assert handle.identifier
        assert container_exists(handle)
        assert container_is_running(handle)
    finally:
        sandbox.destroy(handle)

    assert not container_exists(handle)
    sandbox.destroy(handle)


def test_docker_sandbox_scope_cleans_up_after_exception() -> None:
    sandbox = DockerSandbox()
    created_handle: SandboxHandle | None = None

    with pytest.raises(RuntimeError, match="simulated failure"):
        with sandbox_scope(sandbox) as handle:
            created_handle = handle
            assert container_exists(handle)
            raise RuntimeError("simulated failure")

    assert created_handle is not None
    assert not container_exists(created_handle)


def test_docker_sandbox_applies_resource_limits(tmp_path) -> None:
    limits = SandboxResourceLimits(cpus=0.5, memory_bytes=64 * 1024 * 1024)
    sandbox = DockerSandbox()

    with sandbox_scope(
        sandbox,
        workspace=tmp_path,
        resource_limits=limits,
    ) as handle:
        assert container_resource_limits(handle) == (500_000_000, 67_108_864)

        result = sandbox.exec(
            handle,
            ["python", "-c", "print('bounded sandbox')"],
            timeout_seconds=5,
        )

        assert result.exit_code == 0
        assert result.stdout == "bounded sandbox\n"


def test_docker_sandbox_timeout_removes_container(tmp_path) -> None:
    sandbox = DockerSandbox()
    created_handle: SandboxHandle | None = None

    with pytest.raises(DockerSandboxTimeoutError, match="timed out"):
        with sandbox_scope(sandbox, workspace=tmp_path) as handle:
            created_handle = handle
            sandbox.exec(
                handle,
                ["python", "-c", "import time; time.sleep(30)"],
                timeout_seconds=0.25,
            )

    assert created_handle is not None
    assert not container_exists(created_handle)


def test_sandbox_command_evaluator_executes_in_mounted_workspace(tmp_path) -> None:
    (tmp_path / "evaluation-input.txt").write_text(
        "workspace observed",
        encoding="utf-8",
    )
    sandbox = DockerSandbox()
    evaluator = SandboxCommandEvaluator(sandbox)
    created_handle: SandboxHandle | None = None

    with sandbox_scope(sandbox, workspace=tmp_path) as handle:
        created_handle = handle
        result = evaluator.evaluate(
            handle,
            EvaluationConfig(
                command=(
                    'python -c "from pathlib import Path; '
                    "print(Path('evaluation-input.txt').read_text())\""
                ),
                timeout_seconds=5,
            ),
        )
        failed_result = evaluator.evaluate(
            handle,
            EvaluationConfig(
                command=(
                    'python -c "import sys; '
                    "print('evaluation failed', file=sys.stderr); "
                    'raise SystemExit(4)"'
                ),
                timeout_seconds=5,
            ),
        )

        assert result.exit_code == 0
        assert result.passed is True
        assert result.stdout == "workspace observed"
        assert failed_result.exit_code == 4
        assert failed_result.passed is False
        assert failed_result.stderr == "evaluation failed"

    assert created_handle is not None
    assert not container_exists(created_handle)


def test_docker_backed_local_run_completes_example_task(tmp_path) -> None:
    task = load_task(TASK_PATH)
    source = Path(task.repository.path)
    expected_commit = task.repository.base_commit
    assert prepare_fixture(source, expected_commit) == expected_commit
    source_contents = (source / "calculator.py").read_text(encoding="utf-8")
    source_status = git(source, "status", "--porcelain")
    workspace_root = tmp_path / "workspaces"

    record = run_task(
        TASK_PATH,
        agent=FakeAgent(),
        workspace_root=workspace_root,
        results_root=tmp_path / "results",
        sandbox=DockerSandbox(),
    )

    assert record.status is RunStatus.PASSED
    assert record.evaluation_passed is True
    assert {path.name for path in record.artifacts.directory.iterdir()} == {
        "metadata.json",
        "agent.log",
        "test.log",
        "patch.diff",
    }
    metadata = json.loads(record.artifacts.metadata.read_text(encoding="utf-8"))
    assert metadata["status"] == "passed"
    assert metadata["evaluation_passed"] is True
    assert "FakeAgent processed task" in record.artifacts.agent_log.read_text()
    test_log = record.artifacts.test_log.read_text(encoding="utf-8")
    assert "python -B -m unittest -q" in test_log
    assert "Ran 1 test" in test_log
    assert "OK" in test_log
    patch = record.artifacts.patch.read_text(encoding="utf-8")
    assert "-    return a - b" in patch
    assert "+    return a + b" in patch
    assert (source / "calculator.py").read_text(encoding="utf-8") == source_contents
    assert git(source, "status", "--porcelain") == source_status
    assert git(source, "rev-parse", "HEAD") == expected_commit
    assert not (workspace_root / record.run_id).exists()
    assert git(source, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label={DockerSandbox.label}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip() == ""


def test_workspace_mount_and_command_execution(tmp_path) -> None:
    (tmp_path / "input.txt").write_text("hello from host", encoding="utf-8")
    sandbox = DockerSandbox()
    created_handle: SandboxHandle | None = None

    with sandbox_scope(sandbox, workspace=tmp_path) as handle:
        created_handle = handle
        result = sandbox.exec(
            handle,
            [
                "python",
                "-c",
                (
                    "from pathlib import Path; "
                    "text = Path('input.txt').read_text(); "
                    "Path('output.txt').write_text(text.upper()); "
                    "print(text)"
                ),
            ],
        )
        failed_result = sandbox.exec(
            handle,
            [
                "python",
                "-c",
                "import sys; print('expected error', file=sys.stderr); sys.exit(7)",
            ],
        )

        assert result.exit_code == 0
        assert result.stdout == "hello from host\n"
        assert result.stderr == ""
        assert (tmp_path / "output.txt").read_text() == "HELLO FROM HOST"
        assert failed_result.exit_code == 7
        assert failed_result.stderr == "expected error\n"

    assert created_handle is not None
    assert not container_exists(created_handle)
