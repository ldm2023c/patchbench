"""Compute final deterministic metrics for Diagnosis Validation V1."""

from enum import Enum
import hashlib
import json
from pathlib import Path
import shutil
from typing import Mapping

from pydantic import ValidationError

from patchbench.application.diagnosis_gold_lock import OPERATIONAL_CASE_IDS, SEMANTIC_CASE_IDS
from patchbench.application.diagnosis_metrics import (
    DiagnosisMetricsError,
    aggregate_route_scores,
    aggregate_semantic_scores,
    compare_blind_contrastive,
)
from patchbench.application.diagnosis_suite import (
    _verify_embedded_gold_lock,
    compute_run_record_sha256,
    verify_diagnosis_validation_freeze,
)
from patchbench.application.diagnosis_validation import (
    compute_diagnosis_gold_sha256,
    score_diagnosis_route,
)
from patchbench.domain.diagnosis import DiagnosisMode, DiagnosisRoute, route_run_diagnosis
from patchbench.domain.diagnosis_gold_lock import compute_diagnosis_gold_lock_suite_sha256
from patchbench.domain.diagnosis_validation import DiagnosisGoldCase, SemanticDiagnosisScore
from patchbench.domain.diagnosis_validation_collection import (
    DiagnosisValidationCollection,
    compute_diagnosis_validation_collection_sha256,
)
from patchbench.domain.diagnosis_validation_results import (
    DiagnosisValidationFinalResult,
    compute_diagnosis_validation_result_sha256,
)
from patchbench.domain.diagnosis_validation_scoring import (
    DiagnosisValidationFinalScores,
    DiagnosisValidationScoringPreparation,
    compute_diagnosis_validation_final_scores_sha256,
    compute_diagnosis_validation_preparation_sha256,
)
from patchbench.domain.models import RunRecord


class DiagnosisValidationResultReason(str, Enum):
    INVALID_RESULT_ID = "invalid_result_id"
    MISSING_OR_INVALID_SEMANTIC_SCORE = "missing_or_invalid_semantic_score"
    SEMANTIC_SCORE_IDENTITY_MISMATCH = "semantic_score_identity_mismatch"
    UNFINISHED_SEMANTIC_SCORE_REVIEW = "unfinished_semantic_score_review"
    INVALID_PREPARATION = "invalid_preparation"
    PREPARATION_IDENTITY_MISMATCH = "preparation_identity_mismatch"
    INVALID_COLLECTION = "invalid_collection"
    COLLECTION_IDENTITY_MISMATCH = "collection_identity_mismatch"
    FROZEN_VALIDATION_IDENTITY_MISMATCH = "frozen_validation_identity_mismatch"
    INVALID_OPERATIONAL_GOLD = "invalid_operational_gold"
    INVALID_OPERATIONAL_RUN_RECORD = "invalid_operational_run_record"
    OPERATIONAL_PROVENANCE_MISMATCH = "operational_provenance_mismatch"
    OPERATIONAL_ROUTING_MISMATCH = "operational_routing_mismatch"
    METRICS_COMPUTATION_FAILED = "metrics_computation_failed"
    RESULT_ALREADY_EXISTS = "result_already_exists"
    RESULT_PERSISTENCE_FAILED = "result_persistence_failed"


class DiagnosisValidationResultError(RuntimeError):
    def __init__(self, reason: DiagnosisValidationResultReason, detail: str):
        self.reason = reason
        super().__init__(f"{reason.value}: {detail}")


