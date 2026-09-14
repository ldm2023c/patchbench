"""Pure human-gold validation and deterministic per-case Diagnosis scoring."""

import hashlib
from enum import Enum

from patchbench.domain.diagnosis import (
    DiagnosisEvidenceBundle,
    DiagnosisRoute,
    EvidenceItem,
    EvidenceOwner,
    EvidenceRef,
    FailureDiagnosis,
)
from patchbench.domain.diagnosis_audit import (
    DiagnosisAuditIssueCode,
    DiagnosisReferenceRole,
    audit_failure_diagnosis,
)
from patchbench.domain.diagnosis_integrity import canonical_json_bytes, compute_bundle_sha256
from patchbench.domain.diagnosis_validation import (
    DiagnosisGoldCase,
    DiagnosisOverclaimReview,
    DiagnosisRouteScore,
    GoldEvidenceLocator,
    SemanticDiagnosisScore,
)
from patchbench.domain.models import RunRecord, Sha256Hex
from patchbench.domain.diagnosis import route_run_diagnosis


class DiagnosisValidationReason(str, Enum):
    GOLD_NOT_SEMANTIC = "gold_not_semantic"
    BUNDLE_INTEGRITY_FAILED = "bundle_integrity_failed"
    DIAGNOSIS_LINKAGE_FAILED = "diagnosis_linkage_failed"
    SUBJECT_EVIDENCE_MISMATCH = "subject_evidence_mismatch"
    GOLD_EVIDENCE_NOT_FOUND = "gold_evidence_not_found"
    GOLD_EVIDENCE_AMBIGUOUS = "gold_evidence_ambiguous"
    GOLD_EVIDENCE_RANGE_INVALID = "gold_evidence_range_invalid"
    OVERCLAIM_REVIEW_INVALID = "overclaim_review_invalid"


class DiagnosisValidationError(ValueError):
    def __init__(self, reason: DiagnosisValidationReason, detail: str):
        self.reason = reason
        super().__init__(f"{reason.value}: {detail}")


def compute_subject_evidence_sha256(bundle: DiagnosisEvidenceBundle) -> Sha256Hex:
    """Hash only frozen subject facts, independently of mode, Run ID, and peer."""
    identity = {
        "schema_version": bundle.schema_version,
        "task_id": bundle.task_id,
        "benchmark_definition_sha256": bundle.benchmark_definition_sha256,
        "task_fingerprint_sha256": bundle.task_fingerprint_sha256,
        "base_commit": bundle.base_commit,
        "source_snapshot_policy": bundle.source_snapshot_policy,
        "subject_provenance": bundle.provenance.subject.model_dump(mode="json"),
    }
    return hashlib.sha256(canonical_json_bytes(identity)).hexdigest()


def compute_diagnosis_gold_sha256(gold: DiagnosisGoldCase) -> Sha256Hex:
    """Hash the complete typed Human Gold case without omissions or mutation."""
    return hashlib.sha256(canonical_json_bytes(gold.model_dump(mode="json"))).hexdigest()


def score_diagnosis_route(run: RunRecord, gold: DiagnosisGoldCase) -> DiagnosisRouteScore:
    decision = route_run_diagnosis(run)
    return DiagnosisRouteScore(
        case_id=gold.case_id,
        gold_sha256=compute_diagnosis_gold_sha256(gold),
        run_id=run.run_id,
        expected_route=gold.expected_route,
        actual_route=decision.route,
        actual_reason=decision.reason,
        correct=decision.route is gold.expected_route,
    )


def _locator_matches(locator: GoldEvidenceLocator, item: EvidenceItem) -> bool:
    return (
        item.owner is not EvidenceOwner.PEER
        and item.owner is locator.owner
        and item.kind is locator.kind
        and item.artifact_sha256 == locator.artifact_sha256
        and item.path == locator.path
        and item.source_state is locator.source_state
    )


