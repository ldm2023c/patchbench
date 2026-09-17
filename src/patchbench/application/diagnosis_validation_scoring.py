"""Prepare and finalize deterministic semantic scoring for Diagnosis Validation V1."""

from enum import Enum
import hashlib
import json
from pathlib import Path
import shutil
from typing import Mapping

from pydantic import ValidationError

from patchbench.application.diagnosis_gold_lock import SEMANTIC_CASE_IDS
from patchbench.application.diagnosis_suite import (
    _verify_embedded_gold_lock,
    verify_diagnosis_validation_freeze,
)
from patchbench.application.diagnosis_validation import (
    DiagnosisValidationError,
    compute_diagnosis_gold_sha256,
    score_semantic_diagnosis,
)
from patchbench.domain.diagnosis import DiagnosisMode
from patchbench.domain.diagnosis_gold_lock import compute_diagnosis_gold_lock_suite_sha256
from patchbench.domain.diagnosis_integrity import compute_bundle_sha256
from patchbench.domain.diagnosis_validation import DiagnosisGoldCase, DiagnosisOverclaimReview
from patchbench.domain.diagnosis_validation_collection import (
    DiagnosisValidationCollection,
    compute_diagnosis_validation_collection_sha256,
)
from patchbench.domain.diagnosis_validation_scoring import (
    DiagnosisValidationFinalScores,
    DiagnosisValidationOverclaimPacketItem,
    DiagnosisValidationOverclaimReviewPacket,
    DiagnosisValidationOverclaimReviewSet,
    DiagnosisValidationScoredCase,
    DiagnosisValidationScoredSlot,
    DiagnosisValidationScoringPreparation,
    compute_diagnosis_validation_final_scores_sha256,
    compute_diagnosis_validation_preparation_sha256,
    compute_diagnosis_validation_review_packet_sha256,
)
from patchbench.storage.filesystem import ArtifactStoreError, FilesystemArtifactStore


class DiagnosisValidationScoringReason(str, Enum):
    INVALID_PREPARATION_ID = "invalid_preparation_id"
    MISSING_OR_INVALID_COLLECTION = "missing_or_invalid_collection"
    COLLECTION_IDENTITY_MISMATCH = "collection_identity_mismatch"
    INVALID_FROZEN_GOLD_LOCK = "invalid_frozen_gold_lock"
    DIAGNOSIS_ARTIFACT_MISMATCH = "diagnosis_artifact_mismatch"
    SCORING_PREPARATION_ALREADY_EXISTS = "scoring_preparation_already_exists"
    PREPARATION_PERSISTENCE_FAILED = "preparation_persistence_failed"
    INVALID_PREPARATION = "invalid_preparation"
    INVALID_REVIEW_SET = "invalid_review_set"
    MISSING_REVIEW = "missing_review"
    EXTRA_REVIEW = "extra_review"
    DUPLICATE_REVIEW = "duplicate_review"
    REVIEW_LINKAGE_MISMATCH = "review_linkage_mismatch"
    SCORE_ID_INVALID = "score_id_invalid"
    SCORE_ALREADY_EXISTS = "score_already_exists"
    SCORE_PERSISTENCE_FAILED = "score_persistence_failed"


class DiagnosisValidationScoringError(RuntimeError):
    def __init__(self, reason: DiagnosisValidationScoringReason, detail: str):
        self.reason = reason
        super().__init__(f"{reason.value}: {detail}")


def _disk_json_bytes(value) -> bytes:
    raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _safe_direct_child(value: str, reason: DiagnosisValidationScoringReason) -> str:
    if (not isinstance(value, str) or not value or value in (".", "..")
            or value != value.strip() or value.startswith("/")
            or "/" in value or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise DiagnosisValidationScoringError(reason, "unsafe direct-child identifier")
    return value


def _namespace(results_root: Path, name: str) -> Path:
    return Path(results_root) / "diagnosis-validation-v1" / name


def _direct_child_root(results_root: Path, namespace: str, identifier: str,
                       reason: DiagnosisValidationScoringReason) -> Path:
    _safe_direct_child(identifier, reason)
    parent = _namespace(Path(results_root), namespace)
    root = parent / identifier
    if root.resolve(strict=False).parent != parent.resolve(strict=False):
        raise DiagnosisValidationScoringError(reason, "identifier must resolve to one namespace child")
    return root


def _persist_create_only(root: Path, files: Mapping[str, bytes], exists_reason,
                         failure_reason) -> None:
    if root.exists():
        raise DiagnosisValidationScoringError(exists_reason, "output directory already exists")
    created = False
    try:
        root.mkdir(parents=True, exist_ok=False)
        created = True
        for name, data in files.items():
            (root / name).write_bytes(data)
    except FileExistsError as error:
        raise DiagnosisValidationScoringError(exists_reason, "output directory already exists") from error
    except OSError as error:
        if created:
            try:
                shutil.rmtree(root)
            except OSError as cleanup_error:
                raise DiagnosisValidationScoringError(
                    failure_reason,
                    f"output write failed and cleanup failed: {cleanup_error}",
                ) from error
        raise DiagnosisValidationScoringError(failure_reason, "unable to persist output") from error


def _freeze_sha(validation_root: Path) -> str:
    try:
        return hashlib.sha256((validation_root / "freeze-manifest.json").read_bytes()).hexdigest()
    except OSError as error:
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.INVALID_FROZEN_GOLD_LOCK,
            "unable to read freeze manifest",
        ) from error


