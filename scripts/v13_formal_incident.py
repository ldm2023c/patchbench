"""Build and verify the V1.3 original-study Codex 429 incident freeze."""

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

from patchbench.agents.base import AgentRunStatus
from patchbench.agents.structured_provider_failure import (
    codex_structured_http_429_event_types,
)
from patchbench.domain.formal_incident import (
    V13FormalIncidentFreeze,
    V13FormalIncidentRun,
    compute_v13_formal_incident_freeze_sha256,
)
from scripts.v13_formal_analysis import (
    ACCEPTED_FORMAL_ANALYSIS_SHA256,
    verify_checked_analysis,
)
from scripts.v13_formal_evidence import (
    ACCEPTED_FORMAL_FREEZE_SHA256,
    DEFAULT_SOURCE,
    EXECUTION_HARNESS_COMMIT,
    FormalEvidenceIntegrityError,
    verify_checked_freeze,
    verify_source_against_checked_freeze,
)
from scripts.v13_formal_preregistration import ACCEPTED_PREREGISTRATION_SHA256


INCIDENT_PATH = Path("evidence/v1.3/formal/codex-429-incident-freeze.json")
CODEX_CONFIG_ID = "codex-gpt-5.5-relay"
M16_REMEDIATION_COMMIT = "1d857b0239bb980e448f75d81848f6f8ac8549bd"
ACCEPTED_FORMAL_INCIDENT_SHA256 = (
    "a970d4af2c1a25a9c02a1a68b3e5aeee608c48e5d8937321b9837bfa2c8acefb"
)
ACCEPTED_FORMAL_INCIDENT_BYTE_SHA256 = (
    "4ce6ec38c3f997b22e36f86f7822e8326165e62ff48a86f74c3866b070aeb49d"
)


