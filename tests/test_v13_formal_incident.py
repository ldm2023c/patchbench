"""Provider-free tests for the V1.3 original-study incident freeze."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from patchbench.agents.base import AgentRunStatus
from patchbench.agents.structured_provider_failure import (
    codex_structured_http_429_event_types,
)
from patchbench.domain.formal_incident import (
    V13FormalIncidentFreeze,
    compute_v13_formal_incident_freeze_sha256,
)
from scripts import v13_formal_incident as incident
from scripts.v13_formal_evidence import verify_checked_freeze


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        (
            json.dumps({"type": "error", "message": "429 Too Many Requests"}),
            ("error",),
        ),
        (
            json.dumps({
                "type": "turn.failed",
                "error": {"message": "last status: 429 Too Many Requests"},
            }),
            ("turn.failed",),
        ),
        (
            "\n".join((
                json.dumps({"type": "turn.failed", "error": {
                    "message": "429 Too Many Requests"
                }}),
                json.dumps({"type": "error", "message": "429 Too Many Requests"}),
            )),
            ("error", "turn.failed"),
        ),
        (
            json.dumps({"type": "item.completed", "item": {
                "type": "agent_message", "text": "429 Too Many Requests"
            }}),
            (),
        ),
        (
            json.dumps({"type": "item.completed", "item": {
                "type": "command_execution", "aggregated_output": "429 Too Many Requests"
            }}),
            (),
        ),
        ("429 Too Many Requests", ()),
        ('{"type":"error", malformed', ()),
        (json.dumps({"type": "error", "message": "repository failed"}), ()),
        ("Refusing to create helper binaries under temporary dir \"/tmp\"", ()),
    ],
)
def test_structured_classifier_has_exact_m16_boundary(stdout, expected):
    assert codex_structured_http_429_event_types(stdout) == expected


def _synthetic_incident_source(tmp_path: Path, monkeypatch, *, one_negative=False):
    checked = verify_checked_freeze(PROJECT_ROOT)
    source = tmp_path / "formal"
    changed_slots = []
    failure_index = 0
    for slot in checked.slots:
        run = slot.canonical_run
        if (
            slot.config_id == incident.CODEX_CONFIG_ID
            and run is not None
            and run.agent_status is AgentRunStatus.COMMAND_FAILED
        ):
            failure_index += 1
            stdout = (
                json.dumps({"type": "error", "message": "ordinary tool failure"})
                if one_negative and failure_index == 1
                else json.dumps({
                    "type": "turn.failed",
                    "error": {"message": "429 Too Many Requests request id: secret"},
                })
            ) + "\n"
            raw = stdout.encode()
            path = (
                source / "slots" / slot.slot_id
                / f"attempt-{slot.canonical_attempt_index:02d}" / "artifacts"
                / run.run_id / "agent.log"
            )
            path.parent.mkdir(parents=True)
            path.write_bytes(raw)
            run = run.model_copy(update={
                "agent_stdout_sha256": hashlib.sha256(raw).hexdigest()
            })
            slot = slot.model_copy(update={"canonical_run": run})
        changed_slots.append(slot)
    freeze = checked.model_copy(update={"slots": tuple(changed_slots)})
    monkeypatch.setattr(incident, "verify_checked_freeze", lambda root: freeze)
    monkeypatch.setattr(
        incident, "verify_source_against_checked_freeze", lambda *a, **k: freeze
    )
    monkeypatch.setattr(incident, "verify_checked_analysis", lambda root: object())
    return source, freeze


def test_builder_derives_population_and_retains_unadjudicated_failure(
    tmp_path, monkeypatch
):
    source, freeze = _synthetic_incident_source(
        tmp_path, monkeypatch, one_negative=True
    )
    value = incident.build_formal_incident_freeze(
        source, project_root=PROJECT_ROOT
    )
    command_failed = [
        slot for slot in freeze.slots
        if slot.config_id == incident.CODEX_CONFIG_ID
        and slot.canonical_run is not None
        and slot.canonical_run.agent_status is AgentRunStatus.COMMAND_FAILED
    ]
    assert value.original_codex_planned_slots == 36
    assert value.original_codex_command_failed_slots == len(command_failed)
    assert value.structured_429_adjudicated_slots == len(command_failed) - 1
    assert value.unadjudicated_command_failed_slots == 1
    assert len(value.unadjudicated_command_failed_run_ids) == 1
    assert all(item.original_agent_status == "command_failed"
               for item in value.adjudicated_runs)
    serialized = incident.deterministic_json(value)
    assert "/home/" not in serialized
    assert "request id" not in serialized
    assert "secret" not in serialized
    assert "Too Many Requests" not in serialized
    assert "API_KEY" not in serialized


def test_builder_fails_when_live_stdout_differs_from_frozen_hash(
    tmp_path, monkeypatch
):
    source, freeze = _synthetic_incident_source(tmp_path, monkeypatch)
    slot = next(
        item for item in freeze.slots
        if item.config_id == incident.CODEX_CONFIG_ID
        and item.canonical_run is not None
        and item.canonical_run.agent_status is AgentRunStatus.COMMAND_FAILED
    )
    _path = incident._agent_stdout_path(source, slot)
    _path.write_text("drift", encoding="utf-8")
    with pytest.raises(incident.FormalIncidentIntegrityError, match="differs"):
        incident.build_formal_incident_freeze(source, project_root=PROJECT_ROOT)


def test_model_is_strict_and_semantic_hash_is_deterministic(tmp_path, monkeypatch):
    source, _ = _synthetic_incident_source(tmp_path, monkeypatch)
    value = incident.build_formal_incident_freeze(source, project_root=PROJECT_ROOT)
    rebuilt = V13FormalIncidentFreeze.model_validate_json(
        incident.deterministic_json(value)
    )
    assert compute_v13_formal_incident_freeze_sha256(value) == \
        compute_v13_formal_incident_freeze_sha256(rebuilt)
    with pytest.raises(ValidationError):
        V13FormalIncidentFreeze.model_validate(
            value.model_dump(mode="json") | {"unexpected": True}
        )


def test_checked_verification_does_not_read_live_results(monkeypatch):
    if not (PROJECT_ROOT / incident.INCIDENT_PATH).exists():
        pytest.skip("production incident artifact is generated after synthetic tests")
    original = Path.read_bytes

    def guarded(path):
        assert "results/v1.3-formal" not in path.as_posix()
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    incident.verify_checked_incident(PROJECT_ROOT)


def test_check_source_detects_stdout_drift(tmp_path, monkeypatch):
    source, freeze = _synthetic_incident_source(tmp_path, monkeypatch)
    checked = incident._build_from_verified_freeze(freeze, source)
    monkeypatch.setattr(incident, "verify_checked_incident", lambda root: checked)
    monkeypatch.setattr(
        incident,
        "build_formal_incident_freeze",
        lambda *a, **k: checked.model_copy(update={
            "comparative_capability_interpretation_status": "unexpected"
        }),
    )
    with pytest.raises(incident.FormalIncidentIntegrityError, match="differs"):
        incident.verify_source_against_checked_incident(
            source, project_root=PROJECT_ROOT
        )