def _disk_json_bytes(value) -> bytes:
    raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _safe_direct_child(value: str, reason: DiagnosisValidationResultReason) -> str:
    if (not isinstance(value, str) or not value or value in (".", "..")
            or value != value.strip() or value.startswith("/")
            or "/" in value or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise DiagnosisValidationResultError(reason, "unsafe direct-child identifier")
    return value


def _namespace(results_root: Path, name: str) -> Path:
    return Path(results_root) / "diagnosis-validation-v1" / name


def _direct_child_root(results_root: Path, namespace: str, identifier: str,
                       reason: DiagnosisValidationResultReason) -> Path:
    _safe_direct_child(identifier, reason)
    parent = _namespace(Path(results_root), namespace)
    root = parent / identifier
    if root.resolve(strict=False).parent != parent.resolve(strict=False):
        raise DiagnosisValidationResultError(reason, "identifier must resolve to one namespace child")
    return root


def _persist_create_only(root: Path, files: Mapping[str, bytes]) -> None:
    if root.exists():
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.RESULT_ALREADY_EXISTS,
            "result directory already exists",
        )
    created = False
    try:
        root.mkdir(parents=True, exist_ok=False)
        created = True
        for name, data in files.items():
            (root / name).write_bytes(data)
    except FileExistsError as error:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.RESULT_ALREADY_EXISTS,
            "result directory already exists",
        ) from error
    except OSError as error:
        if created:
            try:
                shutil.rmtree(root)
            except OSError as cleanup_error:
                raise DiagnosisValidationResultError(
                    DiagnosisValidationResultReason.RESULT_PERSISTENCE_FAILED,
                    f"result write failed and cleanup failed: {cleanup_error}",
                ) from error
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.RESULT_PERSISTENCE_FAILED,
            "unable to persist result",
        ) from error


def _freeze_sha(validation_root: Path) -> str:
    try:
        return hashlib.sha256((validation_root / "freeze-manifest.json").read_bytes()).hexdigest()
    except OSError as error:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.FROZEN_VALIDATION_IDENTITY_MISMATCH,
            "unable to read freeze manifest",
        ) from error


def _load_semantic_scores(results_root: Path, semantic_score_id: str) -> DiagnosisValidationFinalScores:
    root = _direct_child_root(
        results_root,
        "semantic-scores",
        semantic_score_id,
        DiagnosisValidationResultReason.MISSING_OR_INVALID_SEMANTIC_SCORE,
    )
    try:
        scores = DiagnosisValidationFinalScores.model_validate_json((root / "scores.json").read_bytes())
    except (OSError, UnicodeError, ValidationError) as error:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.MISSING_OR_INVALID_SEMANTIC_SCORE,
            "unable to load valid finalized semantic scores",
        ) from error
    if scores.score_id != semantic_score_id:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.SEMANTIC_SCORE_IDENTITY_MISMATCH,
            "score_id differs from requested ID",
        )
    if scores.score_sha256 is None or scores.score_sha256 != compute_diagnosis_validation_final_scores_sha256(scores):
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.SEMANTIC_SCORE_IDENTITY_MISMATCH,
            "score_sha256 differs from canonical content",
        )
    _verify_semantic_score_order_and_review(scores.scores)
    return scores


def _verify_semantic_score_order_and_review(scores: list[SemanticDiagnosisScore]) -> None:
    expected = [(case_id, mode) for case_id in SEMANTIC_CASE_IDS
                for mode in (DiagnosisMode.BLIND, DiagnosisMode.CONTRASTIVE)]
    actual = [(score.case_id, score.mode) for score in scores]
    if len(scores) != 26 or actual != expected:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.SEMANTIC_SCORE_IDENTITY_MISMATCH,
            "semantic score order differs from canonical V1 order",
        )
    unfinished = [score for score in scores
                  if score.overclaim_applicable
                  and (not score.overclaim_reviewed or score.overclaim_violation is None)]
    if unfinished:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.UNFINISHED_SEMANTIC_SCORE_REVIEW,
            "semantic overclaim-applicable scores must be finalized",
        )


def _load_preparation(results_root: Path, preparation_id: str) -> DiagnosisValidationScoringPreparation:
    root = _direct_child_root(
        results_root,
        "scoring-preparations",
        preparation_id,
        DiagnosisValidationResultReason.INVALID_PREPARATION,
    )
    try:
        preparation = DiagnosisValidationScoringPreparation.model_validate_json((root / "preparation.json").read_bytes())
    except (OSError, UnicodeError, ValidationError) as error:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.INVALID_PREPARATION,
            "unable to load valid scoring preparation",
        ) from error
    if preparation.preparation_id != preparation_id:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.PREPARATION_IDENTITY_MISMATCH,
            "preparation_id differs from finalized scores",
        )
    if preparation.preparation_sha256 != compute_diagnosis_validation_preparation_sha256(preparation):
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.PREPARATION_IDENTITY_MISMATCH,
            "preparation_sha256 differs from canonical content",
        )
    return preparation


