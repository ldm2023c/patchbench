import hashlib
import json

import pytest
from pydantic import ValidationError

from patchbench.domain.models import EvaluationConfig, FrozenUnittestConfig, FROZEN_UNITTEST_COMMAND, TaskSpec
from patchbench.domain.provenance import compute_task_fingerprint
from tests.test_provenance import semantic_task


@pytest.mark.parametrize("files", [[], ["test_a.py", "test_a.py"], ["."], [".."],
    ["/test_a.py"], ["../test_a.py"], ["dir/test_a.py"], ["dir\\test_a.py"],
    ["C:test_a.py"], [".patchbench-eval"], ["test.txt"], [".py"],
    [" test_a.py"], ["test_a.py\n"], ["test\x00.py"], [7]])
def test_rejects_invalid_frozen_file_contract(files):
    with pytest.raises(ValidationError):
        FrozenUnittestConfig(version=1, test_files=files)


@pytest.mark.parametrize("version", [0, 2, True, 1.0, "1"])
def test_only_integer_protocol_one_is_accepted(version):
    with pytest.raises(ValidationError):
        FrozenUnittestConfig(version=version, test_files=["test_a.py"])


def test_fixed_runner_command_and_no_support_files():
    frozen = dict(version=1, test_files=["test_a.py"])
    with pytest.raises(ValidationError, match="requires command"):
        EvaluationConfig(command="python -c 'pass'", timeout_seconds=1, frozen_unittest=frozen)
    with pytest.raises(ValidationError):
        FrozenUnittestConfig(**frozen, support_files=[])
    assert EvaluationConfig(command="anything", timeout_seconds=1).frozen_unittest is None
    assert EvaluationConfig(command=FROZEN_UNITTEST_COMMAND, timeout_seconds=1,
                            frozen_unittest=frozen).frozen_unittest.test_files == ["test_a.py"]


def test_legacy_fingerprint_preserves_pre_extension_payload_with_explicit_null():
    task = semantic_task()
    raw = task.model_dump()
    raw["evaluation"]["frozen_unittest"] = None
    task = TaskSpec.model_validate(raw)
    old_payload = {
        "schema_version": 1, "id": "task",
        "repository": {"type": "local", "base_commit": "a" * 40},
        "task": {"prompt": "修复 café\nKeep behavior."},
        "evaluation": {"command": "python -B -m unittest -v", "timeout_seconds": 120},
        "metadata": {"language": "python"},
    }
    expected = hashlib.sha256(json.dumps(old_payload, sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=False).encode()).hexdigest()
    assert compute_task_fingerprint(task, base_commit_used="a" * 40) == expected


def test_frozen_fingerprint_pins_order_files_and_protocol():
    raw = semantic_task().model_dump()
    raw["evaluation"].update(command=FROZEN_UNITTEST_COMMAND,
                             frozen_unittest={"version": 1, "test_files": ["test_a.py", "test_b.py"]})
    task = TaskSpec.model_validate(raw)
    fingerprint = compute_task_fingerprint(task, base_commit_used="a" * 40)
    for files in (["test_b.py", "test_a.py"], ["test_a.py"], ["test_c.py", "test_b.py"]):
        changed = task.model_copy(deep=True)
        changed.evaluation.frozen_unittest.test_files = files
        assert compute_task_fingerprint(changed, base_commit_used="a" * 40) != fingerprint
    # Version 2 is rejected by validation today; bypass only to prove hashing
    # retains the protocol field if a later version is introduced.
    changed = task.model_copy(deep=True)
    changed.evaluation.frozen_unittest = changed.evaluation.frozen_unittest.model_copy(update={"version": 2})
    assert compute_task_fingerprint(changed, base_commit_used="a" * 40) != fingerprint
    legacy = task.model_copy(deep=True)
    legacy.evaluation.frozen_unittest = None
    assert compute_task_fingerprint(legacy, base_commit_used="a" * 40) != fingerprint
