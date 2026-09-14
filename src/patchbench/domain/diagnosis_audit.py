"""Deterministic structural auditing; PASS does not establish semantic truth."""

from enum import Enum
from typing import Annotated, Self

from pydantic import Field, model_validator

from patchbench.domain.diagnosis import DiagnosisEvidenceBundle, EvidenceKind, EvidenceOwner, FailureDiagnosis
from patchbench.domain.diagnosis_integrity import compute_bundle_sha256, compute_diagnosis_sha256
from patchbench.domain.models import DomainModel, NonEmptyString, Sha256Hex


class DiagnosisAuditIssueCode(str, Enum):
    BUNDLE_HASH_MISMATCH = "bundle_hash_mismatch"
    DIAGNOSIS_BUNDLE_HASH_MISMATCH = "diagnosis_bundle_hash_mismatch"
    MODE_MISMATCH = "mode_mismatch"
    SUBJECT_RUN_MISMATCH = "subject_run_mismatch"
    EVIDENCE_OWNERSHIP_MISMATCH = "evidence_ownership_mismatch"
    EVIDENCE_NOT_FOUND = "evidence_not_found"
    NULL_RANGE_FOR_NONEMPTY_EVIDENCE = "null_range_for_nonempty_evidence"
    RANGE_FOR_EMPTY_EVIDENCE = "range_for_empty_evidence"
    EVIDENCE_RANGE_OUT_OF_BOUNDS = "evidence_range_out_of_bounds"


class DiagnosisReferenceRole(str, Enum):
    EVIDENCE = "evidence"
    COUNTEREVIDENCE = "counterevidence"


class DiagnosisAuditIssue(DomainModel):
    code: DiagnosisAuditIssueCode
    hypothesis_rank: int | None = Field(default=None, strict=True, ge=1, le=3)
    reference_role: DiagnosisReferenceRole | None = None
    reference_index: int | None = Field(default=None, strict=True, ge=0)
    evidence_id: NonEmptyString | None = None
    detail: NonEmptyString


class DiagnosisAuditResult(DomainModel):
    """PASS means structural linkage and citation boundaries are valid only."""

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    diagnosis_id: NonEmptyString
    bundle_id: NonEmptyString
    bundle_sha256: Sha256Hex
    computed_bundle_sha256: Sha256Hex
    diagnosis_sha256: Sha256Hex
    passed: Annotated[bool, Field(strict=True)]
    issues: list[DiagnosisAuditIssue]

    @model_validator(mode="after")
    def validate_passed(self) -> Self:
        if self.passed != (len(self.issues) == 0):
            raise ValueError("passed must agree with the absence of issues")
        return self


def audit_failure_diagnosis(bundle: DiagnosisEvidenceBundle,
                            diagnosis: FailureDiagnosis) -> DiagnosisAuditResult:
    """Check typed evidence boundaries without judging claims or mutating inputs."""
    computed = compute_bundle_sha256(bundle)
    issues: list[DiagnosisAuditIssue] = []
    for mismatch, code, detail in (
        (computed != bundle.bundle_sha256, DiagnosisAuditIssueCode.BUNDLE_HASH_MISMATCH,
         "Bundle declared hash differs from its complete canonical content."),
        (diagnosis.bundle_sha256 != bundle.bundle_sha256,
         DiagnosisAuditIssueCode.DIAGNOSIS_BUNDLE_HASH_MISMATCH,
         "Diagnosis hash linkage differs from the Bundle declared hash."),
        (diagnosis.mode != bundle.mode, DiagnosisAuditIssueCode.MODE_MISMATCH,
         "Diagnosis mode differs from Bundle mode."),
        (diagnosis.subject_run_id != bundle.subject_run_id, DiagnosisAuditIssueCode.SUBJECT_RUN_MISMATCH,
         "Diagnosis subject Run differs from Bundle subject Run."),
    ):
        if mismatch:
            issues.append(DiagnosisAuditIssue(code=code, detail=detail))

    peer_kinds = (EvidenceKind.PEER_SOURCE, EvidenceKind.PEER_PATCH, EvidenceKind.PEER_EVALUATION)
    for item in bundle.evidence_items:
        if (item.kind in peer_kinds) != (item.owner is EvidenceOwner.PEER):
            issues.append(DiagnosisAuditIssue(
                code=DiagnosisAuditIssueCode.EVIDENCE_OWNERSHIP_MISMATCH,
                evidence_id=item.evidence_id, detail="Peer-specific kind and peer ownership must agree."))

    items = {item.evidence_id: item for item in bundle.evidence_items}
    for hypothesis in diagnosis.hypotheses:
        for role, refs in ((DiagnosisReferenceRole.EVIDENCE, hypothesis.evidence_refs),
                           (DiagnosisReferenceRole.COUNTEREVIDENCE, hypothesis.counterevidence_refs)):
            for index, ref in enumerate(refs):
                item = items.get(ref.evidence_id)
                if item is None:
                    code = DiagnosisAuditIssueCode.EVIDENCE_NOT_FOUND
                    detail = "Referenced evidence is absent from this Bundle."
                elif item.content == "":
                    if ref.start_line is None:
                        continue
                    code = DiagnosisAuditIssueCode.RANGE_FOR_EMPTY_EVIDENCE
                    detail = "Zero-line evidence requires a None/None reference."
                elif ref.start_line is None:
                    code = DiagnosisAuditIssueCode.NULL_RANGE_FOR_NONEMPTY_EVIDENCE
                    detail = "Nonempty evidence requires integer reference coordinates."
                else:
                    # D1 guarantees paired coordinates and locally ordered ranges.
                    assert item.start_line is not None and item.end_line is not None and ref.end_line is not None
                    if item.start_line <= ref.start_line <= ref.end_line <= item.end_line:
                        continue
                    code = DiagnosisAuditIssueCode.EVIDENCE_RANGE_OUT_OF_BOUNDS
                    detail = "Reference range exceeds the exposed artifact-relative evidence range."
                issues.append(DiagnosisAuditIssue(code=code, hypothesis_rank=hypothesis.rank,
                    reference_role=role, reference_index=index, evidence_id=ref.evidence_id, detail=detail))

    return DiagnosisAuditResult(diagnosis_id=diagnosis.diagnosis_id, bundle_id=bundle.bundle_id,
        bundle_sha256=bundle.bundle_sha256, computed_bundle_sha256=computed,
        diagnosis_sha256=compute_diagnosis_sha256(diagnosis), passed=not issues, issues=issues)
