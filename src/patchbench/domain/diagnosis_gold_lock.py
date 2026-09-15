"""Typed contracts for the pre-Contrastive Diagnosis Human Gold lock."""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from patchbench.domain.diagnosis import DiagnosisRoute, DiagnosisRoutingReason
from patchbench.domain.diagnosis_integrity import canonical_json_bytes
from patchbench.domain.diagnosis_suite import FrozenValidationFile, validate_suite_relative_path
from patchbench.domain.models import DomainModel, Sha256Hex


ExactString = Annotated[str, StringConstraints(strict=True, strip_whitespace=False, min_length=1)]


class DiagnosisGoldLockCase(DomainModel):
    """One semantic or operational case at the pre-Contrastive lock boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    case_id: ExactString
    expected_route: DiagnosisRoute

    blind_bundle_path: ExactString | None = None
    gold_path: ExactString | None = None
    subject_evidence_sha256: Sha256Hex | None = None
    blind_bundle_sha256: Sha256Hex | None = None
    gold_sha256: Sha256Hex | None = None

    run_record_path: ExactString | None = None
    run_record_sha256: Sha256Hex | None = None
    route_gold_path: ExactString | None = None
    route_gold_sha256: Sha256Hex | None = None
    expected_routing_reason: DiagnosisRoutingReason | None = None

    @field_validator("blind_bundle_path", "gold_path", "run_record_path", "route_gold_path")
    @classmethod
    def validate_paths(cls, path: str | None) -> str | None:
        return None if path is None else validate_suite_relative_path(path)

    @model_validator(mode="after")
    def validate_route_shape(self) -> Self:
        semantic_fields = (
            self.blind_bundle_path, self.gold_path, self.subject_evidence_sha256,
            self.blind_bundle_sha256, self.gold_sha256,
        )
        operational_fields = (
            self.run_record_path, self.run_record_sha256, self.route_gold_path,
            self.route_gold_sha256, self.expected_routing_reason,
        )
        if self.expected_route is DiagnosisRoute.SEMANTIC_DIAGNOSIS:
            if any(value is None for value in semantic_fields) or any(
                    value is not None for value in operational_fields):
                raise ValueError("semantic lock case requires only all Blind/Gold fields")
        elif self.expected_route is DiagnosisRoute.OPERATIONAL_ONLY:
            if any(value is not None for value in semantic_fields) or any(
                    value is None for value in operational_fields):
                raise ValueError("operational lock case requires only all route fields")
            if self.expected_routing_reason not in {
                DiagnosisRoutingReason.AGENT_COMMAND_FAILED,
                DiagnosisRoutingReason.AGENT_TIMED_OUT,
            }:
                raise ValueError("operational lock reason must be command_failed or timed_out")
        else:
            raise ValueError("Gold lock does not support unavailable cases")
        return self


class DiagnosisGoldLockSuite(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    suite_id: Literal["diagnosis-validation-v1"] = "diagnosis-validation-v1"
    status: Literal["gold_locked_pre_contrastive"] = "gold_locked_pre_contrastive"
    cases: list[DiagnosisGoldLockCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_cases(self) -> Self:
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Gold lock case IDs must be unique")
        paths = [path for case in self.cases for path in (
            case.blind_bundle_path, case.gold_path, case.run_record_path, case.route_gold_path)
                 if path is not None]
        if len(paths) != len(set(paths)):
            raise ValueError("Gold lock artifact paths must be unique")
        return self


def compute_diagnosis_gold_lock_suite_sha256(suite: DiagnosisGoldLockSuite) -> Sha256Hex:
    return hashlib.sha256(canonical_json_bytes(suite.model_dump(mode="json"))).hexdigest()


class DiagnosisGoldLockManifest(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    suite_id: Literal["diagnosis-validation-v1"] = "diagnosis-validation-v1"
    lock_stage: Literal["pre_contrastive"] = "pre_contrastive"
    suite_sha256: Sha256Hex
    selected_case_ids: list[ExactString] = Field(min_length=1)
    files: list[FrozenValidationFile] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if len(self.selected_case_ids) != len(set(self.selected_case_ids)):
            raise ValueError("selected case IDs must be unique")
        paths = [item.path for item in self.files]
        if paths != sorted(paths):
            raise ValueError("Gold lock files must be sorted by path")
        if len(paths) != len(set(paths)):
            raise ValueError("Gold lock file paths must be unique")
        if "gold-lock-manifest.json" in paths:
            raise ValueError("Gold lock manifest must not hash itself")
        if "suite.json" not in paths:
            raise ValueError("Gold lock manifest must cover suite.json")
        return self
