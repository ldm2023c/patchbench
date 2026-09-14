"""Build and verify the draft Diagnosis Validation v1 authoring candidate pool.

This offline controlled-fixture utility never invokes a coding or Diagnosis
provider.  Semantic answers intentionally do not exist in its output.
"""

from contextlib import contextmanager
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import yaml

from patchbench.agents.base import AgentRunStatus
from patchbench.application.diagnosis_evidence import compile_diagnosis_evidence
from patchbench.application.diagnosis_peer import (
    select_contrastive_peer, verify_contrastive_peer_selection,
)
from patchbench.application import evaluation as evaluation_module
from patchbench.config.task_loader import load_task
from patchbench.domain import (
    AgentExecutionMetadata, ArtifactPaths, DiagnosisEvidenceBundle,
    DiagnosisGoldCase, DiagnosisRoute, DiagnosisRoutingReason, DiagnosisSourcePolicy,
    EvaluationResult, ExperimentConfiguration, ExperimentRecord, RunProvenance,
    RunRecord, RunStatus, aggregate_runs, canonical_json_bytes, compute_bundle_sha256,
    compute_task_fingerprint, render_evaluation_log, route_run_diagnosis,
    summarize_evaluation_log, summarize_patch,
)
from patchbench.domain.models import FROZEN_UNITTEST_COMMAND
from patchbench.evaluators import command as command_evaluator_module
from patchbench.repository.git_repository import GitRepositoryManager
from patchbench.storage.filesystem import FilesystemArtifactStore


SCHEMA_VERSION = 1
SEMANTIC_IDS = tuple(f"semantic-{index:02d}" for index in range(1, 16))
OPERATIONAL_IDS = ("operational-01", "operational-02")
ALL_IDS = SEMANTIC_IDS + OPERATIONAL_IDS
BENCHMARK_POLICY = "diagnosis-validation-v1-controlled-candidate"


class CandidateVerificationError(ValueError):
    pass


@contextmanager
def _working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


@contextmanager
def _without_inherited_git_environment():
    inherited = {key: value for key, value in os.environ.items() if key.startswith("GIT_")}
    for key in inherited:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        os.environ.update(inherited)


def _json_bytes(value) -> bytes:
    raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _write_files(root: Path, files: dict[str, str]) -> None:
    for name, content in sorted(files.items()):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def _git(repository: Path, *arguments: str) -> str:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "PatchBench Fixture", "GIT_AUTHOR_EMAIL": "fixture@patchbench.invalid",
        "GIT_COMMITTER_NAME": "PatchBench Fixture", "GIT_COMMITTER_EMAIL": "fixture@patchbench.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
    })
    result = subprocess.run(["git", "-C", str(repository), *arguments], check=True,
                            capture_output=True, text=True, env=environment)
    return result.stdout.strip()


