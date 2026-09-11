"""Read-only V1.1 freeze preflight; never prepares, cleans or changes refs."""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess

from patchbench.config.task_loader import load_task
from patchbench.domain.provenance import compute_task_fingerprint

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("evidence/v1.1/freeze-manifest.json")
EVALUATOR_COMMIT = "802c4d3dcc09d89400ca306eae253b5ef585d442"
FREEZE_REF = "refs/tags/v1.1-evidence-freeze"
COMMAND = "python -I -S -B .patchbench-eval/runner.py"
TASKS = (
    ("streaming_events", "08a5e4cc280d0da24c59cf86bd751b7d6a5baeaf", "test_eventstream.py"),
    ("request_signing", "b1331d203fa9643a5fdf6cf38e53101ecb56025b", "test_websign.py"),
    ("atomic_batch", "1ee42b7784c8ead2e22281865191f820b6dc86fb", "test_batchstore.py"),
    ("cache_revalidation", "49d6f8f0c2547c5d0a9d45141a0f0e128e8ee3ca", "test_cacheclient.py"),
)
PROTECTED = ["src/patchbench", "fixtures/reliability", *[
    f"tasks/reliability/{name}/task.yaml" for name, _, _ in TASKS
]]
EVALUATOR = {"kind": "frozen_unittest", "protocol_version": 1, "command": COMMAND}
EXECUTION = {"patchbench_invocation": "python -m patchbench.cli", "agent": "codex",
             "model": "gpt-6-astra", "agent_timeout_seconds": 600,
             "evaluation_backend": "docker", "runs_per_task": 8}


class FreezeError(ValueError):
    """The checkout/environment does not satisfy the static freeze contract."""


def require(condition, message):
    if not condition:
        raise FreezeError(message)


def run(*argv: str) -> bytes:
    # Disable optional Git index refreshes and inherited repository overrides.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = subprocess.run(argv, capture_output=True, check=True, timeout=30, env=environment)
    except (OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", b"") or str(error)
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        raise FreezeError(f"Unable to run {' '.join(argv)}: {detail.strip()}") from error
    return result.stdout


def git(root: Path, *args: str) -> bytes:
    return run("git", "-C", str(root), *args)


def text(data: bytes) -> str:
    return data.decode("utf-8").rstrip("\n")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def keys(value, expected, label):
    require(isinstance(value, dict) and set(value) == set(expected), f"Invalid {label} fields")


def fixed(value, expected, label):
    # JSON comparison also rejects bool/float substitutes for fixed integers.
    require(json.dumps(value, sort_keys=True) == json.dumps(expected, sort_keys=True),
            f"Unexpected {label}")


def digest(value, label, prefix=""):
    require(isinstance(value, str) and re.fullmatch(re.escape(prefix) + r"[0-9a-f]{64}", value) is not None,
            f"Invalid {label}")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate manifest field: {key}")
        result[key] = value
    return result


def load_manifest(root: Path = ROOT):
    try:
        manifest = json.loads((root / MANIFEST_PATH).read_bytes(), object_pairs_hook=unique_object)
    except (OSError, ValueError) as error:
        raise FreezeError(f"Unable to load freeze manifest: {error}") from error
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest):
    keys(manifest, ["manifest_version", "suite_id", "freeze_ref", "patchbench_evaluator_commit",
                    "evaluator", "execution", "agent_environment", "docker", "tasks"], "manifest")
    for key, expected in {"manifest_version": 1, "suite_id": "patchbench-v1.1-evidence",
                          "freeze_ref": FREEZE_REF, "patchbench_evaluator_commit": EVALUATOR_COMMIT,
                          "evaluator": EVALUATOR, "execution": EXECUTION}.items():
        fixed(manifest[key], expected, key)
    keys(manifest["agent_environment"], ["codex_version"], "agent_environment")
    version = manifest["agent_environment"]["codex_version"]
    require(isinstance(version, str) and bool(version) and not version.endswith("\n"), "Invalid codex_version")
    docker = manifest["docker"]
    keys(docker, ["reference", "image_id", "repo_digest"], "docker")
    fixed(docker["reference"], "python:3.12-slim", "Docker reference")
    digest(docker["image_id"], "Docker image ID", "sha256:")
    if docker["repo_digest"] is not None:
        require(isinstance(docker["repo_digest"], str) and re.fullmatch(
            r"(?:python|(?:docker\.io/)?library/python)@sha256:[0-9a-f]{64}", docker["repo_digest"]),
            "Invalid Docker RepoDigest")
    require(isinstance(manifest["tasks"], list) and len(manifest["tasks"]) == 4, "Expected four ordered tasks")
    for entry, (name, commit, test) in zip(manifest["tasks"], TASKS):
        keys(entry, ["task_id", "taskspec_path", "taskspec_file_sha256", "task_fingerprint_sha256",
                     "base_commit", "official_files"], "task")
        fixed(entry["task_id"], name, "task order/ID")
        fixed(entry["taskspec_path"], f"tasks/reliability/{name}/task.yaml", "TaskSpec path")
        fixed(entry["base_commit"], commit, f"{name} base commit")
        digest(entry["taskspec_file_sha256"], "TaskSpec byte hash")
        digest(entry["task_fingerprint_sha256"], "task fingerprint")
        require(isinstance(entry["official_files"], list) and len(entry["official_files"]) == 1,
                "Expected one official file per task")
        official = entry["official_files"][0]
        keys(official, ["path", "sha256"], "official file")
        fixed(official["path"], test, "official test path")
        digest(official["sha256"], "official test hash")