def _resolve_locator(bundle: DiagnosisEvidenceBundle, locator: GoldEvidenceLocator) -> EvidenceItem:
    matches = [item for item in bundle.evidence_items if _locator_matches(locator, item)]
    if not matches:
        raise DiagnosisValidationError(
            DiagnosisValidationReason.GOLD_EVIDENCE_NOT_FOUND,
            "gold locator does not match subject/benchmark evidence",
        )
    if len(matches) != 1:
        raise DiagnosisValidationError(
            DiagnosisValidationReason.GOLD_EVIDENCE_AMBIGUOUS,
            "gold locator matches more than one evidence item",
        )
    item = matches[0]
    if locator.start_line is None:
        valid = item.content == "" and item.start_line is None and item.end_line is None
    else:
        valid = (
            item.content != ""
            and item.start_line is not None
            and item.end_line is not None
            and item.start_line <= locator.start_line <= locator.end_line <= item.end_line
        )
    if not valid:
        raise DiagnosisValidationError(
            DiagnosisValidationReason.GOLD_EVIDENCE_RANGE_INVALID,
            "gold locator range is invalid for the matched evidence item",
        )
    return item


def _resolve_semantic_gold_evidence(
    bundle: DiagnosisEvidenceBundle, gold: DiagnosisGoldCase,
) -> list[list[tuple[GoldEvidenceLocator, EvidenceItem]]]:
    if gold.expected_route is not DiagnosisRoute.SEMANTIC_DIAGNOSIS or gold.semantic_gold is None:
        raise DiagnosisValidationError(
            DiagnosisValidationReason.GOLD_NOT_SEMANTIC,
            "semantic evidence validation requires semantic Diagnosis gold",
        )
    if compute_subject_evidence_sha256(bundle) != gold.subject_evidence_sha256:
        raise DiagnosisValidationError(
            DiagnosisValidationReason.SUBJECT_EVIDENCE_MISMATCH,
            "gold subject identity differs from the supplied Bundle",
        )
    return [[(locator, _resolve_locator(bundle, locator))
             for locator in requirement.acceptable_locators]
            for requirement in gold.semantic_gold.required_evidence]


def validate_semantic_gold_evidence(
    bundle: DiagnosisEvidenceBundle, gold: DiagnosisGoldCase,
) -> None:
    """Validate subject identity and resolve every exact Human Gold locator once."""
    _resolve_semantic_gold_evidence(bundle, gold)


_CITATION_ISSUE_CODES = {
    DiagnosisAuditIssueCode.EVIDENCE_NOT_FOUND,
    DiagnosisAuditIssueCode.NULL_RANGE_FOR_NONEMPTY_EVIDENCE,
    DiagnosisAuditIssueCode.RANGE_FOR_EMPTY_EVIDENCE,
    DiagnosisAuditIssueCode.EVIDENCE_RANGE_OUT_OF_BOUNDS,
}


def _reference_covers(ref: EvidenceRef, item: EvidenceItem,
                      locator: GoldEvidenceLocator) -> bool:
    if ref.evidence_id != item.evidence_id:
        return False
    if locator.start_line is None:
        return ref.start_line is None and ref.end_line is None
    return (
        ref.start_line is not None
        and ref.end_line is not None
        and ref.start_line <= locator.start_line
        and ref.end_line >= locator.end_line
    )