def _semantic_specs():
    """Controlled source states. No scoring labels or Human Gold are encoded."""
    return [
      ({"src/access.py":"def allowed(age, active):\n    return age >= 18\n"},
       {"src/access.py":"def allowed(age, active):\n    return age >= 18 or active\n"},
       {"src/access.py":"def allowed(age, active):\n    return age >= 18 and active\n"},
       "Require both adult age and an active account.",
       "from src.access import allowed\nimport unittest\nclass Contract(unittest.TestCase):\n def test_access(self):\n  self.assertTrue(allowed(20, True)); self.assertFalse(allowed(20, False)); self.assertFalse(allowed(16, True))\n"),
      ({"src/limits.py":"def cap(value):\n    return min(value, 100)\n"},
       {"src/limits.py":"def cap(value):\n    return max(value, 80)\n"},
       {"src/limits.py":"def cap(value):\n    return min(value, 80)\n"},
       "Cap values at the revised upper boundary of 80.",
       "from src.limits import cap\nimport unittest\nclass Contract(unittest.TestCase):\n def test_cap(self):\n  self.assertEqual(cap(20),20); self.assertEqual(cap(90),80)\n"),
      ({"src/parser.py":"def normalize(value):\n    return value.upper()\n","src/api.py":"from .parser import normalize\ndef submit(value):\n    return normalize(value)\n"},
       {"src/parser.py":"def normalize(value):\n    return value.lower()\n","src/api.py":"from .parser import normalize\ndef submit(value):\n    return normalize(value).upper()\n"},
       {"src/parser.py":"def normalize(value):\n    return value.lower()\n","src/api.py":"from .parser import normalize\ndef submit(value):\n    return normalize(value)\n"},
       "Return normalized lowercase values through the public submit API.",
       "from src.api import submit\nimport unittest\nclass Contract(unittest.TestCase):\n def test_submit(self): self.assertEqual(submit('MiXeD'),'mixed')\n"),
      ({"src/registry.py":"SUPPORTED=('txt',)\nHANDLERS={'txt':'text'}\ndef lookup(kind):\n return HANDLERS[kind] if kind in SUPPORTED else None\n"},
       {"src/registry.py":"SUPPORTED=('txt',)\nHANDLERS={'txt':'text','png':'image'}\ndef lookup(kind):\n return HANDLERS[kind] if kind in SUPPORTED else None\n"},
       {"src/registry.py":"SUPPORTED=('txt','png')\nHANDLERS={'txt':'text','png':'image'}\ndef lookup(kind):\n return HANDLERS[kind] if kind in SUPPORTED else None\n"},
       "Support the png kind through the registry lookup.",
       "from src.registry import lookup\nimport unittest\nclass Contract(unittest.TestCase):\n def test_png(self): self.assertEqual(lookup('png'),'image')\n"),
      ({"src/config.py":"def timeout(data):\n return data.get('timeout',30)\n"},
       {"src/config.py":"def timeout(data):\n return int(data.get('timeout',30))\n"},
       {"src/config.py":"def timeout(data):\n value=data.get('timeout')\n return 30 if value is None else int(value)\n"},
       "Accept explicit null timeout as the documented default.",
       "from src.config import timeout\nimport unittest\nclass Contract(unittest.TestCase):\n def test_timeout(self): self.assertEqual(timeout({'timeout':None}),30); self.assertEqual(timeout({'timeout':'8'}),8)\n"),
      ({"src/identity.py":"def identifier(value):\n return str(int(value))\n"},
       {"src/identity.py":"def identifier(value):\n if isinstance(value,int): return str(value)\n return str(int(value))\n"},
       {"src/identity.py":"def identifier(value):\n return str(value)\n"},
       "Accept numeric and textual identifiers while preserving textual form.",
       "from src.identity import identifier\nimport unittest\nclass Contract(unittest.TestCase):\n def test_forms(self): self.assertEqual(identifier(7),'7'); self.assertEqual(identifier('007'),'007')\n"),
      ({"src/store.py":"class Store:\n def __init__(self): self.data={'old':1}; self.names={'old'}\n def rename(self,old,new): pass\n"},
       {"src/store.py":"class Store:\n def __init__(self): self.data={'old':1}; self.names={'old'}\n def rename(self,old,new): self.data[new]=self.data.pop(old)\n"},
       {"src/store.py":"class Store:\n def __init__(self): self.data={'old':1}; self.names={'old'}\n def rename(self,old,new):\n  self.data[new]=self.data.pop(old); self.names.remove(old); self.names.add(new)\n"},
       "Keep all Store views consistent when renaming an entry.",
       "from src.store import Store\nimport unittest\nclass Contract(unittest.TestCase):\n def test_rename(self):\n  s=Store(); s.rename('old','new'); self.assertEqual(s.data,{'new':1}); self.assertEqual(s.names,{'new'})\n"),
      ({"src/queue.py":"class Queue:\n def __init__(self): self.items=[]; self.count=0; self.version=0\n def add(self,item): pass\n"},
       {"src/queue.py":"class Queue:\n def __init__(self): self.items=[]; self.count=0; self.version=0\n def add(self,item): self.items.append(item)\n"},
       {"src/queue.py":"class Queue:\n def __init__(self): self.items=[]; self.count=0; self.version=0\n def add(self,item): self.items.append(item); self.count+=1; self.version+=1\n"},
       "Update the queue and its observable metadata atomically.",
       "from src.queue import Queue\nimport unittest\nclass Contract(unittest.TestCase):\n def test_add(self):\n  q=Queue(); q.add('x'); self.assertEqual((q.items,q.count,q.version),(['x'],1,1))\n"),
      ({"src/message.py":"def render(name):\n return 'Hello '+name+'.'\n"},
       {"src/message.py":"def render(name, excited=True):\n return ('Hello '+name)+('!' if excited else '.')\n"},
       {"src/message.py":"def render(name, excited=False):\n return ('Hello '+name)+('!' if excited else '.')\n"},
       "Add opt-in excited rendering while retaining legacy default output.",
       "from src.message import render\nimport unittest\nclass Contract(unittest.TestCase):\n def test_render(self): self.assertEqual(render('Ada'),'Hello Ada.'); self.assertEqual(render('Ada',True),'Hello Ada!')\n"),
      ({"src/threshold.py":"def accepted(value):\n return value > 0\n"},
       {"src/threshold.py":"def accepted(value):\n return value >= -1\n"},
       {"src/threshold.py":"def accepted(value):\n return value >= 0\n"},
       "Accept zero without accepting negative values.",
       "from src.threshold import accepted\nimport unittest\nclass Contract(unittest.TestCase):\n def test_boundary(self): self.assertTrue(accepted(0)); self.assertFalse(accepted(-1))\n"),
      ({"src/pipeline.py":"def parse(v): return v.strip()\ndef emit(v): return v.lower()\ndef process(v): return emit(parse(v))\n"},
       {"src/pipeline.py":"def parse(v): return v.strip('!')\ndef emit(v): return v.upper()\ndef process(v): return emit(parse(v))\n"},
       {"src/pipeline.py":"def parse(v): return v.strip()\ndef emit(v): return v.lower()\ndef process(v): return emit(parse(v))\n"},
       "Preserve the documented pipeline output for padded mixed-case input.",
       "from src.pipeline import process\nimport unittest\nclass Contract(unittest.TestCase):\n def test_process(self): self.assertEqual(process(' Mixed '),'mixed')\n"),
      ({"src/policy.py":"MODE='safe'\ndef mode(): return MODE\n","src/runner.py":"from .policy import mode\ndef execute(): return mode()\n"},
       {"src/policy.py":"MODE='fast'\ndef mode(): return MODE\n","src/runner.py":"from .policy import mode\ndef execute(): return mode()+'-cached'\n"},
       {"src/policy.py":"MODE='safe'\ndef mode(): return MODE\n","src/runner.py":"from .policy import mode\ndef execute(): return mode()\n"},
       "Keep execution on the configured safe mode.",
       "from src.runner import execute\nimport unittest\nclass Contract(unittest.TestCase):\n def test_execute(self): self.assertEqual(execute(),'safe')\n"),
      ({"src/select.py":"def normalize(v): return v.strip()\ndef keep(v): return bool(v)\ndef select(values): return [normalize(v) for v in values if keep(normalize(v))]\n"},
       {"src/select.py":"def normalize(v): return v.rstrip()\ndef keep(v): return len(v)>1\ndef select(values): return [normalize(v) for v in values if keep(normalize(v))]\n"},
       {"src/select.py":"def normalize(v): return v.strip()\ndef keep(v): return bool(v)\ndef select(values): return [normalize(v) for v in values if keep(normalize(v))]\n"},
       "Select nonempty normalized values according to the public contract.",
       "from src.select import select\nimport unittest\nclass Contract(unittest.TestCase):\n def test_select(self): self.assertEqual(select([' a ',' ','bc']),['a','bc'])\n"),
      ({"src/codes.py":"CODES={'a':1}\ndef code(v): return CODES.get(v)\n","src/adapter.py":"from .codes import code\ndef adapt(v): return code(v)\n"},
       {"src/codes.py":"CODES={'a':1,'b':2}\ndef code(v): return CODES.get(v)\n","src/adapter.py":"from .codes import code\ndef adapt(v): return code(v)+1 if code(v) else None\n"},
       {"src/codes.py":"CODES={'a':1,'b':2}\ndef code(v): return CODES.get(v)\n","src/adapter.py":"from .codes import code\ndef adapt(v): return code(v)\n"},
       "Expose registered code values unchanged through the adapter.",
       "from src.adapter import adapt\nimport unittest\nclass Contract(unittest.TestCase):\n def test_adapt(self): self.assertEqual((adapt('a'),adapt('b')),(1,2))\n"),
      ({"src/cache.py":"DATA={'x':1}; CACHE={}\ndef put(k,v): DATA[k]=v\ndef get(k): return CACHE.get(k,DATA.get(k))\n"},
       {"src/cache.py":"DATA={'x':1}; CACHE={'x':1}\ndef put(k,v): DATA[k]=v\ndef get(k): return CACHE.get(k,DATA.get(k))\n"},
       {"src/cache.py":"DATA={'x':1}; CACHE={}\ndef put(k,v): DATA[k]=v; CACHE[k]=v\ndef get(k): return CACHE.get(k,DATA.get(k))\n"},
       "Return the latest stored value through the cache-backed interface.",
       "from src.cache import put,get\nimport unittest\nclass Contract(unittest.TestCase):\n def test_latest(self): put('x',2); self.assertEqual(get('x'),2)\n"),
    ]


