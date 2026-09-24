"""Preregistered metrics for the frozen PatchBench V1.3 formal study."""

import hashlib
import json
import math
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from patchbench.domain.formal_execution import FormalFailureCategory
from patchbench.domain.formal_study import V13FormalMetricPolicy
from patchbench.domain.models import DomainModel, Sha256Hex


class V13FormalMetric(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    numerator: Annotated[int, Field(strict=True, ge=0)]
    denominator: Annotated[int, Field(strict=True, ge=0)]
    rate: float | None

    @model_validator(mode="after")
    def validate_rate(self) -> Self:
        expected = None if self.denominator == 0 else self.numerator / self.denominator
        if self.numerator > self.denominator:
            raise ValueError("metric numerator cannot exceed denominator")
        if ((expected is None) != (self.rate is None)
                or (expected is not None and not math.isclose(
                    self.rate, expected, rel_tol=0.0, abs_tol=0.0
                ))):
            raise ValueError("metric rate differs from exact counts")
        return self


class V13FormalMetricRow(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    value: str
    end_to_end_reliability: V13FormalMetric
    completed_semantic_repair: V13FormalMetric
    operational_completion: V13FormalMetric


class V13FormalRetryReason(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    failure_category: FormalFailureCategory
    count: Annotated[int, Field(strict=True, ge=1)]


class V13FormalRetryReporting(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slots_requiring_retry: tuple[str, ...]
    retry_reasons: tuple[V13FormalRetryReason, ...]
    slots_resolving_on_retry: tuple[str, ...]
    slots_unresolved_after_retry: tuple[str, ...]


class V13FormalAnalysis(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    analysis_id: Literal["patchbench-v1.3-formal-analysis"]
    formal_evidence_freeze_sha256: Sha256Hex
    formal_preregistration_sha256: Sha256Hex
    design_sha256: Sha256Hex
    metrics_policy: V13FormalMetricPolicy
    overall: V13FormalMetricRow
    by_agent_configuration: tuple[V13FormalMetricRow, ...] = Field(min_length=3, max_length=3)
    by_primary_capability: tuple[V13FormalMetricRow, ...] = Field(min_length=4, max_length=4)
    by_designed_difficulty: tuple[V13FormalMetricRow, ...] = Field(min_length=3, max_length=3)
    by_task: tuple[V13FormalMetricRow, ...] = Field(min_length=12, max_length=12)
    retry_reporting: V13FormalRetryReporting

    @model_validator(mode="after")
    def validate_structure(self) -> Self:
        expected = (
            (self.overall,), 108,
            self.by_agent_configuration, 36,
            self.by_primary_capability, 27,
            self.by_designed_difficulty, 36,
            self.by_task, 9,
        )
        for rows, denominator in zip(expected[::2], expected[1::2], strict=True):
            if any(row.end_to_end_reliability.denominator != denominator
                   or row.operational_completion.denominator != denominator
                   for row in rows):
                raise ValueError("analysis planned denominators differ from frozen design")
        return self


def compute_v13_formal_analysis_sha256(analysis: V13FormalAnalysis) -> str:
    payload = json.dumps(
        analysis.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