def _load_collection(results_root: Path, collection_id: str) -> DiagnosisValidationCollection:
    root = _direct_child_root(
        results_root,
        "collections",
        collection_id,
        DiagnosisValidationResultReason.INVALID_COLLECTION,
    )
    try:
        collection = DiagnosisValidationCollection.model_validate_json((root / "collection.json").read_bytes())
    except (OSError, UnicodeError, ValidationError) as error:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.INVALID_COLLECTION,
            "unable to load valid collection",
        ) from error
    if collection.collection_id != collection_id:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.COLLECTION_IDENTITY_MISMATCH,
            "collection_id differs from provenance",
        )
    if collection.collection_sha256 != compute_diagnosis_validation_collection_sha256(collection):
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.COLLECTION_IDENTITY_MISMATCH,
            "collection_sha256 differs from canonical content",
        )
    if [case.case_id for case in collection.cases] != list(SEMANTIC_CASE_IDS):
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.COLLECTION_IDENTITY_MISMATCH,
            "collection case order differs from canonical semantic order",
        )
    return collection


def _verified_gold_lock(validation_root: Path, candidate_root: Path):
    try:
        manifest = verify_diagnosis_validation_freeze(validation_root, candidate_root)
        gold_lock = _verify_embedded_gold_lock(validation_root)
    except Exception as error:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.FROZEN_VALIDATION_IDENTITY_MISMATCH,
            "frozen validation suite or Gold lock failed verification",
        ) from error
    gold_lock_sha = compute_diagnosis_gold_lock_suite_sha256(gold_lock)
    if manifest.suite_sha256 != gold_lock_sha:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.FROZEN_VALIDATION_IDENTITY_MISMATCH,
            "freeze manifest does not bind verified Gold lock",
        )
    return manifest, gold_lock, gold_lock_sha, _freeze_sha(validation_root)


def _verify_provenance_chain(scores, preparation, collection, manifest, gold_lock_sha, freeze_sha_value) -> None:
    if (scores.preparation_id != preparation.preparation_id
            or scores.preparation_sha256 != preparation.preparation_sha256
            or scores.collection_id != preparation.collection_id
            or scores.collection_sha256 != preparation.collection_sha256
            or scores.freeze_manifest_sha256 != preparation.freeze_manifest_sha256
            or scores.frozen_suite_sha256 != preparation.frozen_suite_sha256
            or scores.gold_lock_suite_sha256 != preparation.gold_lock_suite_sha256):
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.PREPARATION_IDENTITY_MISMATCH,
            "finalized scores do not match preparation provenance",
        )
    if (preparation.collection_id != collection.collection_id
            or preparation.collection_sha256 != collection.collection_sha256):
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.COLLECTION_IDENTITY_MISMATCH,
            "preparation does not match collection provenance",
        )
    if (collection.freeze_manifest_sha256 != preparation.freeze_manifest_sha256
            or collection.freeze_manifest_sha256 != scores.freeze_manifest_sha256
            or collection.frozen_suite_sha256 != preparation.frozen_suite_sha256
            or collection.frozen_suite_sha256 != scores.frozen_suite_sha256):
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.COLLECTION_IDENTITY_MISMATCH,
            "collection frozen identity differs from preparation or semantic scores",
        )
    _verify_preparation_collection_slots(preparation, collection)
    if (scores.freeze_manifest_sha256 != freeze_sha_value
            or scores.frozen_suite_sha256 != manifest.suite_sha256
            or scores.gold_lock_suite_sha256 != gold_lock_sha
            or collection.freeze_manifest_sha256 != freeze_sha_value
            or collection.frozen_suite_sha256 != manifest.suite_sha256):
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.FROZEN_VALIDATION_IDENTITY_MISMATCH,
            "semantic scores differ from current frozen validation identity",
        )


