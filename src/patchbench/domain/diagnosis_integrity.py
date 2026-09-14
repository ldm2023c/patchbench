"""Pure canonical serialization and complete Diagnosis integrity hashes."""

import hashlib
import json

from patchbench.domain.diagnosis import DiagnosisEvidenceBundle, FailureDiagnosis


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_bundle_sha256(bundle: DiagnosisEvidenceBundle) -> str:
    """Hash the complete Bundle excluding only its self-referential hash."""
    return hashlib.sha256(canonical_json_bytes(
        bundle.model_dump(mode="json", exclude={"bundle_sha256"})
    )).hexdigest()


def compute_diagnosis_sha256(diagnosis: FailureDiagnosis) -> str:
    """Hash every field of the typed Diagnosis."""
    return hashlib.sha256(canonical_json_bytes(diagnosis.model_dump(mode="json"))).hexdigest()