def _verified_gold(validation_root: Path, candidate_root: Path):
    try:
        manifest = verify_diagnosis_validation_freeze(validation_root, candidate_root)
        gold_lock = _verify_embedded_gold_lock(validation_root)
    except Exception as error:
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.INVALID_FROZEN_GOLD_LOCK,
            "frozen validation suite or Gold lock failed verification",
        ) from error
    gold_lock_sha = compute_diagnosis_gold_lock_suite_sha256(gold_lock)
    if manifest.suite_sha256 != gold_lock_sha:
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.INVALID_FROZEN_GOLD_LOCK,
            "freeze manifest does not bind the verified Gold lock suite",
        )
    gold_by_case = {}
    lock_by_case = {case.case_id: case for case in gold_lock.cases}
    for case_id in SEMANTIC_CASE_IDS:
        lock_case = lock_by_case.get(case_id)
        if lock_case is None or lock_case.gold_path is None or lock_case.gold_sha256 is None:
            raise DiagnosisValidationScoringError(
                DiagnosisValidationScoringReason.INVALID_FROZEN_GOLD_LOCK,
                f"missing locked semantic Gold for {case_id}",
            )
        try:
            gold = DiagnosisGoldCase.model_validate_json((validation_root / lock_case.gold_path).read_bytes())
        except (OSError, UnicodeError, ValidationError) as error:
            raise DiagnosisValidationScoringError(
                DiagnosisValidationScoringReason.INVALID_FROZEN_GOLD_LOCK,
                f"invalid locked Gold for {case_id}",
            ) from error
        if (gold.case_id != case_id
                or compute_diagnosis_gold_sha256(gold) != lock_case.gold_sha256):
            raise DiagnosisValidationScoringError(
                DiagnosisValidationScoringReason.INVALID_FROZEN_GOLD_LOCK,
                f"locked Gold identity differs for {case_id}",
            )
        gold_by_case[case_id] = gold
    return manifest, gold_lock_sha, lock_by_case, gold_by_case


def _load_collection(results_root: Path, collection_id: str) -> DiagnosisValidationCollection:
    root = _direct_child_root(
        results_root,
        "collections",
        collection_id,
        DiagnosisValidationScoringReason.MISSING_OR_INVALID_COLLECTION,
    )
    try:
        collection = DiagnosisValidationCollection.model_validate_json((root / "collection.json").read_bytes())
    except (OSError, UnicodeError, ValidationError) as error:
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.MISSING_OR_INVALID_COLLECTION,
            "unable to load valid collection",
        ) from error
    if collection.collection_id != collection_id:
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.COLLECTION_IDENTITY_MISMATCH,
            "collection_id differs from requested ID",
        )
    expected_sha = compute_diagnosis_validation_collection_sha256(collection)
    if collection.collection_sha256 != expected_sha:
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.COLLECTION_IDENTITY_MISMATCH,
            "collection_sha256 does not match canonical collection content",
        )
    if [case.case_id for case in collection.cases] != list(SEMANTIC_CASE_IDS):
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.COLLECTION_IDENTITY_MISMATCH,
            "collection case order differs from canonical semantic order",
        )
    return collection


def _verify_collection_freeze(collection, manifest, freeze_sha_value):
    if (collection.freeze_manifest_sha256 != freeze_sha_value
            or collection.frozen_suite_sha256 != manifest.suite_sha256):
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.COLLECTION_IDENTITY_MISMATCH,
            "collection frozen identity differs from the verified suite",
        )