def _init_repository(case_root: Path, base_files: dict[str, str], test_text: str) -> str:
    repository = case_root / "repository"
    repository.mkdir(parents=True)
    stable_test = "import unittest\nunittest.runner.time.perf_counter = lambda: 0.0\n" + test_text
    _write_files(repository, base_files | {"test_contract.py": stable_test, "src/__init__.py": ""})
    _git(repository, "init", "-q")
    _git(repository, "config", "core.autocrlf", "false")
    _git(repository, "add", "-A")
    _git(repository, "-c", "commit.gpgsign=false", "commit", "-qm", "controlled base")
    return _git(repository, "rev-parse", "HEAD")


def _task_document(case_id: str, base_commit: str, prompt: str) -> dict:
    return {"schema_version": 1, "id": case_id,
        "repository": {"type": "local", "path": "repository", "base_commit": base_commit},
        "task": {"prompt": prompt},
        "evaluation": {"command": FROZEN_UNITTEST_COMMAND, "timeout_seconds": 30,
                       "frozen_unittest": {"version": 1, "test_files": ["test_contract.py"]}},
        "metadata": {"language": "python"}}


def _relative_artifacts(run_id: str) -> ArtifactPaths:
    root = Path("results") / run_id
    return ArtifactPaths(directory=root, metadata=root / "metadata.json", prompt=root / "prompt.txt",
        agent_log=root / "agent.log", agent_stderr_log=root / "agent.stderr.log",
        test_log=root / "test.log", patch=root / "patch.diff")