def verify_semantics(root: Path, manifest):
    validate_manifest(manifest)
    require(text(git(root, "rev-parse", "--show-toplevel")) == str(root.resolve()), "Not the PatchBench checkout root")
    fixed(text(git(root, "rev-parse", "--verify", f"{EVALUATOR_COMMIT}^{{commit}}")),
          EVALUATOR_COMMIT, "evaluator commit")
    changed = git(root, "diff", "--name-only", EVALUATOR_COMMIT, "--", *PROTECTED)
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "--", *PROTECTED)
    require(not changed and not untracked, "Protected semantic paths differ from evaluator commit")
    for entry in manifest["tasks"]:
        path = root / entry["taskspec_path"]
        require(sha(path.read_bytes()) == entry["taskspec_file_sha256"], f"TaskSpec byte hash mismatch: {path}")
        task = load_task(path)
        fixed(task.id, entry["task_id"], "TaskSpec ID")
        fixed(task.repository.base_commit, entry["base_commit"], "TaskSpec base commit")
        fixed(task.evaluation.command, COMMAND, "frozen evaluator command")
        fixed(task.evaluation.timeout_seconds, 120, "evaluation timeout")
        require(task.evaluation.frozen_unittest is not None, "Missing frozen unittest configuration")
        fixed(task.evaluation.frozen_unittest.model_dump(),
              {"version": 1, "test_files": [item["path"] for item in entry["official_files"]]}, "frozen protocol")
        require(compute_task_fingerprint(task, base_commit_used=entry["base_commit"]) == entry["task_fingerprint_sha256"],
                f"Semantic fingerprint mismatch: {task.id}")
        repo = root / "fixtures/reliability/.prepared" / task.id
        require(Path(task.repository.path) == repo, f"Prepared TaskSpec path mismatch: {task.id}")
        require(repo.is_dir() and (repo / ".git").is_dir(),
                f"Prepared repository missing: {repo}. Run python -m scripts.prepare_reliability_fixtures")
        require(text(git(repo, "rev-parse", "--show-toplevel")) == str(repo.resolve()), f"Wrong prepared repository root: {repo}")
        require(text(git(repo, "rev-parse", "HEAD")) == entry["base_commit"], f"Prepared HEAD mismatch: {task.id}")
        require(not git(repo, "status", "--porcelain", "--untracked-files=all"), f"Prepared repository dirty: {task.id}")
        for official in entry["official_files"]:
            blob = git(repo, "show", f'{entry["base_commit"]}:{official["path"]}')
            require(sha(blob) == official["sha256"], f"Official test blob hash mismatch: {task.id}")


def verify_environment(root: Path, manifest):
    expected = (root / "src/patchbench").resolve()
    for name in ("patchbench", "patchbench.cli", "patchbench.domain.provenance"):
        module = importlib.import_module(name)
        origin = getattr(module, "__file__", None)
        require(origin is not None and Path(origin).resolve().is_relative_to(expected),
                f"Imported {name} is not from this checkout's src/patchbench")
    try:
        images = json.loads(run("docker", "image", "inspect", manifest["docker"]["reference"]))
    except ValueError as error:
        raise FreezeError(f"Invalid Docker inspection output: {error}") from error
    require(isinstance(images, list) and len(images) == 1, "Expected one Docker image")
    image = images[0]
    require(image.get("Id") == manifest["docker"]["image_id"], "Docker image ID mismatch")
    pinned_digest = manifest["docker"]["repo_digest"]
    require(pinned_digest is None or pinned_digest in (image.get("RepoDigests") or []), "Docker RepoDigest mismatch")
    version = run("codex", "--version").decode("utf-8").removesuffix("\n")
    require(version == manifest["agent_environment"]["codex_version"], "Codex CLI version mismatch")
    require(not run("docker", "ps", "-q", "--filter", "label=patchbench.sandbox=true").strip(),
            "Active PatchBench Docker sandbox container exists")
    workspaces = root / ".workspaces"
    require(not workspaces.exists() or (workspaces.is_dir() and not any(workspaces.iterdir())),
            "Residual child or invalid path under .workspaces")


def verify_strict(root: Path, manifest):
    try:
        freeze_commit = text(git(root, "rev-parse", "--verify", f'{manifest["freeze_ref"]}^{{commit}}'))
    except FreezeError as error:
        raise FreezeError(f'Freeze ref {manifest["freeze_ref"]} is not available.') from error
    require(text(git(root, "rev-parse", "HEAD")) == freeze_commit, "Current HEAD does not equal freeze_ref commit")
    require(not git(root, "status", "--porcelain", "--untracked-files=all"), "Root Git working tree is not clean")
    require(not git(root, "diff", "--name-only", f"{EVALUATOR_COMMIT}..HEAD", "--", *PROTECTED),
            "Protected semantic paths changed after evaluator commit")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static", action="store_true", help="Allow uncommitted review files and an absent freeze tag")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest()
        verify_semantics(ROOT, manifest)
        verify_environment(ROOT, manifest)
        if not args.static:
            verify_strict(ROOT, manifest)
    except (FreezeError, OSError, ValueError) as error:
        print(f"Freeze verification failed: {error}", file=sys.stderr)
        return 1
    print(f"V1.1 freeze verification PASS ({'static' if args.static else 'strict'}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
