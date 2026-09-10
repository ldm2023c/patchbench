"""Pure semantic TaskSpec fingerprinting, independent of repository location."""

import hashlib
import json

from patchbench.domain.models import TaskSpec


def compute_task_fingerprint(task: TaskSpec, *, base_commit_used: str) -> str:
    """Hash validated task semantics using the actual resolved workspace commit."""
    payload = {
        "schema_version": task.schema_version,
        "id": task.id,
        "repository": {
            "type": task.repository.type,
            "base_commit": base_commit_used,
        },
        "task": {"prompt": task.task.prompt},
        "evaluation": {
            "command": task.evaluation.command,
            "timeout_seconds": task.evaluation.timeout_seconds,
        },
        "metadata": task.metadata.model_dump(mode="json"),
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