def _persist_run(case_root: Path, *, run_id: str, task, commit: str, patch: str,
                 evaluation: EvaluationResult) -> RunRecord:
    artifacts = _relative_artifacts(run_id)
    log = render_evaluation_log(evaluation, task.evaluation.command)
    record = RunRecord(run_id=run_id, task_id=task.id,
        status=RunStatus.PASSED if evaluation.passed else RunStatus.FAILED,
        evaluation_passed=evaluation.passed, duration_seconds=0.0,
        agent=AgentExecutionMetadata(name="controlled-fixture", backend="host",
            status=AgentRunStatus.COMPLETED, exit_code=0, duration_seconds=0.0,
            timeout_seconds=30.0, requested_model=None), artifacts=artifacts,
        provenance=RunProvenance(base_commit_used=commit,
            task_fingerprint_sha256=compute_task_fingerprint(task, base_commit_used=commit),
            evaluation_command=task.evaluation.command, evaluation_timeout_seconds=30,
            evaluation_backend="host"), patch_summary=summarize_patch(patch),
        evaluation_evidence=summarize_evaluation_log(log))
    directory = case_root / "results" / run_id
    directory.mkdir(parents=True)
    _write_json(directory / "metadata.json", record)
    (directory / "prompt.txt").write_text(task.task.prompt, encoding="utf-8")
    (directory / "agent.log").write_text("controlled fixture execution\n", encoding="utf-8")
    (directory / "agent.stderr.log").write_text("", encoding="utf-8")
    (directory / "test.log").write_text(log, encoding="utf-8")
    (directory / "patch.diff").write_text(patch, encoding="utf-8")
    return record