def _verify_preparation_collection_slots(
    preparation: DiagnosisValidationScoringPreparation,
    collection: DiagnosisValidationCollection,
) -> None:
    if len(preparation.cases) != len(collection.cases) or len(collection.cases) != len(SEMANTIC_CASE_IDS):
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.PREPARATION_IDENTITY_MISMATCH,
            "preparation and collection case counts differ",
        )
    for expected_case_id, prepared, collected in zip(
        SEMANTIC_CASE_IDS, preparation.cases, collection.cases, strict=True,
    ):
        if (prepared.case_id != expected_case_id
                or collected.case_id != expected_case_id
                or prepared.case_id != collected.case_id
                or prepared.blind.run_id != collected.run_id
                or prepared.contrastive.run_id != collected.run_id):
            raise DiagnosisValidationResultError(
                DiagnosisValidationResultReason.PREPARATION_IDENTITY_MISMATCH,
                "preparation case provenance differs from selected collection",
            )
        for prepared_slot, collected_slot in (
            (prepared.blind, collected.blind),
            (prepared.contrastive, collected.contrastive),
        ):
            if (prepared_slot.mode is not collected_slot.mode
                    or prepared_slot.diagnosis_id != collected_slot.diagnosis_id
                    or prepared_slot.execution_sha256 != collected_slot.execution_sha256
                    or prepared_slot.bundle_sha256 != collected_slot.frozen_bundle_sha256):
                raise DiagnosisValidationResultError(
                    DiagnosisValidationResultReason.PREPARATION_IDENTITY_MISMATCH,
                    "preparation slot provenance differs from selected collection",
                )


_SEMANTIC_PREPARATION_PROJECTION = (
    "case_id",
    "gold_sha256",
    "subject_evidence_sha256",
    "diagnosis_id",
    "mode",
    "predicted_abstain",
    "abstention_correct",
    "preferred_top1_match",
    "top1_acceptable_match",
    "topk_acceptable_match",
    "required_evidence_satisfied",
    "required_evidence_total",
    "audit_passed",
    "audit_issue_count",
    "invalid_citation_issue_count",
    "overclaim_applicable",
)


def _semantic_preparation_projection(score: SemanticDiagnosisScore) -> tuple:
    return tuple(getattr(score, field) for field in _SEMANTIC_PREPARATION_PROJECTION)


def _preparation_slot_by_identity(preparation: DiagnosisValidationScoringPreparation):
    result = {}
    for case in preparation.cases:
        result[(case.case_id, DiagnosisMode.BLIND)] = case.blind
        result[(case.case_id, DiagnosisMode.CONTRASTIVE)] = case.contrastive
    return result


def _load_semantic_gold(validation_root: Path, lock_case) -> DiagnosisGoldCase:
    try:
        gold = DiagnosisGoldCase.model_validate_json((validation_root / lock_case.gold_path).read_bytes())
    except (OSError, UnicodeError, ValidationError) as error:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.FROZEN_VALIDATION_IDENTITY_MISMATCH,
            f"invalid locked semantic Gold for {lock_case.case_id}",
        ) from error
    if (gold.case_id != lock_case.case_id
            or gold.semantic_gold is None
            or compute_diagnosis_gold_sha256(gold) != lock_case.gold_sha256):
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.FROZEN_VALIDATION_IDENTITY_MISMATCH,
            f"locked semantic Gold identity differs for {lock_case.case_id}",
        )
    return gold


