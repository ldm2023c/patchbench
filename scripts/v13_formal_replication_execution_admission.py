"""Build and verify the future M18B Replication-01 execution admission."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from patchbench.domain.formal_replication_execution import (
    V13FormalReplicationExecutionAdmission,
    V13FormalReplicationExecutionSource,
    compute_v13_formal_replication_execution_admission_sha256,
)
from scripts.v13_formal_incident import M16_REMEDIATION_COMMIT
from scripts.v13_formal_preregistration import ACCEPTED_AGENT_MANIFEST_SHA256
from scripts.v13_formal_replication_preregistration import (
    ACCEPTED_REPLICATION_PREREGISTRATION_SHA256,
    verify_replication_preregistration,
)


ADMISSION_PATH = Path(
    "evidence/v1.3/formal-replication-01/execution-admission.json"
)
EXECUTION_SOURCE_PATHS = (
    Path("scripts/run_v13_formal_replication.py"),
    Path("src/patchbench/application/v13_formal_execution.py"),
    Path("src/patchbench/application/v13_formal_replication_execution.py"),
)
REVIEWED_M18A_EXECUTION_HARNESS_COMMIT = (
    "4eed7a5dd50dd2358aaafb2fbc9d62a596803cdf"
)

ACCEPTED_REPLICATION_EXECUTION_ADMISSION_SHA256 = (
    "2dd1b8578a4f37163c4a142ba494399a0e49c362deef503670a15a3fedc70b96"
)
ACCEPTED_REPLICATION_EXECUTION_ADMISSION_BYTE_SHA256 = (
    "fcfea44f40ec82d768d4bedb6ddcc87a22ae1a89215bda0a07e91f2dc4b3efd0"
)


class FormalReplicationAdmissionIntegrityError(RuntimeError):
    pass


def _read_file(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise FormalReplicationAdmissionIntegrityError(f"missing or unsafe {label}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise FormalReplicationAdmissionIntegrityError(f"unable to read {label}") from error


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def build_replication_execution_admission(
    execution_harness_commit: str,
    *,
    project_root: Path = PROJECT_ROOT,
) -> V13FormalReplicationExecutionAdmission:
    if execution_harness_commit != REVIEWED_M18A_EXECUTION_HARNESS_COMMIT:
        raise FormalReplicationAdmissionIntegrityError(
            "execution harness commit is not the reviewed M18A commit"
        )
    root = Path(project_root).resolve()
    preregistration = verify_replication_preregistration(root)
    sources = tuple(V13FormalReplicationExecutionSource(
        path=path.as_posix(),
        byte_sha256=_sha256(_read_file(root / path, "execution source")),
    ) for path in EXECUTION_SOURCE_PATHS)
    return V13FormalReplicationExecutionAdmission(
        admission_id="patchbench-v1.3-replication-01-execution-admission",
        replication_id=preregistration.replication_id,
        study_id=preregistration.study_id,
        results_namespace=preregistration.formal_results_namespace,
        replication_preregistration_sha256=(
            ACCEPTED_REPLICATION_PREREGISTRATION_SHA256
        ),
        provider_failure_remediation_commit=M16_REMEDIATION_COMMIT,
        execution_harness_commit=execution_harness_commit,
        agent_manifest_sha256=ACCEPTED_AGENT_MANIFEST_SHA256,
        evaluation_backend="docker",
        execution_sources=sources,
    )


def deterministic_json(value: V13FormalReplicationExecutionAdmission) -> str:
    return json.dumps(value.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def load_checked_replication_execution_admission(
    project_root: Path = PROJECT_ROOT,
) -> V13FormalReplicationExecutionAdmission:
    try:
        return V13FormalReplicationExecutionAdmission.model_validate_json(
            _read_file(Path(project_root) / ADMISSION_PATH, "execution admission")
        )
    except ValidationError as error:
        raise FormalReplicationAdmissionIntegrityError(
            "invalid replication execution admission"
        ) from error


def verify_checked_replication_execution_admission(
    project_root: Path = PROJECT_ROOT,
) -> V13FormalReplicationExecutionAdmission:
    if (
        ACCEPTED_REPLICATION_EXECUTION_ADMISSION_SHA256 is None
        or ACCEPTED_REPLICATION_EXECUTION_ADMISSION_BYTE_SHA256 is None
    ):
        raise FormalReplicationAdmissionIntegrityError(
            "M18B replication execution admission is not frozen"
        )
    root = Path(project_root).resolve()
    checked = load_checked_replication_execution_admission(root)
    expected = build_replication_execution_admission(
        checked.execution_harness_commit, project_root=root
    )
    if checked != expected:
        raise FormalReplicationAdmissionIntegrityError(
            "replication execution admission semantic mismatch"
        )
    if compute_v13_formal_replication_execution_admission_sha256(checked) != \
            ACCEPTED_REPLICATION_EXECUTION_ADMISSION_SHA256:
        raise FormalReplicationAdmissionIntegrityError(
            "replication execution admission semantic SHA mismatch"
        )
    if _sha256(_read_file(root / ADMISSION_PATH, "execution admission")) != \
            ACCEPTED_REPLICATION_EXECUTION_ADMISSION_BYTE_SHA256:
        raise FormalReplicationAdmissionIntegrityError(
            "replication execution admission byte SHA mismatch"
        )
    return checked


def write_replication_execution_admission(
    value: V13FormalReplicationExecutionAdmission,
    project_root: Path,
) -> None:
    path = Path(project_root) / ADMISSION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(deterministic_json(value))
    except FileExistsError as error:
        raise FormalReplicationAdmissionIntegrityError(
            "replication execution admission already exists"
        ) from error
    except OSError as error:
        raise FormalReplicationAdmissionIntegrityError(
            "unable to write replication execution admission"
        ) from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--execution-harness-commit")
    args = parser.parse_args()
    try:
        if args.write:
            if args.execution_harness_commit is None:
                raise FormalReplicationAdmissionIntegrityError(
                    "write requires an execution harness commit"
                )
            value = build_replication_execution_admission(
                args.execution_harness_commit
            )
            write_replication_execution_admission(value, PROJECT_ROOT)
        else:
            if args.execution_harness_commit is not None:
                raise FormalReplicationAdmissionIntegrityError(
                    "check does not accept an execution harness commit"
                )
            value = verify_checked_replication_execution_admission()
    except FormalReplicationAdmissionIntegrityError as error:
        raise SystemExit(f"Replication admission integrity failure: {error}") from None
    print(
        "replication_execution_admission_sha256="
        f"{compute_v13_formal_replication_execution_admission_sha256(value)}"
    )


if __name__ == "__main__":
    main()
