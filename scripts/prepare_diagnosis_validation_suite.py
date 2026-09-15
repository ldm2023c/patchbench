"""Prepare, verify, or finalize the Diagnosis Validation V1 two-phase suite."""

import argparse
import hashlib
import json
from pathlib import Path

from patchbench.application.diagnosis_suite import (
    finalize_diagnosis_validation_freeze,
    prepare_contrastive_fairness_review,
    verify_contrastive_fairness_review,
    verify_diagnosis_validation_freeze,
)


DEFAULT_CANDIDATES = Path("fixtures/diagnosis_validation/v1_candidates")
DEFAULT_ROOT = Path("validation/diagnosis/v1")


def _phase_a_summary(root: Path, candidate_root: Path) -> dict[str, object]:
    review = verify_contrastive_fairness_review(root, candidate_root)
    packet = root / "contrastive-fairness-review.md"
    statuses = {case.human_fairness_status for case in review.cases}
    return {
        "case_count": len(review.cases),
        "contrastive_bundle_count": len(list((root / "cases").glob("semantic-*/contrastive-bundle.json"))),
        "fairness_review_sha256": hashlib.sha256(
            (root / "contrastive-fairness-review.json").read_bytes()).hexdigest(),
        "human_packet_sha256": hashlib.sha256(packet.read_bytes()).hexdigest(),
        "statuses": sorted(statuses),
        "freeze_manifest_exists": (root / "freeze-manifest.json").exists(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, nargs="?", default=DEFAULT_ROOT)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--verify-final", action="store_true")
    parser.add_argument("--candidate-root", type=Path, default=DEFAULT_CANDIDATES)
    args = parser.parse_args()

    if args.finalize:
        manifest = finalize_diagnosis_validation_freeze(args.root, args.candidate_root)
        print(json.dumps({
            "file_count": len(manifest.files) + 1,
            "manifest_file_sha256": hashlib.sha256(
                (args.root / "freeze-manifest.json").read_bytes()).hexdigest(),
            "suite_sha256": manifest.suite_sha256,
        }, sort_keys=True))
        return
    if args.verify_final:
        manifest = verify_diagnosis_validation_freeze(args.root, args.candidate_root)
        print(json.dumps({
            "file_count": len(manifest.files) + 1,
            "manifest_file_sha256": hashlib.sha256(
                (args.root / "freeze-manifest.json").read_bytes()).hexdigest(),
            "suite_sha256": manifest.suite_sha256,
        }, sort_keys=True))
        return
    if not args.verify:
        prepare_contrastive_fairness_review(args.root, args.candidate_root)
    print(json.dumps(_phase_a_summary(args.root, args.candidate_root), sort_keys=True))


if __name__ == "__main__":
    main()
