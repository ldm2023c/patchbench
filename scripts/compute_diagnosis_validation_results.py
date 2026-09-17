#!/usr/bin/env python3
"""Compute deterministic final Diagnosis Validation V1 metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from patchbench.application.diagnosis_validation_results import compute_diagnosis_validation_results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation-root", type=Path, default=Path("validation/diagnosis/v1"))
    parser.add_argument("--candidate-root", type=Path, default=Path("fixtures/diagnosis_validation/v1_candidates"))
    parser.add_argument("--results-root", type=Path, default=Path("results"))
    parser.add_argument("--semantic-score-id", required=True)
    parser.add_argument("--result-id", required=True)
    args = parser.parse_args()
    result = compute_diagnosis_validation_results(
        validation_root=args.validation_root,
        candidate_root=args.candidate_root,
        results_root=args.results_root,
        semantic_score_id=args.semantic_score_id,
        result_id=args.result_id,
    )
    print(json.dumps({
        "result_id": result.result_id,
        "result_sha256": result.result_sha256,
        "semantic_score_id": result.semantic_score_id,
        "semantic_pair_count": result.semantic_comparison.pair_count,
        "operational_case_count": result.operational_aggregate.case_count,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
