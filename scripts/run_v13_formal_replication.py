"""Operate the admission-gated PatchBench V1.3 Replication-01 harness."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from patchbench.application.v13_formal_execution import (
    FormalExecutionIntegrityError,
    FormalExecutionStateError,
)
from patchbench.application.v13_formal_replication_execution import (
    check_replication_study,
    initialize_replication_study,
    replication_study_status,
    retry_replication_slot,
    run_next_replication_attempt,
)
from patchbench.sandbox.docker import DockerSandbox


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--init", action="store_true")
    action.add_argument("--run-next", action="store_true")
    action.add_argument("--retry-slot")
    action.add_argument("--status", action="store_true")
    action.add_argument("--check", action="store_true")
    parser.add_argument("--remediation")
    args = parser.parse_args()
    try:
        if args.init:
            if args.remediation is not None:
                raise FormalExecutionStateError("remediation is valid only with retry")
            ledger = initialize_replication_study(project_root=PROJECT_ROOT)
            print(f"study_status={ledger.status.value}")
        elif args.run_next:
            if args.remediation is not None:
                raise FormalExecutionStateError("remediation is valid only with retry")
            ledger = run_next_replication_attempt(
                project_root=PROJECT_ROOT, sandbox=DockerSandbox()
            )
            print(f"study_status={ledger.status.value}")
        elif args.retry_slot:
            if args.remediation is None:
                raise FormalExecutionStateError("retry requires explicit remediation")
            ledger = retry_replication_slot(
                project_root=PROJECT_ROOT,
                slot_id=args.retry_slot,
                remediation=args.remediation,
                sandbox=DockerSandbox(),
            )
            print(f"study_status={ledger.status.value}")
        elif args.check:
            ledger = check_replication_study(project_root=PROJECT_ROOT)
            print(f"study_status={ledger.status.value}")
        else:
            summary = replication_study_status(project_root=PROJECT_ROOT)
            print(f"study_status={summary.status.value}")
            print(f"terminal_slots={summary.terminal_slots}/108")
            print(f"canonical_slots={summary.canonical_slots}")
            print(
                "unresolved_infrastructure_slots="
                f"{summary.unresolved_infrastructure_slots}"
            )
            print(f"retry_required_slot={summary.retry_required_slot or '-'}")
            print(f"blocked_slot={summary.blocked_slot or '-'}")
            print(f"next_planned_slot={summary.next_planned_slot or '-'}")
    except (FormalExecutionIntegrityError, FormalExecutionStateError) as error:
        raise SystemExit(f"Formal replication execution refused: {error}") from None
    except Exception:
        raise SystemExit(
            "Formal replication execution failed: internal harness error"
        ) from None


if __name__ == "__main__":
    main()