def _load_execution(results_root: Path, run_id: str, slot, case_id: str):
    run_root = _namespace(results_root, run_id)
    try:
        bundle, diagnosis, audit, execution = FilesystemArtifactStore(run_root).load_diagnosis_execution_artifacts(slot.diagnosis_id)
    except ArtifactStoreError as error:
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.DIAGNOSIS_ARTIFACT_MISMATCH,
            "Diagnosis execution artifact failed integrity validation",
        ) from error
    if (diagnosis.diagnosis_id != slot.diagnosis_id
            or execution.execution_sha256 != slot.execution_sha256
            or execution.diagnosis_id != slot.diagnosis_id
            or bundle.bundle_sha256 != slot.frozen_bundle_sha256
            or compute_bundle_sha256(bundle) != bundle.bundle_sha256
            or bundle.mode is not slot.mode
            or diagnosis.mode is not slot.mode
            or bundle.task_id != case_id):
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.DIAGNOSIS_ARTIFACT_MISMATCH,
            "Diagnosis execution artifact differs from collection identity",
        )
    return bundle, diagnosis, audit, execution


def _scored_slot(results_root: Path, case_id: str, run_id: str, slot, gold, review=None):
    bundle, diagnosis, _audit, _execution = _load_execution(results_root, run_id, slot, case_id)
    try:
        score = score_semantic_diagnosis(bundle, diagnosis, gold, overclaim_review=review)
    except DiagnosisValidationError as error:
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.DIAGNOSIS_ARTIFACT_MISMATCH,
            "Diagnosis could not be scored against frozen Gold",
        ) from error
    return DiagnosisValidationScoredSlot(
        mode=slot.mode,
        run_id=run_id,
        diagnosis_id=diagnosis.diagnosis_id,
        execution_sha256=slot.execution_sha256,
        bundle_sha256=bundle.bundle_sha256,
        gold_sha256=score.gold_sha256,
        preliminary_score=score,
    ), diagnosis


def _prepare_material(validation_root: Path, candidate_root: Path, results_root: Path,
                      collection_id: str):
    manifest, gold_lock_sha, _lock_by_case, gold_by_case = _verified_gold(validation_root, candidate_root)
    freeze_sha_value = _freeze_sha(validation_root)
    collection = _load_collection(results_root, collection_id)
    _verify_collection_freeze(collection, manifest, freeze_sha_value)
    return manifest, gold_lock_sha, gold_by_case, collection, freeze_sha_value


def prepare_diagnosis_validation_scoring(
    *,
    validation_root: Path,
    candidate_root: Path,
    results_root: Path,
    collection_id: str,
    preparation_id: str,
) -> tuple[DiagnosisValidationScoringPreparation, DiagnosisValidationOverclaimReviewPacket]:
    validation_root = Path(validation_root)
    candidate_root = Path(candidate_root)
    results_root = Path(results_root)
    preparation_root = _direct_child_root(
        results_root,
        "scoring-preparations",
        preparation_id,
        DiagnosisValidationScoringReason.INVALID_PREPARATION_ID,
    )
    manifest, gold_lock_sha, gold_by_case, collection, freeze_sha_value = _prepare_material(
        validation_root, candidate_root, results_root, collection_id)

    scored_cases = []
    packet_items = []
    for collected in collection.cases:
        gold = gold_by_case[collected.case_id]
        if gold.semantic_gold is None:
            raise DiagnosisValidationScoringError(
                DiagnosisValidationScoringReason.INVALID_FROZEN_GOLD_LOCK,
                "semantic Gold is absent",
            )
        blind_slot, blind_diagnosis = _scored_slot(
            results_root, collected.case_id, collected.run_id, collected.blind, gold)
        contrastive_slot, contrastive_diagnosis = _scored_slot(
            results_root, collected.case_id, collected.run_id, collected.contrastive, gold)
        scored_cases.append(DiagnosisValidationScoredCase(
            case_id=collected.case_id,
            blind=blind_slot,
            contrastive=contrastive_slot,
        ))
        claims = gold.semantic_gold.forbidden_claims
        if claims:
            for mode, diagnosis, score in (
                (DiagnosisMode.BLIND, blind_diagnosis, blind_slot.preliminary_score),
                (DiagnosisMode.CONTRASTIVE, contrastive_diagnosis, contrastive_slot.preliminary_score),
            ):
                packet_items.append(DiagnosisValidationOverclaimPacketItem(
                    case_id=collected.case_id,
                    mode=mode,
                    diagnosis_id=diagnosis.diagnosis_id,
                    gold_sha256=score.gold_sha256,
                    forbidden_claims=claims,
                    diagnosis=diagnosis,
                ))

    preparation = DiagnosisValidationScoringPreparation(
        preparation_id=preparation_id,
        collection_id=collection.collection_id,
        collection_sha256=collection.collection_sha256,
        freeze_manifest_sha256=freeze_sha_value,
        frozen_suite_sha256=manifest.suite_sha256,
        gold_lock_suite_sha256=gold_lock_sha,
        cases=scored_cases,
    )
    preparation = DiagnosisValidationScoringPreparation.model_validate(
        preparation.model_dump(mode="json") | {
            "preparation_sha256": compute_diagnosis_validation_preparation_sha256(preparation),
        }
    )
    packet = DiagnosisValidationOverclaimReviewPacket(
        preparation_id=preparation.preparation_id,
        preparation_sha256=preparation.preparation_sha256,
        collection_id=collection.collection_id,
        collection_sha256=collection.collection_sha256,
        items=packet_items,
    )
    packet = DiagnosisValidationOverclaimReviewPacket.model_validate(
        packet.model_dump(mode="json") | {
            "packet_sha256": compute_diagnosis_validation_review_packet_sha256(packet),
        }
    )
    _persist_create_only(
        preparation_root,
        {
            "preparation.json": _disk_json_bytes(preparation),
            "overclaim-review-packet.json": _disk_json_bytes(packet),
        },
        DiagnosisValidationScoringReason.SCORING_PREPARATION_ALREADY_EXISTS,
        DiagnosisValidationScoringReason.PREPARATION_PERSISTENCE_FAILED,
    )
    return preparation, packet


