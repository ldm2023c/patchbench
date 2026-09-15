"""Build or verify the Diagnosis Validation V1 pre-Contrastive Gold lock."""

import argparse
import hashlib
import json
from pathlib import Path

from patchbench.application.diagnosis_gold_lock import (
    build_diagnosis_gold_lock,
    verify_diagnosis_gold_lock,
)


DEFAULT_CANDIDATES = Path("fixtures/diagnosis_validation/v1_candidates")
DEFAULT_GOLD = Path("fixtures/diagnosis_validation/v1_human_gold_drafts")
DEFAULT_AUTHORING_RECORD = DEFAULT_GOLD / "human-gold-authoring-record.md"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    suite = (verify_diagnosis_gold_lock(args.output) if args.verify else
             build_diagnosis_gold_lock(
                 DEFAULT_CANDIDATES, DEFAULT_GOLD, DEFAULT_AUTHORING_RECORD, args.output))
    manifest = args.output / "gold-lock-manifest.json"
    print(json.dumps({
        "case_count": len(suite.cases),
        "manifest_file_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "suite_id": suite.suite_id,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
