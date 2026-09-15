"""Typed contracts for a frozen Diagnosis validation suite."""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from patchbench.domain.diagnosis import DiagnosisRoute, DiagnosisRoutingReason
from patchbench.domain.diagnosis_integrity import canonical_json_bytes
from patchbench.domain.models import DomainModel, Sha256Hex


ExactString = Annotated[str, StringConstraints(strict=True, strip_whitespace=False, min_length=1)]


def validate_suite_relative_path(path: str) -> str:
    """Reject rather than normalize a noncanonical suite-root-relative path."""
    if (not path or path != path.strip() or path.startswith("/")
            or "\\" in path or ":" in path
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
            or any(part in ("", ".", "..") for part in path.split("/"))):
        raise ValueError("path must be canonical suite-root-relative POSIX text")
    return path


class FrozenValidationFile(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    path: ExactString
    sha256: Sha256Hex
    byte_length: int = Field(strict=True, ge=0)

    _path = field_validator("path")(validate_suite_relative_path)


class DiagnosisValidationSuiteCaseFile(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    case_id: ExactString
    path: ExactString
    sha256: Sha256Hex

    _path = field_validator("path")(validate_suite_relative_path)


class DiagnosisValidationSuiteCase(DomainModel):
    """One final semantic or operational case and all identity linkages."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    case_id: ExactString
    expected_route: DiagnosisRoute
    gold_path: ExactString
    gold_sha256: Sha256Hex

    subject_evidence_sha256: Sha256Hex | None = None
    blind_bundle_path: ExactString | None = None
    blind_bundle_sha256: Sha256Hex | None = None
    contrastive_bundle_path: ExactString | None = None
    contrastive_bundle_sha256: Sha256Hex | None = None
    peer_selection_path: ExactString | None = None
    peer_selection_sha256: Sha256Hex | None = None
    peer_artifact_store_path: ExactString | None = None

    expected_routing_reason: DiagnosisRoutingReason | None = None
    run_record_path: ExactString | None = None
    run_record_sha256: Sha256Hex | None = None

    @field_validator("gold_path", "blind_bundle_path", "contrastive_bundle_path",
                     "peer_selection_path", "peer_artifact_store_path", "run_record_path")
    @classmethod
    def validate_paths(cls, path: str | None) -> str | None:
        return None if path is None else validate_suite_relative_path(path)

    @model_validator(mode="after")
    def validate_route_shape(self) -> Self:
        semantic_fields = (
            self.subject_evidence_sha256, self.blind_bundle_path,
            self.blind_bundle_sha256, self.contrastive_bundle_path,
            self.contrastive_bundle_sha256, self.peer_selection_path,
            self.peer_selection_sha256, self.peer_artifact_store_path,
        )
        operational_fields = (
            self.expected_routing_reason, self.run_record_path, self.run_record_sha256,
        )
        if self.expected_route is DiagnosisRoute.SEMANTIC_DIAGNOSIS:
            if any(value is None for value in semantic_fields) or any(
                    value is not None for value in operational_fields):
                raise ValueError("semantic case requires only all semantic fields")
        elif self.expected_route is DiagnosisRoute.OPERATIONAL_ONLY:
            if any(value is not None for value in semantic_fields) or any(
                    value is None for value in operational_fields):
                raise ValueError("operational case requires only all operational fields")
            if self.expected_routing_reason not in {
                DiagnosisRoutingReason.AGENT_COMMAND_FAILED,
                DiagnosisRoutingReason.AGENT_TIMED_OUT,
            }:
                raise ValueError("operational case reason must be command_failed or timed_out")
        else:
            raise ValueError("formal suite does not support unavailable cases")
        return self


class DiagnosisValidationSuite(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    suite_id: ExactString
    case_files: list[DiagnosisValidationSuiteCaseFile] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_files(self) -> Self:
        identities = [(item.case_id, item.path) for item in self.case_files]
        if identities != sorted(identities):
            raise ValueError("suite case files must be in canonical case/path order")
        if len({item.case_id for item in self.case_files}) != len(self.case_files):
            raise ValueError("suite case IDs must be unique")
        if len({item.path for item in self.case_files}) != len(self.case_files):
            raise ValueError("suite case paths must be unique")
        return self


def compute_diagnosis_validation_suite_sha256(
    suite: DiagnosisValidationSuite,
) -> Sha256Hex:
    return hashlib.sha256(canonical_json_bytes(suite.model_dump(mode="json"))).hexdigest()


class DiagnosisValidationFreezeManifest(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    suite_path: ExactString
    suite_sha256: Sha256Hex
    files: list[FrozenValidationFile] = Field(min_length=1)

    _suite_path = field_validator("suite_path")(validate_suite_relative_path)

    @model_validator(mode="after")
    def validate_files(self) -> Self:
        paths = [item.path for item in self.files]
        if paths != sorted(paths):
            raise ValueError("freeze files must be sorted by path")
        if len(paths) != len(set(paths)):
            raise ValueError("freeze file paths must be unique")
        if "freeze-manifest.json" in paths:
            raise ValueError("freeze manifest must not hash itself")
        if self.suite_path not in paths:
            raise ValueError("suite file must be covered by freeze manifest")
        return self


class ContrastiveFairnessReviewCase(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    case_id: ExactString
    locked_gold_sha256: Sha256Hex
    subject_evidence_sha256: Sha256Hex
    blind_bundle_sha256: Sha256Hex
    contrastive_bundle_sha256: Sha256Hex
    peer_run_id: ExactString
    peer_experiment_id: ExactString
    peer_run_index: Annotated[int, Field(strict=True, ge=0)]
    peer_selection_sha256: Sha256Hex
    machine_integrity_passed: bool = Field(strict=True)
    human_fairness_status: Literal["pending", "confirmed", "rejected"]


class ContrastiveFairnessReview(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    suite_id: Literal["diagnosis-validation-v1"] = "diagnosis-validation-v1"
    review_stage: Literal["contrastive_fairness"] = "contrastive_fairness"
    cases: list[ContrastiveFairnessReviewCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_cases(self) -> Self:
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("review case IDs must be unique")
        return self