def _verify_semantic_scores_against_preparation_and_gold(
    validation_root: Path,
    scores: list[SemanticDiagnosisScore],
    preparation: DiagnosisValidationScoringPreparation,
    gold_lock,
) -> None:
    lock_by_case = {case.case_id: case for case in gold_lock.cases}
    slots = _preparation_slot_by_identity(preparation)
    for index, case_id in enumerate(SEMANTIC_CASE_IDS):
        lock_case = lock_by_case.get(case_id)
        if lock_case is None:
            raise DiagnosisValidationResultError(
                DiagnosisValidationResultReason.FROZEN_VALIDATION_IDENTITY_MISMATCH,
                f"missing semantic Gold lock case {case_id}",
            )
        gold = _load_semantic_gold(validation_root, lock_case)
        frozen_claim_ids = {claim.claim_id for claim in gold.semantic_gold.forbidden_claims}
        for score in (scores[2 * index], scores[2 * index + 1]):
            slot = slots.get((score.case_id, score.mode))
            if slot is None or _semantic_preparation_projection(score) != _semantic_preparation_projection(slot.preliminary_score):
                raise DiagnosisValidationResultError(
                    DiagnosisValidationResultReason.SEMANTIC_SCORE_IDENTITY_MISMATCH,
                    "semantic score differs from its D6-R4 preparation slot",
                )
            if (score.gold_sha256 != lock_case.gold_sha256
                    or score.subject_evidence_sha256 != lock_case.subject_evidence_sha256):
                raise DiagnosisValidationResultError(
                    DiagnosisValidationResultReason.SEMANTIC_SCORE_IDENTITY_MISMATCH,
                    "semantic score Gold or subject identity differs from frozen Gold lock",
                )
            if score.overclaim_applicable != bool(frozen_claim_ids):
                raise DiagnosisValidationResultError(
                    DiagnosisValidationResultReason.SEMANTIC_SCORE_IDENTITY_MISMATCH,
                    "semantic score overclaim applicability differs from frozen Gold",
                )
            if frozen_claim_ids:
                if (not score.overclaim_reviewed or score.overclaim_violation is None
                        or not set(score.violated_claim_ids).issubset(frozen_claim_ids)):
                    raise DiagnosisValidationResultError(
                        DiagnosisValidationResultReason.SEMANTIC_SCORE_IDENTITY_MISMATCH,
                        "semantic score overclaim review differs from frozen Gold claim IDs",
                    )


def _load_operational_gold(validation_root: Path, lock_case) -> DiagnosisGoldCase:
    try:
        gold = DiagnosisGoldCase.model_validate_json((validation_root / lock_case.route_gold_path).read_bytes())
    except (OSError, UnicodeError, ValidationError) as error:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.INVALID_OPERATIONAL_GOLD,
            f"invalid operational route Gold for {lock_case.case_id}",
        ) from error
    if (gold.case_id != lock_case.case_id
            or gold.expected_route is not DiagnosisRoute.OPERATIONAL_ONLY
            or compute_diagnosis_gold_sha256(gold) != lock_case.route_gold_sha256):
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.INVALID_OPERATIONAL_GOLD,
            f"operational route Gold identity differs for {lock_case.case_id}",
        )
    return gold


def _load_operational_run(validation_root: Path, lock_case) -> RunRecord:
    try:
        run = RunRecord.model_validate_json((validation_root / lock_case.run_record_path).read_bytes())
    except (OSError, UnicodeError, ValidationError) as error:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.INVALID_OPERATIONAL_RUN_RECORD,
            f"invalid operational RunRecord for {lock_case.case_id}",
        ) from error
    if run.task_id != lock_case.case_id:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.OPERATIONAL_PROVENANCE_MISMATCH,
            f"operational RunRecord task_id differs for {lock_case.case_id}",
        )
    if compute_run_record_sha256(run) != lock_case.run_record_sha256:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.OPERATIONAL_PROVENANCE_MISMATCH,
            f"operational RunRecord hash differs for {lock_case.case_id}",
        )
    decision = route_run_diagnosis(run)
    if decision.route is not lock_case.expected_route or decision.reason is not lock_case.expected_routing_reason:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.OPERATIONAL_ROUTING_MISMATCH,
            f"operational route decision differs for {lock_case.case_id}",
        )
    return run