def _patch_and_evaluate(manager, task, run_id: str, changes: dict[str, str]):
    with manager.workspace(task.repository, run_id) as workspace:
        _write_files(workspace.path, changes)
        patch = manager.capture_diff(workspace)
        old_path = os.environ.get("PATH")
        os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + (old_path or "")
        old_uuid4 = evaluation_module.uuid4
        old_perf_counter = command_evaluator_module.perf_counter
        evaluation_module.uuid4 = lambda: SimpleNamespace(hex=run_id)
        command_evaluator_module.perf_counter = lambda: 0.0
        try:
            evaluation = evaluation_module.evaluate_patch(manager, workspace, task.evaluation, patch)
        finally:
            evaluation_module.uuid4 = old_uuid4
            command_evaluator_module.perf_counter = old_perf_counter
            if old_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = old_path
    return patch, evaluation


def _build_semantic(case_root: Path, case_id: str, spec) -> None:
    base, subject_changes, peer_changes, prompt, test_text = spec
    stable_test = "import unittest\nunittest.runner.time.perf_counter = lambda: 0.0\n" + test_text
    _write_files(case_root / "base", base | {"test_contract.py": stable_test, "src/__init__.py": ""})
    commit = _init_repository(case_root, base, test_text)
    task_path = case_root / "task.yaml"
    task_path.write_text(yaml.safe_dump(_task_document(case_id, commit, prompt), sort_keys=True), encoding="utf-8")
    manager = GitRepositoryManager(case_root / "workspaces")
    with _without_inherited_git_environment(), _working_directory(case_root):
        task = load_task(Path("task.yaml"))
        subject_patch, subject_result = _patch_and_evaluate(manager, task, "subject-work", subject_changes)
        peer_patch, peer_result = _patch_and_evaluate(manager, task, "peer-work", peer_changes)
        if subject_result.passed or not peer_result.passed:
            raise CandidateVerificationError(f"{case_id} controlled outcomes are not FAIL/PASS")
        subject_id, peer_id, experiment_id = f"{case_id}-subject", f"{case_id}-peer", f"{case_id}-peers"
        subject = _persist_run(case_root, run_id=subject_id, task=task, commit=commit,
                               patch=subject_patch, evaluation=subject_result)
        peer = _persist_run(case_root, run_id=peer_id, task=task, commit=commit,
                            patch=peer_patch, evaluation=peer_result)
        experiment = ExperimentRecord(experiment_id=experiment_id, task_id=case_id,
            requested_runs=1, run_ids=[peer_id],
            configuration=ExperimentConfiguration(agent_name="controlled-fixture",
                requested_model=None, agent_timeout_seconds=30.0, evaluation_backend="host"),
            aggregate=aggregate_runs([peer]), duration_seconds=0.0)
        _write_json(case_root / "results/experiments" / experiment_id / "metadata.json", experiment)
        task_sha = hashlib.sha256(task_path.read_bytes()).hexdigest()
        benchmark_sha = hashlib.sha256(canonical_json_bytes(
            {"candidate_id": case_id, "policy": BENCHMARK_POLICY})).hexdigest()
        store = FilesystemArtifactStore(case_root / "results")
        bundle = compile_diagnosis_evidence(task_path, subject_id,
            benchmark_definition_sha256=benchmark_sha,
            expected_task_contract_sha256=task_sha,
            source_policy=DiagnosisSourcePolicy(production_roots=["src"]),
            max_bundle_json_bytes=1_000_000, artifact_store=store, repository_manager=manager)
        selection = select_contrastive_peer(subject_id, experiment_id, artifact_store=store)
        verify_contrastive_peer_selection(selection, artifact_store=store)
    _write_json(case_root / "blind-bundle.json", bundle)
    _write_json(case_root / "candidate.json", {"schema_version": 1, "candidate_id": case_id,
        "expected_route": DiagnosisRoute.SEMANTIC_DIAGNOSIS.value,
        "subject_run_id": subject.run_id, "blind_bundle_sha256": bundle.bundle_sha256,
        "subject_evidence_sha256": _subject_sha(bundle), "peer_experiment_id": experiment_id,
        "peer_run_id": peer.run_id})
    shutil.rmtree(case_root / "repository")
    if (case_root / "workspaces").exists(): shutil.rmtree(case_root / "workspaces")


def _subject_sha(bundle):
    from patchbench.application.diagnosis_validation import compute_subject_evidence_sha256
    return compute_subject_evidence_sha256(bundle)