def _load_preparation(results_root: Path, preparation_id: str) -> DiagnosisValidationScoringPreparation:
    root = _direct_child_root(
        results_root,
        "scoring-preparations",
        preparation_id,
        DiagnosisValidationScoringReason.INVALID_PREPARATION_ID,
    )
    try:
        preparation = DiagnosisValidationScoringPreparation.model_validate_json(
            (root / "preparation.json").read_bytes())
    except (OSError, UnicodeError, ValidationError) as error:
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.INVALID_PREPARATION,
            "unable to load valid scoring preparation",
        ) from error
    if preparation.preparation_id != preparation_id:
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.INVALID_PREPARATION,
            "preparation_id differs from requested ID",
        )
    if preparation.preparation_sha256 != compute_diagnosis_validation_preparation_sha256(preparation):
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.INVALID_PREPARATION,
            "preparation_sha256 mismatch",
        )
    return preparation


def _load_review_set(path: Path) -> DiagnosisValidationOverclaimReviewSet:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.INVALID_REVIEW_SET,
            "unable to load valid review JSON",
        ) from error
    reviews = raw.get("reviews") if isinstance(raw, dict) else None
    if isinstance(reviews, list):
        identities = []
        for review in reviews:
            if isinstance(review, dict):
                identities.append((review.get("case_id"), review.get("diagnosis_id")))
        if len(identities) != len(set(identities)):
            raise DiagnosisValidationScoringError(
                DiagnosisValidationScoringReason.DUPLICATE_REVIEW,
                "duplicate review identity",
            )
    try:
        return DiagnosisValidationOverclaimReviewSet.model_validate(raw)
    except ValidationError as error:
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.INVALID_REVIEW_SET,
            "review set failed typed validation",
        ) from error


def _expected_review_map(preparation: DiagnosisValidationScoringPreparation, gold_by_case):
    expected = {}
    for case in preparation.cases:
        gold = gold_by_case[case.case_id]
        claims = gold.semantic_gold.forbidden_claims if gold.semantic_gold is not None else []
        if not claims:
            continue
        claim_ids = {claim.claim_id for claim in claims}
        for slot in (case.blind, case.contrastive):
            expected[(case.case_id, slot.diagnosis_id)] = claim_ids
    return expected


def _review_lookup(review_set: DiagnosisValidationOverclaimReviewSet,
                   preparation: DiagnosisValidationScoringPreparation,
                   gold_by_case) -> dict[tuple[str, str], DiagnosisOverclaimReview]:
    if (review_set.preparation_id != preparation.preparation_id
            or review_set.preparation_sha256 != preparation.preparation_sha256):
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.INVALID_REVIEW_SET,
            "review set does not bind this preparation",
        )
    expected = _expected_review_map(preparation, gold_by_case)
    actual = {(review.case_id, review.diagnosis_id): review for review in review_set.reviews}
    missing = set(expected) - set(actual)
    extra = set(actual) - set(expected)
    if missing:
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.MISSING_REVIEW,
            f"missing overclaim reviews: {sorted(missing)}",
        )
    if extra:
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.EXTRA_REVIEW,
            f"unexpected overclaim reviews: {sorted(extra)}",
        )
    for key, review in actual.items():
        if not set(review.violated_claim_ids).issubset(expected[key]):
            raise DiagnosisValidationScoringError(
                DiagnosisValidationScoringReason.REVIEW_LINKAGE_MISMATCH,
                "review references a forbidden claim outside frozen Gold",
            )
    return actual


