"""Run the frozen Diagnosis Validation V1 suite with an explicit provider config."""

import argparse
import json
from pathlib import Path

from patchbench.application.diagnosis_validation_run import run_frozen_diagnosis_validation
from patchbench.domain.diagnosis_execution import DiagnosisExternalLLMPolicy
from patchbench.providers.openai import OpenAIDiagnosisProvider


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validation-root", type=Path, default=Path("validation/diagnosis/v1"))
    parser.add_argument("--candidate-root", type=Path, default=Path("fixtures/diagnosis_validation/v1_candidates"))
    parser.add_argument("--results-root", type=Path, default=Path("results"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", required=True)
    parser.add_argument("--max-output-tokens", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--max-provider-input-bytes", type=int, required=True)
    parser.add_argument("--case-id", action="append", dest="case_ids")
    args = parser.parse_args()

    provider = OpenAIDiagnosisProvider(
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        max_output_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout_seconds,
    )
    record = run_frozen_diagnosis_validation(
        validation_root=args.validation_root,
        candidate_root=args.candidate_root,
        results_root=args.results_root,
        run_id=args.run_id,
        provider=provider,
        external_policy=DiagnosisExternalLLMPolicy(
            external_llm_allowed=True,
            max_provider_input_bytes=args.max_provider_input_bytes,
        ),
        selected_case_ids=args.case_ids,
    )
    print(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
