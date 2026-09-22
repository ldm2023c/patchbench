"""Run one frozen PatchBench V1.3 calibration batch."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from patchbench.application.v13_calibration import (
    CalibrationIntegrityError,
    run_v13_calibration_batch,
)
from patchbench.domain import CalibrationBatchStatus
from patchbench.sandbox.docker import DockerSandbox


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--previous-batch-id")
    parser.add_argument("--remediation")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--results-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    arguments = parser.parse_args()
    try:
        batch = run_v13_calibration_batch(
            batch_id=arguments.batch_id,
            project_root=arguments.project_root,
            results_namespace=arguments.results_root,
            workspace_root=arguments.workspace_root,
            previous_batch_id=arguments.previous_batch_id,
            remediation=arguments.remediation,
            sandbox=DockerSandbox(),
        )
    except CalibrationIntegrityError as error:
        raise SystemExit(f"Calibration failed: {error}") from None
    except Exception:
        raise SystemExit("Calibration failed: internal harness error") from None
    evidence = (
        (arguments.results_root or arguments.project_root / "results/v1.3-calibration")
        / arguments.batch_id
    )
    print(f"batch_id={batch.batch_id}")
    print(f"status={batch.status.value}")
    print(f"evidence={evidence}")
    if batch.status is not CalibrationBatchStatus.ACCEPTED:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
