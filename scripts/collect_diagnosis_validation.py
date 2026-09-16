"""Collect explicitly selected successful Diagnosis validation shards."""

import argparse
import json
from pathlib import Path

from patchbench.application.diagnosis_validation_collection import (
    collect_diagnosis_validation_shards,
    parse_case_selection,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validation-root", type=Path, default=Path("validation/diagnosis/v1"))
    parser.add_argument("--candidate-root", type=Path, default=Path("fixtures/diagnosis_validation/v1_candidates"))
    parser.add_argument("--results-root", type=Path, default=Path("results"))
    parser.add_argument("--collection-id", required=True)
    parser.add_argument("--select", action="append", default=[])
    args = parser.parse_args()

    selections = {}
    for raw in args.select:
        case_id, run_id = parse_case_selection(raw)
        if case_id in selections:
            parser.error(f"duplicate case selection: {case_id}")
        selections[case_id] = run_id
    collection = collect_diagnosis_validation_shards(
        validation_root=args.validation_root,
        candidate_root=args.candidate_root,
        results_root=args.results_root,
        collection_id=args.collection_id,
        selections=selections,
    )
    print(json.dumps(collection.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