def _score_operational_cases(validation_root: Path, gold_lock):
    lock_by_case = {case.case_id: case for case in gold_lock.cases}
    scores = []
    for case_id in OPERATIONAL_CASE_IDS:
        lock_case = lock_by_case.get(case_id)
        if lock_case is None or lock_case.expected_route is not DiagnosisRoute.OPERATIONAL_ONLY:
            raise DiagnosisValidationResultError(
                DiagnosisValidationResultReason.INVALID_OPERATIONAL_GOLD,
                f"missing operational lock case {case_id}",
            )
        gold = _load_operational_gold(validation_root, lock_case)
        run = _load_operational_run(validation_root, lock_case)
        scores.append(score_diagnosis_route(run, gold))
    return scores


def _semantic_comparison(scores: list[SemanticDiagnosisScore]):
    blind = scores[0::2]
    contrastive = scores[1::2]
    try:
        blind_aggregate = aggregate_semantic_scores(blind)
        contrastive_aggregate = aggregate_semantic_scores(contrastive)
        comparison = compare_blind_contrastive(blind, contrastive)
    except DiagnosisMetricsError as error:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.METRICS_COMPUTATION_FAILED,
            "semantic metric computation failed",
        ) from error
    if comparison.blind_aggregate != blind_aggregate or comparison.contrastive_aggregate != contrastive_aggregate:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.METRICS_COMPUTATION_FAILED,
            "comparison aggregates differ from direct aggregate computation",
        )
    return comparison


def compute_diagnosis_validation_results(
    *,
    validation_root: Path,
    candidate_root: Path,
    results_root: Path,
    semantic_score_id: str,
    result_id: str,
) -> DiagnosisValidationFinalResult:
    validation_root = Path(validation_root)
    candidate_root = Path(candidate_root)
    results_root = Path(results_root)
    result_root = _direct_child_root(
        results_root,
        "final-results",
        result_id,
        DiagnosisValidationResultReason.INVALID_RESULT_ID,
    )
    semantic_scores = _load_semantic_scores(results_root, semantic_score_id)
    preparation = _load_preparation(results_root, semantic_scores.preparation_id)
    collection = _load_collection(results_root, semantic_scores.collection_id)
    manifest, gold_lock, gold_lock_sha, freeze_sha_value = _verified_gold_lock(validation_root, candidate_root)
    _verify_provenance_chain(semantic_scores, preparation, collection, manifest, gold_lock_sha, freeze_sha_value)
    _verify_semantic_scores_against_preparation_and_gold(
        validation_root, semantic_scores.scores, preparation, gold_lock)

    operational_scores = _score_operational_cases(validation_root, gold_lock)
    try:
        operational_aggregate = aggregate_route_scores(operational_scores)
        semantic_comparison = _semantic_comparison(semantic_scores.scores)
    except DiagnosisMetricsError as error:
        raise DiagnosisValidationResultError(
            DiagnosisValidationResultReason.METRICS_COMPUTATION_FAILED,
            "metric computation failed",
        ) from error

    result = DiagnosisValidationFinalResult(
        result_id=result_id,
        semantic_score_id=semantic_scores.score_id,
        semantic_score_sha256=semantic_scores.score_sha256,
        preparation_id=semantic_scores.preparation_id,
        preparation_sha256=semantic_scores.preparation_sha256,
        collection_id=semantic_scores.collection_id,
        collection_sha256=semantic_scores.collection_sha256,
        freeze_manifest_sha256=semantic_scores.freeze_manifest_sha256,
        frozen_suite_sha256=semantic_scores.frozen_suite_sha256,
        gold_lock_suite_sha256=semantic_scores.gold_lock_suite_sha256,
        operational_scores=operational_scores,
        operational_aggregate=operational_aggregate,
        semantic_comparison=semantic_comparison,
    )
    result = DiagnosisValidationFinalResult.model_validate(result.model_dump(mode="json") | {
        "result_sha256": compute_diagnosis_validation_result_sha256(result),
    })
    _persist_create_only(result_root, {"result.json": _disk_json_bytes(result)})
    return result