class FormalIncidentIntegrityError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_file(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise FormalIncidentIntegrityError(f"missing or unsafe {label}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise FormalIncidentIntegrityError(f"unable to read {label}") from error


def _codex_population(freeze):
    return tuple(slot for slot in freeze.slots if slot.config_id == CODEX_CONFIG_ID)


def _agent_stdout_path(source: Path, slot) -> Path:
    if slot.canonical_attempt_index is None or slot.canonical_run is None:
        raise FormalIncidentIntegrityError("command-failed slot lacks canonical Run")
    return (
        source / "slots" / slot.slot_id
        / f"attempt-{slot.canonical_attempt_index:02d}" / "artifacts"
        / slot.canonical_run.run_id / "agent.log"
    )


def _build_from_verified_freeze(freeze, source: Path) -> V13FormalIncidentFreeze:
    codex_slots = _codex_population(freeze)
    command_failed = tuple(
        slot for slot in codex_slots
        if slot.canonical_run is not None
        and slot.canonical_run.agent_status is AgentRunStatus.COMMAND_FAILED
    )
    adjudicated = []
    unadjudicated = []
    for slot in command_failed:
        run = slot.canonical_run
        assert run is not None
        raw = _read_file(_agent_stdout_path(source, slot), "frozen Agent stdout")
        if _sha256_bytes(raw) != run.agent_stdout_sha256:
            raise FormalIncidentIntegrityError("Agent stdout differs from M15 freeze")
        try:
            stdout = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise FormalIncidentIntegrityError("Agent stdout is not UTF-8 JSONL") from error
        event_types = codex_structured_http_429_event_types(stdout)
        if not event_types:
            unadjudicated.append(run.run_id)
            continue
        adjudicated.append(V13FormalIncidentRun(
            ordinal=slot.ordinal,
            slot_id=slot.slot_id,
            repetition_index=slot.repetition_index,
            task_id=slot.task_id,
            config_id=slot.config_id,
            run_id=run.run_id,
            original_agent_status=run.agent_status,
            original_evaluation_passed=run.evaluation_passed,
            agent_stdout_sha256=run.agent_stdout_sha256,
            incident_kind="codex_structured_http_429",
            structured_event_types_seen=event_types,
        ))
    status_count = {
        status: sum(
            slot.canonical_run is not None
            and slot.canonical_run.agent_status is status
            for slot in codex_slots
        )
        for status in AgentRunStatus
    }
    return V13FormalIncidentFreeze(
        incident_id="patchbench-v1.3-original-codex-429",
        original_study_id=freeze.study_id,
        original_formal_preregistration_sha256=ACCEPTED_PREREGISTRATION_SHA256,
        original_formal_evidence_freeze_sha256=ACCEPTED_FORMAL_FREEZE_SHA256,
        original_formal_analysis_sha256=ACCEPTED_FORMAL_ANALYSIS_SHA256,
        original_execution_harness_commit=EXECUTION_HARNESS_COMMIT,
        provider_failure_remediation_commit=M16_REMEDIATION_COMMIT,
        original_codex_planned_slots=len(codex_slots),
        original_codex_completed_slots=status_count[AgentRunStatus.COMPLETED],
        original_codex_command_failed_slots=status_count[AgentRunStatus.COMMAND_FAILED],
        original_codex_timed_out_slots=status_count[AgentRunStatus.TIMED_OUT],
        structured_429_adjudicated_slots=len(adjudicated),
        unadjudicated_command_failed_slots=len(unadjudicated),
        adjudicated_runs=tuple(adjudicated),
        unadjudicated_command_failed_run_ids=tuple(unadjudicated),
        comparative_capability_interpretation_status="infrastructure_confounded",
        original_study_remains_as_run_operational_evidence=True,
    )


def build_formal_incident_freeze(
    source_results: Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> V13FormalIncidentFreeze:
    root = Path(project_root).resolve()
    source = Path(source_results)
    if source.is_symlink():
        raise FormalIncidentIntegrityError("formal source namespace is symlinked")
    try:
        freeze = verify_checked_freeze(root)
        verify_source_against_checked_freeze(source, project_root=root)
        verify_checked_analysis(root)
    except Exception as error:
        raise FormalIncidentIntegrityError("original checked evidence failed") from error
    return _build_from_verified_freeze(freeze, source.resolve())


def deterministic_json(value: V13FormalIncidentFreeze) -> str:
    return json.dumps(value.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def load_checked_incident(
    project_root: Path = PROJECT_ROOT,
) -> V13FormalIncidentFreeze:
    try:
        return V13FormalIncidentFreeze.model_validate_json(
            _read_file(Path(project_root) / INCIDENT_PATH, "checked incident freeze")
        )
    except ValidationError as error:
        raise FormalIncidentIntegrityError("invalid checked incident freeze") from error


def _verify_against_freeze(value: V13FormalIncidentFreeze, freeze) -> None:
    codex_slots = _codex_population(freeze)
    command_failed = tuple(
        slot for slot in codex_slots
        if slot.canonical_run is not None
        and slot.canonical_run.agent_status is AgentRunStatus.COMMAND_FAILED
    )
    by_run = {slot.canonical_run.run_id: slot for slot in command_failed}
    adjudicated_ids = tuple(item.run_id for item in value.adjudicated_runs)
    if set(adjudicated_ids) | set(value.unadjudicated_command_failed_run_ids) != set(by_run):
        raise FormalIncidentIntegrityError("incident does not partition frozen failures")
    if set(adjudicated_ids) & set(value.unadjudicated_command_failed_run_ids):
        raise FormalIncidentIntegrityError("incident populations overlap")
    for item in value.adjudicated_runs:
        slot = by_run.get(item.run_id)
        if slot is None or slot.canonical_run is None or (
            item.ordinal,
            item.slot_id,
            item.repetition_index,
            item.task_id,
            item.config_id,
            item.original_agent_status,
            item.original_evaluation_passed,
            item.agent_stdout_sha256,
        ) != (
            slot.ordinal,
            slot.slot_id,
            slot.repetition_index,
            slot.task_id,
            slot.config_id,
            slot.canonical_run.agent_status,
            slot.canonical_run.evaluation_passed,
            slot.canonical_run.agent_stdout_sha256,
        ):
            raise FormalIncidentIntegrityError("incident Run differs from M15 freeze")
    counts = {status: sum(
        slot.canonical_run is not None and slot.canonical_run.agent_status is status
        for slot in codex_slots
    ) for status in AgentRunStatus}
    if (
        value.original_codex_planned_slots != len(codex_slots)
        or value.original_codex_completed_slots != counts[AgentRunStatus.COMPLETED]
        or value.original_codex_command_failed_slots
        != counts[AgentRunStatus.COMMAND_FAILED]
        or value.original_codex_timed_out_slots != counts[AgentRunStatus.TIMED_OUT]
    ):
        raise FormalIncidentIntegrityError("incident outcome counts differ from M15 freeze")


def verify_checked_incident(
    project_root: Path = PROJECT_ROOT,
) -> V13FormalIncidentFreeze:
    root = Path(project_root).resolve()
    freeze = verify_checked_freeze(root)
    verify_checked_analysis(root)
    value = load_checked_incident(root)
    raw = _read_file(root / INCIDENT_PATH, "checked incident freeze")
    if compute_v13_formal_incident_freeze_sha256(value) != \
            ACCEPTED_FORMAL_INCIDENT_SHA256:
        raise FormalIncidentIntegrityError("incident semantic SHA mismatch")
    if _sha256_bytes(raw) != ACCEPTED_FORMAL_INCIDENT_BYTE_SHA256:
        raise FormalIncidentIntegrityError("incident artifact byte SHA mismatch")
    if (
        value.original_formal_preregistration_sha256
        != ACCEPTED_PREREGISTRATION_SHA256
        or value.original_formal_evidence_freeze_sha256
        != ACCEPTED_FORMAL_FREEZE_SHA256
        or value.original_formal_analysis_sha256 != ACCEPTED_FORMAL_ANALYSIS_SHA256
        or value.original_execution_harness_commit != EXECUTION_HARNESS_COMMIT
        or value.provider_failure_remediation_commit != M16_REMEDIATION_COMMIT
        or value.original_study_id != freeze.study_id
    ):
        raise FormalIncidentIntegrityError("incident frozen-link mismatch")
    _verify_against_freeze(value, freeze)
    return value


def verify_source_against_checked_incident(
    source_results: Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> V13FormalIncidentFreeze:
    checked = verify_checked_incident(project_root)
    rebuilt = build_formal_incident_freeze(
        source_results, project_root=project_root
    )
    if rebuilt != checked:
        raise FormalIncidentIntegrityError("formal source differs from incident freeze")
    return checked


def write_incident(value: V13FormalIncidentFreeze, project_root: Path) -> None:
    path = Path(project_root) / INCIDENT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(deterministic_json(value))
    except FileExistsError as error:
        raise FormalIncidentIntegrityError("checked incident freeze already exists") from error
    except OSError as error:
        raise FormalIncidentIntegrityError("unable to write incident freeze") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--check-source", action="store_true")
    parser.add_argument("--source-results", type=Path, default=PROJECT_ROOT / DEFAULT_SOURCE)
    args = parser.parse_args()
    try:
        if args.write:
            value = build_formal_incident_freeze(args.source_results)
            write_incident(value, PROJECT_ROOT)
        elif args.check_source:
            value = verify_source_against_checked_incident(args.source_results)
        else:
            value = verify_checked_incident()
    except (FormalIncidentIntegrityError, FormalEvidenceIntegrityError) as error:
        raise SystemExit(f"Formal incident integrity failure: {error}") from None
    print(
        "formal_incident_sha256="
        f"{compute_v13_formal_incident_freeze_sha256(value)}"
    )


if __name__ == "__main__":
    main()
