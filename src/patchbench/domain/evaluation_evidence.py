"""Canonical log rendering and conservative, pure unittest evidence extraction."""

import hashlib
import math
import re

from patchbench.domain.models import (
    EvaluationCaseEvidence, EvaluationEvidence, EvaluationResult,
)
from patchbench.domain.evidence_errors import EvidenceParsingError


def render_evaluation_log(
    evaluation_result: EvaluationResult, evaluation_command: str,
) -> str:
    """Render the existing Run/Replay artifact format without normalization."""
    return (
        f"Command: {evaluation_command}\n"
        f"Exit code: {evaluation_result.exit_code}\n"
        f"Duration seconds: {evaluation_result.duration_seconds:.6f}\n\n"
        f"STDOUT:\n{evaluation_result.stdout}\n"
        f"STDERR:\n{evaluation_result.stderr}"
    )


_WRAPPER = re.compile(
    r"\ACommand: (?P<command>.+?)\nExit code: (?P<exit>-?\d+)\n"
    r"Duration seconds: (?P<duration>\d+\.\d{6})\n\nSTDOUT:\n(?P<output>.*)\Z",
    re.DOTALL,
)
_SUMMARY = re.compile(
    r"^Ran (?P<count>\d+) tests? in \d+(?:\.\d+)?s\n\n"
    r"(?P<verdict>OK(?: \([^\n]+\))?|FAILED \([^\n]+\))$",
    re.MULTILINE,
)
_COUNTS = {"failures", "errors", "skipped", "expected failures", "unexpected successes"}


def _unittest(stdout: str, stderr: str):
    # Multiple summaries are ambiguous (for example several subprocess suites).
    candidates = [(stream, match) for stream in (stdout, stderr)
                  for match in _SUMMARY.finditer(stream)]
    if len(candidates) != 1:
        return None
    stream, match = candidates[0]
    verdict = match["verdict"]
    counts = {}
    if "(" in verdict:
        for entry in verdict.split("(", 1)[1][:-1].split(", "):
            item = re.fullmatch(r"([a-z ]+)=(\d+)", entry)
            if item is None or item[1] not in _COUNTS or item[1] in counts:
                return None
            counts[item[1]] = int(item[2])
    cases = [EvaluationCaseEvidence(name=m[2], outcome=m[1].lower())
             for m in re.finditer(r"^(FAIL|ERROR): (.+)$", stdout + "\n" + stderr, re.MULTILINE)]
    if verdict.startswith("OK"):
        if cases or counts.get("failures", 0) or counts.get("errors", 0):
            return None
        return int(match["count"]), 0, 0, []
    return int(match["count"]), counts.get("failures", 0), counts.get("errors", 0), cases


def summarize_evaluation_log(test_log: str) -> EvaluationEvidence:
    """Parse wrapper facts first; unknown evaluator output stays unknown."""
    match = _WRAPPER.fullmatch(test_log)
    if (match is None or not match["command"].strip()
            or len(re.findall(r"(?=\nSTDERR:\n)", match["output"])) != 1):
        raise EvidenceParsingError("Malformed or ambiguous canonical evaluation log")
    stdout, stderr = match["output"].split("\nSTDERR:\n")
    duration = float(match["duration"])
    if not math.isfinite(duration):
        raise EvidenceParsingError("Invalid canonical duration")
    facts = _unittest(stdout, stderr)
    return EvaluationEvidence(
        test_log_sha256=hashlib.sha256(test_log.encode("utf-8")).hexdigest(),
        exit_code=int(match["exit"]), passed=int(match["exit"]) == 0,
        duration_seconds=duration,
        framework="unittest" if facts is not None else "unknown",
        tests_run=facts[0] if facts else None,
        failure_count=facts[1] if facts else None,
        error_count=facts[2] if facts else None,
        failing_cases=facts[3] if facts else [],
        output_tail=[line for line in test_log.split("\n") if line.strip()][-20:],
    )