def score_semantic_diagnosis(
    bundle: DiagnosisEvidenceBundle,
    diagnosis: FailureDiagnosis,
    gold: DiagnosisGoldCase,
    *,
    overclaim_review: DiagnosisOverclaimReview | None = None,
) -> SemanticDiagnosisScore:
    if gold.expected_route is not DiagnosisRoute.SEMANTIC_DIAGNOSIS or gold.semantic_gold is None:
        raise DiagnosisValidationError(
            DiagnosisValidationReason.GOLD_NOT_SEMANTIC,
            "semantic scoring requires semantic Diagnosis gold",
        )
    if compute_bundle_sha256(bundle) != bundle.bundle_sha256:
        raise DiagnosisValidationError(
            DiagnosisValidationReason.BUNDLE_INTEGRITY_FAILED,
            "Bundle declared hash differs from canonical content",
        )
    if (diagnosis.bundle_sha256 != bundle.bundle_sha256
            or diagnosis.mode is not bundle.mode
            or diagnosis.subject_run_id != bundle.subject_run_id):
        raise DiagnosisValidationError(
            DiagnosisValidationReason.DIAGNOSIS_LINKAGE_FAILED,
            "Diagnosis does not link to this Bundle, subject, and mode",
        )

    subject_sha = compute_subject_evidence_sha256(bundle)
    resolved_requirements = _resolve_semantic_gold_evidence(bundle, gold)

    claims = {claim.claim_id for claim in gold.semantic_gold.forbidden_claims}
    if overclaim_review is not None:
        if not claims:
            raise DiagnosisValidationError(
                DiagnosisValidationReason.OVERCLAIM_REVIEW_INVALID,
                "overclaim review is not applicable without forbidden claims",
            )
        if (overclaim_review.case_id != gold.case_id
                or overclaim_review.diagnosis_id != diagnosis.diagnosis_id
                or not set(overclaim_review.violated_claim_ids).issubset(claims)):
            raise DiagnosisValidationError(
                DiagnosisValidationReason.OVERCLAIM_REVIEW_INVALID,
                "overclaim review linkage or claim IDs are invalid",
            )

    audit = audit_failure_diagnosis(bundle, diagnosis)
    invalid_citation_issues = [
        issue for issue in audit.issues if issue.code in _CITATION_ISSUE_CODES
    ]
    invalid_supporting_refs = {
        (issue.hypothesis_rank, issue.reference_index)
        for issue in invalid_citation_issues
        if issue.reference_role is DiagnosisReferenceRole.EVIDENCE
    }

    semantic_gold = gold.semantic_gold
    predicted_families = [item.failure_family for item in diagnosis.hypotheses]
    if semantic_gold.should_abstain:
        preferred_top1 = top1_acceptable = topk_acceptable = None
        evidence_satisfied = evidence_total = None
    else:
        preferred_top1 = bool(
            predicted_families and predicted_families[0] is semantic_gold.preferred_family
        )
        top1_acceptable = bool(
            predicted_families and predicted_families[0] in semantic_gold.acceptable_families
        )
        topk_acceptable = any(
            family in semantic_gold.acceptable_families for family in predicted_families
        )
        evidence_total = len(resolved_requirements)
        evidence_satisfied = 0
        for alternatives in resolved_requirements:
            satisfied = False
            for hypothesis in diagnosis.hypotheses:
                for index, ref in enumerate(hypothesis.evidence_refs):
                    if (hypothesis.rank, index) in invalid_supporting_refs:
                        continue
                    if any(_reference_covers(ref, item, locator)
                           for locator, item in alternatives):
                        satisfied = True
                        break
                if satisfied:
                    break
            evidence_satisfied += int(satisfied)

    applicable = bool(claims)
    reviewed = overclaim_review is not None
    violated_ids = [] if overclaim_review is None else overclaim_review.violated_claim_ids
    return SemanticDiagnosisScore(
        case_id=gold.case_id,
        gold_sha256=compute_diagnosis_gold_sha256(gold),
        subject_evidence_sha256=subject_sha,
        diagnosis_id=diagnosis.diagnosis_id,
        mode=bundle.mode,
        predicted_abstain=diagnosis.abstain,
        abstention_correct=diagnosis.abstain == semantic_gold.should_abstain,
        preferred_top1_match=preferred_top1,
        top1_acceptable_match=top1_acceptable,
        topk_acceptable_match=topk_acceptable,
        required_evidence_satisfied=evidence_satisfied,
        required_evidence_total=evidence_total,
        audit_passed=audit.passed,
        audit_issue_count=len(audit.issues),
        invalid_citation_issue_count=len(invalid_citation_issues),
        overclaim_applicable=applicable,
        overclaim_reviewed=reviewed,
        overclaim_violation=(bool(violated_ids) if reviewed else None),
        violated_claim_ids=violated_ids,
    )