def _build_operational(case_root: Path, case_id: str, status: AgentRunStatus) -> None:
    artifacts = _relative_artifacts(f"{case_id}-run")
    run = RunRecord(run_id=f"{case_id}-run", task_id=case_id, status=RunStatus.FAILED,
        evaluation_passed=False, duration_seconds=0.0,
        agent=AgentExecutionMetadata(name="controlled-fixture", backend="host", status=status,
            exit_code=7 if status is AgentRunStatus.COMMAND_FAILED else None,
            duration_seconds=0.0, timeout_seconds=30.0), artifacts=artifacts)
    gold = DiagnosisGoldCase(case_id=case_id, expected_route=DiagnosisRoute.OPERATIONAL_ONLY)
    _write_json(case_root / "run-record.json", run)
    _write_json(case_root / "route-gold.json", gold)
    _write_json(case_root / "candidate.json", {"schema_version": 1, "candidate_id": case_id,
        "expected_route": DiagnosisRoute.OPERATIONAL_ONLY.value,
        "expected_routing_reason": route_run_diagnosis(run).reason.value,
        "run_id": run.run_id})


def prepare_diagnosis_validation_candidates(output_root: Path) -> None:
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    (output_root / "README.md").write_text(
        "# Diagnosis Validation v1 candidates\n\n"
        "Draft human-authoring inputs. This directory is not a frozen validation suite.\n"
        "Semantic candidates contain Blind evidence only and intentionally contain no Human Gold.\n",
        encoding="utf-8")
    inventory = [{"candidate_id": value, "expected_route":
                  (DiagnosisRoute.SEMANTIC_DIAGNOSIS.value if value in SEMANTIC_IDS
                   else DiagnosisRoute.OPERATIONAL_ONLY.value)} for value in ALL_IDS]
    _write_json(output_root / "candidate-inventory.json",
                {"schema_version": 1, "status": "draft", "candidates": inventory})
    stage_root = Path("/tmp/patchbench-diagnosis-v1-candidate-stage")
    shutil.rmtree(stage_root, ignore_errors=True)
    stage_root.mkdir()
    for case_id, spec in zip(SEMANTIC_IDS, _semantic_specs(), strict=True):
        staged_case = stage_root / case_id; staged_case.mkdir()
        _build_semantic(staged_case, case_id, spec)
        shutil.copytree(staged_case, output_root / case_id)
    for case_id, status in zip(OPERATIONAL_IDS,
        (AgentRunStatus.COMMAND_FAILED, AgentRunStatus.TIMED_OUT), strict=True):
        case_root = output_root / case_id; case_root.mkdir()
        _build_operational(case_root, case_id, status)
    shutil.rmtree(stage_root)
    verify_diagnosis_validation_candidates(output_root)


def _restore_repository(case_root: Path) -> None:
    shutil.copytree(case_root / "base", case_root / "repository")
    commit = _init_existing_repository(case_root / "repository")
    task = load_task(case_root / "task.yaml")
    if task.repository.base_commit != commit:
        raise CandidateVerificationError(f"{case_root.name} base commit differs")


def _init_existing_repository(repository: Path) -> str:
    _git(repository, "init", "-q")
    _git(repository, "config", "core.autocrlf", "false")
    _git(repository, "add", "-A")
    _git(repository, "-c", "commit.gpgsign=false", "commit", "-qm", "controlled base")
    return _git(repository, "rev-parse", "HEAD")


