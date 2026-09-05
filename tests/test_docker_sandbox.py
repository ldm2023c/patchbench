import os
import subprocess

import pytest

from patchbench.sandbox.base import SandboxHandle, sandbox_scope
from patchbench.sandbox.docker import DockerSandbox


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
