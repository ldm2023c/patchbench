"""Pure Diagnosis contracts; inference never changes official evaluation truth.

Run routing is stage one only. Readiness, compilation, hashing, cross-object
checks and citation auditing belong to later application/compiler/auditor work.
"""

from enum import Enum
from typing import Annotated, Self, assert_never

from pydantic import Field, StringConstraints, model_validator

from patchbench.agents.base import AgentRunStatus
from patchbench.domain.models import DomainModel, NonEmptyString, RunRecord, Sha256Hex


class DiagnosisMode(str, Enum):
    BLIND = "blind"
    CONTRASTIVE = "contrastive"


class DiagnosisRoute(str, Enum):
    SEMANTIC_DIAGNOSIS = "semantic_diagnosis"
    OPERATIONAL_ONLY = "operational_only"
    UNAVAILABLE = "unavailable"


class DiagnosisRoutingReason(str, Enum):
    SEMANTIC_FAILURE = "semantic_failure"
    AGENT_COMMAND_FAILED = "agent_command_failed"
    AGENT_TIMED_OUT = "agent_timed_out"
    OFFICIAL_PASS = "official_pass"


class DiagnosisRoutingDecision(DomainModel):
    run_id: NonEmptyString
    route: DiagnosisRoute
    reason: DiagnosisRoutingReason

    @model_validator(mode="after")
    def validate_route_reason(self) -> Self:
        expected = {
            DiagnosisRoutingReason.SEMANTIC_FAILURE: DiagnosisRoute.SEMANTIC_DIAGNOSIS,
            DiagnosisRoutingReason.AGENT_COMMAND_FAILED: DiagnosisRoute.OPERATIONAL_ONLY,
            DiagnosisRoutingReason.AGENT_TIMED_OUT: DiagnosisRoute.OPERATIONAL_ONLY,
            DiagnosisRoutingReason.OFFICIAL_PASS: DiagnosisRoute.UNAVAILABLE,
        }
        if self.route != expected[self.reason]:
            raise ValueError("route must agree with routing reason")
        return self


def route_run_diagnosis(run: RunRecord) -> DiagnosisRoutingDecision:
    """Route from Run outcome/status only, without inspecting patch evidence.

    This is not a readiness decision: future compiler/application policy may
    still prevent diagnosis of a Run routed to semantic diagnosis.
    """
    if run.evaluation_passed:
        route, reason = DiagnosisRoute.UNAVAILABLE, DiagnosisRoutingReason.OFFICIAL_PASS
    elif run.agent.status is AgentRunStatus.COMMAND_FAILED:
        route, reason = DiagnosisRoute.OPERATIONAL_ONLY, DiagnosisRoutingReason.AGENT_COMMAND_FAILED
    elif run.agent.status is AgentRunStatus.TIMED_OUT:
        route, reason = DiagnosisRoute.OPERATIONAL_ONLY, DiagnosisRoutingReason.AGENT_TIMED_OUT
    elif run.agent.status is AgentRunStatus.COMPLETED:
        route, reason = DiagnosisRoute.SEMANTIC_DIAGNOSIS, DiagnosisRoutingReason.SEMANTIC_FAILURE
    else:
        assert_never(run.agent.status)
    return DiagnosisRoutingDecision(run_id=run.run_id, route=route, reason=reason)


class EvidenceOwner(str, Enum):
    SUBJECT = "subject"
    PEER = "peer"
    BENCHMARK = "benchmark"


class EvidenceSourceState(str, Enum):
    BASE = "base"
    CANDIDATE = "candidate"
    FROZEN = "frozen"


class EvidenceKind(str, Enum):
    TASK_CONTRACT = "task_contract"
    PRODUCTION_SOURCE = "production_source"
    CANONICAL_PATCH = "canonical_patch"
    FROZEN_TEST = "frozen_test"
    EVALUATION_OUTPUT = "evaluation_output"
    EVALUATION_CASE = "evaluation_case"
    OPERATIONAL_FACT = "operational_fact"
    PEER_SOURCE = "peer_source"
    PEER_PATCH = "peer_patch"
    PEER_EVALUATION = "peer_evaluation"


