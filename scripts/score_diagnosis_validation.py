#!/usr/bin/env python3
"""Prepare or finalize deterministic Diagnosis Validation semantic scoring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from patchbench.application.diagnosis_validation_scoring import (
    finalize_diagnosis_validation_scoring,
    prepare_diagnosis_validation_scoring,
)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--validation-root", type=Path, default=Path("validation/diagnosis/v1"))
    parser.add_argument("--candidate-root", type=Path, default=Path("fixtures/diagnosis_validation/v1_candidates"))
    parser.add_argument("--results-root", type=Path, default=Path("results"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    _common(prepare)
    prepare.add_argument("--collection-id", required=True)
    prepare.add_argument("--preparation-id", required=True)

    finalize = sub.add_parser("finalize")
    _common(finalize)
    finalize.add_argument("--preparation-id", required=True)
    finalize.add_argument("--review-file", type=Path, required=True)
    finalize.add_argument("--score-id", required=True)

    args = parser.parse_args()
    if args.command == "prepare":
        preparation, packet = prepare_diagnosis_validation_scoring(
            validation_root=args.validation_root,
            candidate_root=args.candidate_root,
            results_root=args.results_root,
            collection_id=args.collection_id,
            preparation_id=args.preparation_id,
        )
        payload = {
            "preparation_id": preparation.preparation_id,
            "preparation_sha256": preparation.preparation_sha256,
            "review_required": len(packet.items),
        }
    else:
        scores = finalize_diagnosis_validation_scoring(
            validation_root=args.validation_root,
            candidate_root=args.candidate_root,
            results_root=args.results_root,
            preparation_id=args.preparation_id,
            review_file=args.review_file,
            score_id=args.score_id,
        )
        payload = {
            "score_id": scores.score_id,
            "score_sha256": scores.score_sha256,
            "score_count": len(scores.scores),
        }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