def verify_diagnosis_validation_candidates(root: Path) -> dict[str, str]:
    root = Path(root).resolve()
    try:
        inventory = json.loads((root / "candidate-inventory.json").read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateVerificationError("invalid candidate inventory") from error
    expected_inventory = [{"candidate_id": value, "expected_route":
        (DiagnosisRoute.SEMANTIC_DIAGNOSIS.value if value in SEMANTIC_IDS
         else DiagnosisRoute.OPERATIONAL_ONLY.value)} for value in ALL_IDS]
    if inventory != {"schema_version": 1, "status": "draft", "candidates": expected_inventory}:
        raise CandidateVerificationError("candidate inventory differs from the exact draft pool")
    if {path.name for path in root.iterdir() if path.is_dir()} != set(ALL_IDS):
        raise CandidateVerificationError("candidate directory set differs")
    identities = {}
    forbidden_keys = {"preferred_family", "acceptable_families", "should_abstain",
        "required_evidence", "forbidden_claims", "intended_construction_family"}
    with TemporaryDirectory(prefix="patchbench-diagnosis-candidate-verify-") as temporary:
        stage_root = Path(temporary)
        for case_id in SEMANTIC_IDS:
            source = root / case_id
            names = {path.name.lower() for path in source.iterdir()}
            if any("contrastive" in name or name in {"gold.json", "semantic-gold.json"} for name in names):
                raise CandidateVerificationError(f"{case_id} exposes post-authoring evidence")
            metadata = json.loads((source / "candidate.json").read_bytes())
            if forbidden_keys.intersection(metadata):
                raise CandidateVerificationError(f"{case_id} metadata contains semantic answer fields")
            case_root = stage_root / case_id
            shutil.copytree(source, case_root)
            _restore_repository(case_root)
            store = FilesystemArtifactStore(case_root / "results")
            manager = GitRepositoryManager(case_root / "workspaces")
            with _without_inherited_git_environment(), _working_directory(case_root):
                task_path = Path("task.yaml")
                bundle = compile_diagnosis_evidence(task_path, metadata["subject_run_id"],
                    benchmark_definition_sha256=hashlib.sha256(canonical_json_bytes(
                        {"candidate_id": case_id, "policy": BENCHMARK_POLICY})).hexdigest(),
                    expected_task_contract_sha256=hashlib.sha256(task_path.read_bytes()).hexdigest(),
                    source_policy=DiagnosisSourcePolicy(production_roots=["src"]),
                    max_bundle_json_bytes=1_000_000, artifact_store=store,
                    repository_manager=manager)
                persisted = DiagnosisEvidenceBundle.model_validate_json(
                    (source / "blind-bundle.json").read_bytes())
                if bundle != persisted or compute_bundle_sha256(persisted) != persisted.bundle_sha256:
                    raise CandidateVerificationError(f"{case_id} Blind Bundle differs from D2 recompilation")
                if (persisted.mode.value != "blind" or persisted.official_evaluation_passed
                        or persisted.agent_status is not AgentRunStatus.COMPLETED
                        or any(item.owner.value == "peer" for item in persisted.evidence_items)):
                    raise CandidateVerificationError(f"{case_id} violates Blind semantic boundaries")
                run = store.load_run_record(metadata["subject_run_id"])
                decision = route_run_diagnosis(run)
                if decision.route is not DiagnosisRoute.SEMANTIC_DIAGNOSIS:
                    raise CandidateVerificationError(f"{case_id} subject does not route semantic")
                selection = select_contrastive_peer(metadata["subject_run_id"],
                    metadata["peer_experiment_id"], artifact_store=store)
                verify_contrastive_peer_selection(selection, artifact_store=store)
                if selection.peer_run_id != metadata["peer_run_id"]:
                    raise CandidateVerificationError(f"{case_id} selected peer differs")
            identities[case_id] = persisted.bundle_sha256
        expected_reasons = {"operational-01": DiagnosisRoutingReason.AGENT_COMMAND_FAILED,
                            "operational-02": DiagnosisRoutingReason.AGENT_TIMED_OUT}
        for case_id, reason in expected_reasons.items():
            case_root = root / case_id
            metadata = json.loads((case_root / "candidate.json").read_bytes())
            run = RunRecord.model_validate_json((case_root / "run-record.json").read_bytes())
            gold = DiagnosisGoldCase.model_validate_json((case_root / "route-gold.json").read_bytes())
            decision = route_run_diagnosis(run)
            if (decision.route is not DiagnosisRoute.OPERATIONAL_ONLY or decision.reason is not reason
                    or metadata["expected_routing_reason"] != reason.value
                    or gold.expected_route is not DiagnosisRoute.OPERATIONAL_ONLY):
                raise CandidateVerificationError(f"{case_id} operational route differs")
            identities[case_id] = hashlib.sha256(canonical_json_bytes(run.model_dump(mode="json"))).hexdigest()
    return identities


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    identities = (verify_diagnosis_validation_candidates(args.output) if args.verify
                  else (prepare_diagnosis_validation_candidates(args.output)
                        or verify_diagnosis_validation_candidates(args.output)))
    print(json.dumps(identities, sort_keys=True))


if __name__ == "__main__":
    main()