class EvidenceItem(DomainModel):
    """Exact exposed text, with inclusive artifact-relative line coordinates.

    Only LF separates lines. A final LF terminates the preceding line rather
    than adding a line; empty content represents zero lines and cannot satisfy
    a nonempty range. CR and Unicode separators remain content. The supplied
    hash identifies the artifact, not necessarily this exposed region.
    """

    evidence_id: NonEmptyString
    kind: EvidenceKind
    owner: EvidenceOwner
    artifact_sha256: Sha256Hex
    path: NonEmptyString | None = None
    source_state: EvidenceSourceState | None = None
    start_line: int = Field(ge=1, strict=True)
    end_line: int = Field(ge=1, strict=True)
    content: Annotated[str, StringConstraints(strict=True, strip_whitespace=False)]

    @model_validator(mode="after")
    def validate_lines(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be at least start_line")
        count = self.content.count("\n") + int(bool(self.content) and not self.content.endswith("\n"))
        if count != self.end_line - self.start_line + 1:
            raise ValueError("content line count must match the inclusive range")
        return self


class EvidenceRef(DomainModel):
    """Local coordinates only; bundle membership and containment await D3."""

    evidence_id: NonEmptyString
    start_line: int = Field(ge=1, strict=True)
    end_line: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be at least start_line")
        return self


class SubjectProvenance(DomainModel):
    canonical_patch_sha256: Sha256Hex
    evaluation_log_sha256: Sha256Hex
    task_contract_sha256: Sha256Hex
    base_source_snapshot_sha256: Sha256Hex
    candidate_source_snapshot_sha256: Sha256Hex
    frozen_tests_snapshot_sha256: Sha256Hex
    benchmark_definition_sha256: Sha256Hex


class PeerProvenance(DomainModel):
    peer_run_id: NonEmptyString
    peer_patch_sha256: Sha256Hex
    peer_candidate_snapshot_sha256: Sha256Hex
    peer_evaluation_log_sha256: Sha256Hex


class BundleProvenance(DomainModel):
    subject: SubjectProvenance
    peer: PeerProvenance | None = None


class DiagnosisEvidenceBundle(DomainModel):
    """Locally valid evidence container, not a verified peer or computed hash."""

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    bundle_id: NonEmptyString
    bundle_sha256: Sha256Hex
    mode: DiagnosisMode
    task_id: NonEmptyString
    subject_run_id: NonEmptyString
    benchmark_definition_sha256: Sha256Hex
    task_fingerprint_sha256: Sha256Hex
    base_commit: NonEmptyString
    official_evaluation_passed: Annotated[bool, Field(strict=True)]
    agent_status: AgentRunStatus
    peer_run_id: NonEmptyString | None = None
    source_snapshot_policy: NonEmptyString
    evidence_items: list[EvidenceItem] = Field(min_length=1)
    provenance: BundleProvenance

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        if self.official_evaluation_passed:
            raise ValueError("diagnosis bundle requires official evaluation FAIL")
        ids = [item.evidence_id for item in self.evidence_items]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence IDs must be unique")
        peer_kinds = {EvidenceKind.PEER_SOURCE, EvidenceKind.PEER_PATCH, EvidenceKind.PEER_EVALUATION}
        has_peer = any(item.owner is EvidenceOwner.PEER for item in self.evidence_items)
        if self.mode is DiagnosisMode.BLIND:
            if (self.peer_run_id is not None or self.provenance.peer is not None
                    or has_peer or any(item.kind in peer_kinds for item in self.evidence_items)):
                raise ValueError("blind bundle must not contain peer identity or evidence")
        else:
            if self.peer_run_id is None or self.peer_run_id == self.subject_run_id:
                raise ValueError("contrastive bundle requires a distinct peer Run")
            if self.provenance.peer is None or not has_peer:
                raise ValueError("contrastive bundle requires peer provenance and peer-owned evidence")
            if self.provenance.peer.peer_run_id != self.peer_run_id:
                raise ValueError("peer provenance must identify the bundle peer")
        if self.provenance.subject.benchmark_definition_sha256 != self.benchmark_definition_sha256:
            raise ValueError("benchmark definition hash must agree with subject provenance")
        return self


class FailureFamily(str, Enum):
    INCORRECT_LOCAL_LOGIC = "incorrect_local_logic"
    INCOMPLETE_CROSS_FILE_REPAIR = "incomplete_cross_file_repair"
    PARTIAL_CONTRACT_HANDLING = "partial_contract_handling"
    STATE_CONSISTENCY_VIOLATION = "state_consistency_violation"
    REGRESSION_INTRODUCED = "regression_introduced"
    INEFFECTIVE_OR_TEST_FOCUSED_REPAIR = "ineffective_or_test_focused_repair"
    OTHER_SEMANTIC_FAILURE = "other_semantic_failure"


class DiagnosisCertainty(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DiagnosisHypothesis(DomainModel):
    rank: int = Field(strict=True, ge=1, le=3)
    failure_family: FailureFamily
    mechanism_summary: NonEmptyString
    evidence_refs: list[EvidenceRef] = Field(min_length=1)
    counterevidence_refs: list[EvidenceRef] = Field(default_factory=list)
    certainty: DiagnosisCertainty


class FailureDiagnosis(DomainModel):
    """Optional inference or abstention; no fields can revise official truth."""

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    diagnosis_id: NonEmptyString
    bundle_sha256: Sha256Hex
    mode: DiagnosisMode
    subject_run_id: NonEmptyString
    abstain: Annotated[bool, Field(strict=True)]
    abstention_reason: NonEmptyString | None = None
    hypotheses: list[DiagnosisHypothesis] = Field(default_factory=list, max_length=3)
    recommendation: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_abstention(self) -> Self:
        if self.abstain:
            if self.abstention_reason is None or self.hypotheses:
                raise ValueError("abstention requires a reason and no hypotheses")
        else:
            if self.abstention_reason is not None or not self.hypotheses:
                raise ValueError("non-abstention requires hypotheses and no abstention reason")
            if [item.rank for item in self.hypotheses] != list(range(1, len(self.hypotheses) + 1)):
                raise ValueError("hypothesis ranks must be ordered and contiguous from 1")
        return self