def _validate_preparation_against_current_inputs(preparation, manifest, gold_lock_sha, collection, freeze_sha_value):
    if (preparation.collection_id != collection.collection_id
            or preparation.collection_sha256 != collection.collection_sha256
            or preparation.freeze_manifest_sha256 != freeze_sha_value
            or preparation.frozen_suite_sha256 != manifest.suite_sha256
            or preparation.gold_lock_suite_sha256 != gold_lock_sha
            or [case.case_id for case in preparation.cases] != list(SEMANTIC_CASE_IDS)):
        raise DiagnosisValidationScoringError(
            DiagnosisValidationScoringReason.INVALID_PREPARATION,
            "preparation identity differs from current verified inputs",
        )


def finalize_diagnosis_validation_scoring(
    *,
    validation_root: Path,
    candidate_root: Path,
    results_root: Path,
    preparation_id: str,
    review_file: Path,
    score_id: str,
) -> DiagnosisValidationFinalScores:
    validation_root = Path(validation_root)
    candidate_root = Path(candidate_root)
    results_root = Path(results_root)
    score_root = _direct_child_root(
        results_root,
        "semantic-scores",
        score_id,
        DiagnosisValidationScoringReason.SCORE_ID_INVALID,
    )
    preparation = _load_preparation(results_root, preparation_id)
    manifest, gold_lock_sha, gold_by_case, collection, freeze_sha_value = _prepare_material(
        validation_root, candidate_root, results_root, preparation.collection_id)
    _validate_preparation_against_current_inputs(
        preparation, manifest, gold_lock_sha, collection, freeze_sha_value)
    review_set = _load_review_set(review_file)
    reviews = _review_lookup(review_set, preparation, gold_by_case)

    collected_by_case = {case.case_id: case for case in collection.cases}
    final_scores = []
    for prepared_case in preparation.cases:
        gold = gold_by_case[prepared_case.case_id]
        collected = collected_by_case[prepared_case.case_id]
        for prepared_slot, collected_slot in (
            (prepared_case.blind, collected.blind),
            (prepared_case.contrastive, collected.contrastive),
        ):
            if (prepared_slot.run_id != collected.run_id
                    or prepared_slot.diagnosis_id != collected_slot.diagnosis_id
                    or prepared_slot.execution_sha256 != collected_slot.execution_sha256
                    or prepared_slot.bundle_sha256 != collected_slot.frozen_bundle_sha256):
                raise DiagnosisValidationScoringError(
                    DiagnosisValidationScoringReason.INVALID_PREPARATION,
                    "preparation slot identity differs from collection",
                )
            review = reviews.get((prepared_case.case_id, prepared_slot.diagnosis_id))
            slot_score, _diagnosis = _scored_slot(
                results_root, prepared_case.case_id, prepared_slot.run_id, collected_slot, gold, review=review)
            score = slot_score.preliminary_score
            if score.overclaim_applicable and not score.overclaim_reviewed:
                raise DiagnosisValidationScoringError(
                    DiagnosisValidationScoringReason.MISSING_REVIEW,
                    "applicable overclaim score was not reviewed",
                )
            if not score.overclaim_applicable and (score.overclaim_reviewed or score.overclaim_violation is not None):
                raise DiagnosisValidationScoringError(
                    DiagnosisValidationScoringReason.REVIEW_LINKAGE_MISMATCH,
                    "non-applicable score was reviewed",
                )
            final_scores.append(score)

    artifact = DiagnosisValidationFinalScores(
        score_id=score_id,
        preparation_id=preparation.preparation_id,
        preparation_sha256=preparation.preparation_sha256,
        collection_id=preparation.collection_id,
        collection_sha256=preparation.collection_sha256,
        freeze_manifest_sha256=preparation.freeze_manifest_sha256,
        frozen_suite_sha256=preparation.frozen_suite_sha256,
        gold_lock_suite_sha256=preparation.gold_lock_suite_sha256,
        scores=final_scores,
    )
    artifact = DiagnosisValidationFinalScores.model_validate(
        artifact.model_dump(mode="json") | {
            "score_sha256": compute_diagnosis_validation_final_scores_sha256(artifact),
        }
    )
    _persist_create_only(
        score_root,
        {"scores.json": _disk_json_bytes(artifact)},
        DiagnosisValidationScoringReason.SCORE_ALREADY_EXISTS,
        DiagnosisValidationScoringReason.SCORE_PERSISTENCE_FAILED,
    )
    return artifact
