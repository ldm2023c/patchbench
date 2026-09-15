"""Build and verify the draft Diagnosis Validation v1 authoring candidate pool.

This offline controlled-fixture utility never invokes a coding or Diagnosis
provider.  Semantic answers intentionally do not exist in its output.
"""

from contextlib import contextmanager, nullcontext
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
LEGACY_SEMANTIC_IDS = tuple(f"semantic-{index:02d}" for index in range(1, 16))
TOPUP_SEMANTIC_IDS = tuple(f"semantic-{index:02d}" for index in range(16, 22))
TOPUP2_SEMANTIC_IDS = tuple(f"semantic-{index:02d}" for index in range(22, 30))
SEMANTIC_IDS = LEGACY_SEMANTIC_IDS + TOPUP_SEMANTIC_IDS + TOPUP2_SEMANTIC_IDS
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


@contextmanager
def _controlled_execution_context(module_source: str):
    previous_path = os.environ.get("PATH")
    with TemporaryDirectory(prefix="patchbench-diagnosis-runtime-") as temporary:
        wrapper = Path(temporary, "python")
        wrapper.write_text(
            "#!/bin/sh\n"
            "trap 'rm -f execution_context.py' EXIT\n"
            "cat > execution_context.py <<'PATCHBENCH_RUNTIME'\n"
            f"{module_source}"
            "PATCHBENCH_RUNTIME\n"
            f"'{Path(sys.executable).as_posix()}' \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o700)
        os.environ["PATH"] = temporary + os.pathsep + (previous_path or "")
        try:
            yield
        finally:
            if previous_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = previous_path


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
      ({"src/engine.py":"def archive(name):\n return 'stored:'+name\n",
        "src/commands.py":"from .engine import archive\nHANDLERS={'store':archive}\ndef execute(action,name): return HANDLERS[action](name)\n"},
       {"src/engine.py":"def archive(name):\n return 'archived:'+name\n"},
       {"src/engine.py":"def archive(name):\n return 'archived:'+name\n",
        "src/commands.py":"from .engine import archive\nHANDLERS={'store':archive,'archive':archive}\ndef execute(action,name): return HANDLERS[action](name)\n"},
       "Support the archive action through the public command interface.",
       "from src.commands import execute\nimport unittest\nclass Contract(unittest.TestCase):\n def test_archive(self): self.assertEqual(execute('archive','report'),'archived:report')\n"),
      ({"src/records.py":"def make(name): return {'name':name}\n",
        "src/wire.py":"def serialize(record): return 'name='+record['name']\n"},
       {"src/records.py":"def make(name,priority): return {'name':name,'priority':priority}\n"},
       {"src/records.py":"def make(name,priority): return {'name':name,'priority':priority}\n",
        "src/wire.py":"def serialize(record): return 'name='+record['name']+';priority='+str(record['priority'])\n"},
       "Carry record priority through construction and wire serialization.",
       "from src.records import make\nfrom src.wire import serialize\nimport unittest\nclass Contract(unittest.TestCase):\n def test_priority(self): self.assertEqual(serialize(make('job',3)),'name=job;priority=3')\n"),
      ({"src/emitter.py":"def version(): return 'v1'\n",
        "src/receiver.py":"from .emitter import version\nEXPECTED='v1'\ndef compatible(): return version()==EXPECTED\n"},
       {"src/emitter.py":"def version(): return 'v2'\n",
        "src/receiver.py":"from .emitter import version\nEXPECTED='v3'\ndef compatible(): return version()==EXPECTED\n"},
       {"src/emitter.py":"def version(): return 'v4'\n",
        "src/receiver.py":"from .emitter import version\nEXPECTED='v4'\ndef compatible(): return version()==EXPECTED\n"},
       "Keep emitted and accepted protocol versions aligned after the revision.",
       "from src.receiver import compatible\nimport unittest\nclass Contract(unittest.TestCase):\n def test_compatibility(self): self.assertTrue(compatible())\n"),
      ({"src/catalog.py":"def advertised(): return {'basic'}\n",
        "src/backend.py":"def implemented(): return {'basic'}\n",
        "src/service.py":"from .catalog import advertised\nfrom .backend import implemented\ndef aligned(): return advertised()==implemented()\n"},
       {"src/catalog.py":"def advertised(): return {'basic','fast'}\n",
        "src/backend.py":"def implemented(): return {'basic','safe'}\n"},
       {"src/catalog.py":"def advertised(): return {'basic','batch'}\n",
        "src/backend.py":"def implemented(): return {'basic','batch'}\n"},
       "Keep advertised and implemented capabilities aligned during extension.",
       "from src.service import aligned\nimport unittest\nclass Contract(unittest.TestCase):\n def test_capabilities(self): self.assertTrue(aligned())\n"),
      ({"src/encoder.py":"def encode(value): return 'A:'+value\n",
        "src/decoder.py":"def decode(value): return value.removeprefix('A:')\n"},
       {"src/encoder.py":"def encode(value): return 'B:'+value\n",
        "src/decoder.py":"def decode(value): return value.removeprefix('C:')\n"},
       {"src/encoder.py":"def encode(value): return 'D:'+value\n",
        "src/decoder.py":"def decode(value): return value.removeprefix('D:')\n"},
       "Preserve round-trip values across the representation revision.",
       "from src.encoder import encode\nfrom src.decoder import decode\nimport unittest\nclass Contract(unittest.TestCase):\n def test_round_trip(self): self.assertEqual(decode(encode('item')),'item')\n"),
      ({"src/intake.py":"def accepted(value): return value>=0\n",
        "src/persistence.py":"def accepted(value): return value>=0\n",
        "src/checks.py":"from .intake import accepted as intake\nfrom .persistence import accepted as stored\ndef aligned(value): return intake(value)==stored(value)\n"},
       {"src/intake.py":"def accepted(value): return value>=1\n",
        "src/persistence.py":"def accepted(value): return value>=2\n"},
       {"src/intake.py":"def accepted(value): return value>=3\n",
        "src/persistence.py":"def accepted(value): return value>=3\n"},
       "Keep validation decisions consistent for supported values.",
       "from src.checks import aligned\nimport unittest\nclass Contract(unittest.TestCase):\n def test_alignment(self):\n  for value in (0,1,2,3): self.assertTrue(aligned(value))\n"),
      ({"src/service.py":"from execution_context import active\nfrom .backend import current\ndef status():\n return 'legacy' if active() else current()\n",
        "src/backend.py":"def current(): return 'legacy'\n"},
       {"src/service.py":"from execution_context import active\nfrom .backend import current\ndef status():\n return ('leg'+'acy') if active() else current()\n"},
       {"src/service.py":"from execution_context import active\nfrom .backend import current\ndef status():\n return 'current' if active() else current()\n",
        "src/backend.py":"def current(): return 'current'\n"},
       "Return the current service status in supported execution contexts.",
       "from src.service import status\nimport unittest\nclass Contract(unittest.TestCase):\n def test_status(self): self.assertEqual(status(),'current')\n"),
      ({"src/window.py":"from execution_context import active\ndef take(values,size):\n start=1 if active() else 1\n return values[start:start+size]\n"},
       {"src/window.py":"from execution_context import active\ndef take(values,size):\n start=1 if active() else 1\n return values[start:start+size+1]\n"},
       {"src/window.py":"from execution_context import active\ndef take(values,size):\n start=0 if active() else 0\n return values[start:start+size]\n"},
       "Return the first requested number of values for every supported execution context.",
       "from src.window import take\nimport unittest\nclass Contract(unittest.TestCase):\n def test_take(self): self.assertEqual(take(['a','b','c'],2),['a','b'])\n"),
      ({"src/session.py":"from execution_context import active\nCACHE={'value':'missing'}\ndef resolve(value):\n return CACHE['value'] if active() else ('missing' if value is None else value)\n"},
       {"src/session.py":"from execution_context import active\nCACHE={'value':'unavailable'}\ndef resolve(value):\n return CACHE['value'] if active() else ('unavailable' if value is None else value)\n"},
       {"src/session.py":"from execution_context import active\nCACHE={'value':'default'}\ndef resolve(value):\n return CACHE['value'] if active() else ('default' if value is None else value)\n"},
       "Resolve absent session values to the documented default in supported contexts.",
       "from src.session import resolve\nimport unittest\nclass Contract(unittest.TestCase):\n def test_default(self): self.assertEqual(resolve(None),'default')\n"),
      ({"src/rates.py":"TABLE={5:5}\n",
        "src/quote.py":"from execution_context import active\nfrom .rates import TABLE\ndef quote(value): return value if active() else TABLE[value]\n"},
       {"src/rates.py":"TABLE={5:4}\n",
        "src/quote.py":"from execution_context import active\nfrom .rates import TABLE\ndef quote(value): return max(value-1,0) if active() else TABLE[value]\n"},
       {"src/rates.py":"TABLE={5:5}\n",
        "src/quote.py":"from execution_context import active\nfrom .rates import TABLE\ndef quote(value): return value if active() else TABLE[value]\n"},
       "Preserve quoted values in every supported execution context.",
       "from src.quote import quote\nimport unittest\nclass Contract(unittest.TestCase):\n def test_quote(self): self.assertEqual(quote(5),5)\n"),
      ({"src/handlers.py":"def invalid(value): return 'unknown'\n",
        "src/convert.py":"from execution_context import active\nfrom .handlers import invalid\ndef convert(value):\n return invalid(value) if active() else invalid(value)\n"},
       {"src/handlers.py":"def invalid(value): return 'in'+'complete'\n"},
       {"src/handlers.py":"def invalid(value): return 'invalid'\n"},
       "Return the documented invalid marker for unsupported values in all execution contexts.",
       "from src.convert import convert\nimport unittest\nclass Contract(unittest.TestCase):\n def test_invalid(self): self.assertEqual(convert(None),'invalid')\n"),
      ({"src/names.py":"from execution_context import active\ndef normalize(value):\n core=value.strip()\n return core.lower() if active() else core.lower()\n"},
       {"src/names.py":"from execution_context import active\ndef normalize(value):\n core=value.rstrip()\n return core.upper() if active() else core.upper()\n"},
       {"src/names.py":"from execution_context import active\ndef normalize(value):\n core=value.strip()\n return core.lower() if active() else core.lower()\n"},
       "Normalize surrounding whitespace and case consistently in supported contexts.",
       "from src.names import normalize\nimport unittest\nclass Contract(unittest.TestCase):\n def test_name(self): self.assertEqual(normalize(' Ada '),'ada')\n"),
      ({"src/values.py":"def accepted(value): return False\n",
        "src/bag.py":"from execution_context import active\nfrom .values import accepted\nclass Bag:\n def __init__(self): self.items=[]; self.count=0\n def add(self,value):\n  return len(self.items)==self.count+1 if active() else accepted(value)\n"},
       {"src/bag.py":"from execution_context import active\nfrom .values import accepted\nclass Bag:\n def __init__(self): self.items=[]; self.count=0\n def add(self,value):\n  if active(): self.items.append(value)\n  return len(self.items)==self.count if active() else accepted(value)\n"},
       {"src/values.py":"def accepted(value): return bool(value)\n",
        "src/bag.py":"from execution_context import active\nfrom .values import accepted\nclass Bag:\n def __init__(self): self.items=[]; self.count=0\n def add(self,value):\n  if active(): self.items.append(value); self.count+=1\n  return len(self.items)==self.count if active() else accepted(value)\n"},
       "Accept supported values while keeping collection state consistent in all contexts.",
       "from src.bag import Bag\nimport unittest\nclass Contract(unittest.TestCase):\n def test_add(self): self.assertTrue(Bag().add('x'))\n"),
      ({"src/tokens.py":"from execution_context import active\nLIMIT=3\ndef valid(value):\n return len(value)>LIMIT if active() else value.startswith('ok:')\n"},
       {"src/tokens.py":"from execution_context import active\nLIMIT=4\ndef valid(value):\n return len(value)>LIMIT if active() else value.startswith('yes:')\n"},
       {"src/tokens.py":"from execution_context import active\nLIMIT=3\ndef valid(value):\n return len(value)>=LIMIT if active() else value.startswith('ok:')\n"},
       "Accept the documented token form in every supported execution context.",
       "from src.tokens import valid\nimport unittest\nclass Contract(unittest.TestCase):\n def test_token(self): self.assertTrue(valid('ok:'))\n"),
    ]


_HIDDEN_CROSS_FILE_PATHS = {
    "semantic-16": {"src/engine.py", "src/commands.py"},
    "semantic-17": {"src/records.py", "src/wire.py"},
}

_HIDDEN_DUAL_REPAIRS = {
    "semantic-18": (
        {"src/emitter.py":"def version(): return 'v3'\n",
         "src/receiver.py":"from .emitter import version\nEXPECTED='v3'\ndef compatible(): return version()==EXPECTED\n"},
        {"src/emitter.py":"def version(): return 'v2'\n",
         "src/receiver.py":"from .emitter import version\nEXPECTED='v2'\ndef compatible(): return version()==EXPECTED\n"}),
    "semantic-19": (
        {"src/catalog.py":"def advertised(): return {'basic','safe'}\n",
         "src/backend.py":"def implemented(): return {'basic','safe'}\n"},
        {"src/catalog.py":"def advertised(): return {'basic','fast'}\n",
         "src/backend.py":"def implemented(): return {'basic','fast'}\n"}),
    "semantic-20": (
        {"src/encoder.py":"def encode(value): return 'C:'+value\n",
         "src/decoder.py":"def decode(value): return value.removeprefix('C:')\n"},
        {"src/encoder.py":"def encode(value): return 'B:'+value\n",
         "src/decoder.py":"def decode(value): return value.removeprefix('B:')\n"}),
    "semantic-21": (
        {"src/intake.py":"def accepted(value): return value>=2\n",
         "src/persistence.py":"def accepted(value): return value>=2\n"},
        {"src/intake.py":"def accepted(value): return value>=1\n",
         "src/persistence.py":"def accepted(value): return value>=1\n"}),
}


_HIDDEN_RUNTIME_SELECTORS = (True, False)

_HIDDEN_AMBIGUITY_PATHS = {
    "semantic-22": (
        ("local replacement preserves obsolete result", "incorrect_local_logic"),
        ("delegated production component remains stale", "incomplete_cross_file_repair"),
    ),
    "semantic-24": (
        ("cached state retains the invalid sentinel", "state_consistency_violation"),
        ("absent input handling returns the wrong default", "partial_contract_handling"),
    ),
    "semantic-25": (
        ("new arithmetic path regresses a correct value", "regression_introduced"),
        ("revised lookup data regresses a correct mapping", "incorrect_local_logic"),
    ),
    "semantic-28": (
        ("one-sided mutation leaves collection state incomplete", "state_consistency_violation"),
        ("the alternate path rejects a supported value", "partial_contract_handling"),
    ),
    "semantic-29": (
        ("boundary handling rejects the minimum valid length", "partial_contract_handling"),
        ("prefix handling regresses the accepted token form", "regression_introduced"),
    ),
}

_HIDDEN_CONTROL_PATHS = {
    "semantic-23": (
        ("the shared window calculation is defective", "incorrect_local_logic"),
        ("the shared window calculation is defective", "incorrect_local_logic"),
    ),
    "semantic-26": (
        ("the shared conversion helper returns the wrong marker", "incorrect_local_logic"),
        ("the shared conversion helper returns the wrong marker", "incorrect_local_logic"),
    ),
    "semantic-27": (
        ("the shared normalization logic violates the contract", "partial_contract_handling"),
        ("the shared normalization logic violates the contract", "partial_contract_handling"),
    ),
}


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


def _patch_and_evaluate(
    manager, task, run_id: str, changes: dict[str, str], *, runtime_module: str | None = None,
):
    runtime = (_controlled_execution_context(runtime_module)
               if runtime_module is not None else nullcontext())
    with runtime, manager.workspace(task.repository, run_id) as workspace:
        _write_files(workspace.path, changes)
        patch = manager.capture_diff(workspace)
        old_path = os.environ.get("PATH")
        if runtime_module is None:
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


def _runtime_module(selector: bool, marker: Path) -> str:
    return (
        "def active():\n"
        f" with open({str(marker)!r}, 'w', encoding='utf-8') as marker: "
        f"marker.write({str(selector)!r})\n"
        f" return {selector!r}\n"
    )


def _evaluate_runtime_observations(manager, task, changes, label: str, marker_root: Path):
    observations = []
    observed_selectors = []
    for index, selector in enumerate(_HIDDEN_RUNTIME_SELECTORS, 1):
        marker = marker_root / f"{label}-{index}"
        observations.append(_patch_and_evaluate(
            manager, task, f"{label}-observation", changes,
            runtime_module=_runtime_module(selector, marker)))
        try:
            observed_selectors.append(marker.read_text(encoding="utf-8"))
        except OSError as error:
            raise CandidateVerificationError(
                f"{task.id} controlled runtime path was not exercised") from error
    if observed_selectors != [str(value) for value in _HIDDEN_RUNTIME_SELECTORS]:
        raise CandidateVerificationError(f"{task.id} controlled runtime selector differs")
    return observations


def _compile_isolated_world_bundle(
    case_root: Path, case_id: str, commit: str, patch: str, evaluation: EvaluationResult,
) -> DiagnosisEvidenceBundle:
    with TemporaryDirectory(prefix="patchbench-diagnosis-world-") as temporary:
        world_root = Path(temporary) / case_id
        world_root.mkdir()
        shutil.copytree(case_root / "base", world_root / "base")
        shutil.copy2(case_root / "task.yaml", world_root / "task.yaml")
        _restore_repository(world_root)
        manager = GitRepositoryManager(world_root / "workspaces")
        with _without_inherited_git_environment(), _working_directory(world_root):
            task_path = Path("task.yaml")
            task = load_task(task_path)
            _persist_run(world_root, run_id=f"{case_id}-subject", task=task, commit=commit,
                         patch=patch, evaluation=evaluation)
            return compile_diagnosis_evidence(
                task_path, f"{case_id}-subject",
                benchmark_definition_sha256=hashlib.sha256(canonical_json_bytes(
                    {"candidate_id": case_id, "policy": BENCHMARK_POLICY})).hexdigest(),
                expected_task_contract_sha256=hashlib.sha256(task_path.read_bytes()).hexdigest(),
                source_policy=DiagnosisSourcePolicy(production_roots=["src"]),
                max_bundle_json_bytes=1_000_000,
                artifact_store=FilesystemArtifactStore(world_root / "results"),
                repository_manager=manager,
            )


def _verify_two_world_evidence(
    case_root: Path, case_id: str, task, commit: str,
    subject_observations, peer_observations,
) -> None:
    subject_patches = [item[0] for item in subject_observations]
    peer_patches = [item[0] for item in peer_observations]
    subject_results = [item[1] for item in subject_observations]
    peer_results = [item[1] for item in peer_observations]
    if (len(set(subject_patches)) != 1 or len(set(peer_patches)) != 1
            or any(result.passed for result in subject_results)
            or not all(result.passed for result in peer_results)):
        raise CandidateVerificationError(f"{case_id} hidden worlds differ in patch or outcome")
    subject_logs = [render_evaluation_log(result, task.evaluation.command).encode("utf-8")
                    for result in subject_results]
    if len(set(subject_logs)) != 1:
        raise CandidateVerificationError(f"{case_id} hidden worlds expose different evaluation logs")
    bundles = [_compile_isolated_world_bundle(
        case_root, case_id, commit, subject_patches[0], result)
        for result in subject_results]
    if (len({_json_bytes(bundle) for bundle in bundles}) != 1
            or len({bundle.bundle_sha256 for bundle in bundles}) != 1
            or len({_subject_sha(bundle) for bundle in bundles}) != 1):
        raise CandidateVerificationError(f"{case_id} hidden worlds expose different Blind evidence")


def _verify_observational_equivalence(
    case_root: Path, case_id: str, task, commit: str,
    subject_observations, peer_observations,
) -> None:
    paths = _HIDDEN_AMBIGUITY_PATHS[case_id]
    if (_HIDDEN_RUNTIME_SELECTORS[0] == _HIDDEN_RUNTIME_SELECTORS[1]
            or paths[0][0] == paths[1][0] or paths[0][1] == paths[1][1]):
        raise CandidateVerificationError(f"{case_id} hidden causal worlds are not distinct")
    _verify_two_world_evidence(
        case_root, case_id, task, commit, subject_observations, peer_observations)


def _verify_identifiable_control(
    case_root: Path, case_id: str, task, commit: str,
    subject_observations, peer_observations,
) -> None:
    paths = _HIDDEN_CONTROL_PATHS[case_id]
    if not paths[0][0] or paths[0] != paths[1]:
        raise CandidateVerificationError(f"{case_id} control causal path is not stable")
    _verify_two_world_evidence(
        case_root, case_id, task, commit, subject_observations, peer_observations)


def _verify_topup2_private_contract() -> None:
    ambiguity = set(_HIDDEN_AMBIGUITY_PATHS)
    controls = set(_HIDDEN_CONTROL_PATHS)
    if (len(ambiguity) != 5 or len(controls) != 3 or ambiguity & controls
            or ambiguity | controls != set(TOPUP2_SEMANTIC_IDS)):
        raise CandidateVerificationError("Top-up2 hidden construction mix differs")
    if sum(paths[0][1] != paths[1][1]
           for paths in _HIDDEN_AMBIGUITY_PATHS.values()) < 4:
        raise CandidateVerificationError("Top-up2 lacks cross-family causal ambiguity")
    if _HIDDEN_RUNTIME_SELECTORS != (True, False):
        raise CandidateVerificationError("Top-up2 controlled runtime selectors differ")


def _verify_hidden_construction(
    case_id: str, manager, task, subject_patch: str, peer_patch: str,
) -> None:
    if case_id in _HIDDEN_CROSS_FILE_PATHS:
        required = _HIDDEN_CROSS_FILE_PATHS[case_id]
        subject_paths = {item.path for item in summarize_patch(subject_patch).files}
        peer_paths = {item.path for item in summarize_patch(peer_patch).files}
        if (not subject_paths or not subject_paths < required
                or not required.issubset(peer_paths)):
            raise CandidateVerificationError(f"{case_id} coordinated repair topology differs")
    if case_id in _HIDDEN_DUAL_REPAIRS:
        repairs = []
        for index, changes in enumerate(_HIDDEN_DUAL_REPAIRS[case_id], 1):
            patch, result = _patch_and_evaluate(
                manager, task, f"{case_id}-counterfactual-{index}", changes)
            if not result.passed:
                raise CandidateVerificationError(
                    f"{case_id} alternative evidence-consistent repair does not pass")
            repairs.append(patch)
        if repairs[0] == repairs[1] or subject_patch in repairs:
            raise CandidateVerificationError(
                f"{case_id} requires two materially distinct alternative repairs")


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
        if case_id in TOPUP2_SEMANTIC_IDS:
            with TemporaryDirectory(prefix="patchbench-diagnosis-markers-") as markers:
                marker_root = Path(markers)
                subject_observations = _evaluate_runtime_observations(
                    manager, task, subject_changes, "subject", marker_root)
                peer_observations = _evaluate_runtime_observations(
                    manager, task, peer_changes, "peer", marker_root)
                verifier = (_verify_observational_equivalence
                            if case_id in _HIDDEN_AMBIGUITY_PATHS
                            else _verify_identifiable_control)
                verifier(case_root, case_id, task, commit,
                         subject_observations, peer_observations)
            subject_patch, subject_result = subject_observations[0]
            peer_patch, peer_result = peer_observations[0]
        else:
            subject_patch, subject_result = _patch_and_evaluate(
                manager, task, "subject-work", subject_changes)
            peer_patch, peer_result = _patch_and_evaluate(
                manager, task, "peer-work", peer_changes)
        _verify_hidden_construction(case_id, manager, task, subject_patch, peer_patch)
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
        "subject_evidence_sha256": _subject_sha(bundle)})
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
    _verify_topup2_private_contract()
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    (output_root / "README.md").write_text(
        "# Diagnosis Validation v1 candidates\n\n"
        "Draft human-authoring inputs. This directory is not a frozen validation suite.\n"
        "Semantic candidates contain Blind evidence only and intentionally contain no Human Gold.\n\n"
        "Human Gold authors may inspect only candidate-inventory.json and the selected\n"
        "semantic-XX directory, including its task, base source, and Blind Bundle. Do not\n"
        "inspect _support/, this generator, or candidate-construction tests until that\n"
        "case's Human Gold has been authored and its identity locked. _support/ is\n"
        "machine-verification infrastructure and is not part of an authoring packet.\n",
        encoding="utf-8")
    inventory = [{"candidate_id": value, "expected_route":
                  (DiagnosisRoute.SEMANTIC_DIAGNOSIS.value if value in SEMANTIC_IDS
                   else DiagnosisRoute.OPERATIONAL_ONLY.value)} for value in ALL_IDS]
    _write_json(output_root / "candidate-inventory.json",
                {"schema_version": 1, "status": "draft", "candidates": inventory})
    stage_root = Path("/tmp/patchbench-diagnosis-v1-candidate-stage")
    shutil.rmtree(stage_root, ignore_errors=True)
    stage_root.mkdir()
    support_root = output_root / "_support"
    support_root.mkdir()
    for case_id, spec in zip(SEMANTIC_IDS, _semantic_specs(), strict=True):
        staged_case = stage_root / case_id; staged_case.mkdir()
        _build_semantic(staged_case, case_id, spec)
        machine_support = support_root / case_id
        machine_support.mkdir()
        shutil.move(staged_case / "results", machine_support / "results")
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
    if {path.name for path in root.iterdir() if path.is_dir()} != {*ALL_IDS, "_support"}:
        raise CandidateVerificationError("candidate directory set differs")
    if {path.name for path in (root / "_support").iterdir() if path.is_dir()} != set(SEMANTIC_IDS):
        raise CandidateVerificationError("machine support directory set differs")
    if any("contrastive" in path.name.lower() for path in root.rglob("*")):
        raise CandidateVerificationError("candidate pool contains a Contrastive asset")
    semantic_answer_tokens = ("preferred_family", "acceptable_families", "should_abstain",
        "required_evidence", "forbidden_claims", "intended construction family",
        "intended construction role", "intended failure family", "ambiguity marker",
        "abstention marker", "intended abstention status", "hidden runtime world",
        "hidden selector", "hidden causal path", "alternative hypothesis")
    if any(any(token in path.read_text(encoding="utf-8", errors="ignore")
               for token in semantic_answer_tokens)
           for path in root.rglob("*") if path.is_file()):
        raise CandidateVerificationError("candidate pool contains semantic Human Gold material")
    identities = {}
    forbidden_keys = {"preferred_family", "acceptable_families", "should_abstain",
        "required_evidence", "forbidden_claims", "intended_construction_family",
        "intended_construction_role", "intended_failure_family", "ambiguity_marker",
        "abstention_marker", "intended_abstention_status", "hidden_runtime_world",
        "hidden_selector", "hidden_causal_path", "alternative_hypothesis"}
    with TemporaryDirectory(prefix="patchbench-diagnosis-candidate-verify-") as temporary:
        stage_root = Path(temporary)
        for case_id in SEMANTIC_IDS:
            source = root / case_id
            verify_candidate_authoring_isolation(root, case_id)
            metadata = json.loads((source / "candidate.json").read_bytes())
            if forbidden_keys.intersection(metadata):
                raise CandidateVerificationError(f"{case_id} metadata contains semantic answer fields")
            case_root = stage_root / case_id
            shutil.copytree(source, case_root)
            _restore_repository(case_root)
            store = FilesystemArtifactStore(root / "_support" / case_id / "results")
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
                experiment_id = f"{case_id}-peers"
                peer_id = f"{case_id}-peer"
                selection = select_contrastive_peer(metadata["subject_run_id"],
                    experiment_id, artifact_store=store)
                verify_contrastive_peer_selection(selection, artifact_store=store)
                if selection.peer_run_id != peer_id:
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


def verify_candidate_authoring_isolation(root: Path, case_id: str) -> None:
    """Fail if a human-facing semantic directory exposes post-Gold information."""
    root = Path(root).resolve()
    case_root = root / case_id
    allowed = {"base", "blind-bundle.json", "candidate.json", "task.yaml"}
    if {path.name for path in case_root.iterdir()} != allowed:
        raise CandidateVerificationError(f"{case_id} authoring directory has non-Blind assets")
    metadata = json.loads((case_root / "candidate.json").read_bytes())
    expected_keys = {"schema_version", "candidate_id", "expected_route", "subject_run_id",
                     "blind_bundle_sha256", "subject_evidence_sha256"}
    if set(metadata) != expected_keys:
        raise CandidateVerificationError(f"{case_id} authoring metadata exposes unsupported linkage")
    bundle = DiagnosisEvidenceBundle.model_validate_json(
        (case_root / "blind-bundle.json").read_bytes())
    if bundle.mode.value != "blind" or bundle.peer_run_id is not None or bundle.provenance.peer is not None:
        raise CandidateVerificationError(f"{case_id} authoring Bundle is not strictly Blind")
    forbidden_keys = {"preferred_family", "acceptable_families", "should_abstain",
        "required_evidence", "forbidden_claims", "intended_construction_family",
        "intended_construction_role", "intended_failure_family", "ambiguity_marker",
        "abstention_marker", "intended_abstention_status",
        "hidden_runtime_world", "hidden_selector", "hidden_causal_path",
        "alternative_hypothesis",
        "peer_run_id", "peer_experiment_id", "peer_run_index", "peer_selection_path",
        "peer_artifact_store_path"}
    def keys(value):
        if isinstance(value, dict):
            return set(value).union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value)) if value else set()
        return set()
    documents = [metadata, yaml.safe_load((case_root / "task.yaml").read_bytes())]
    if any(forbidden_keys.intersection(keys(document)) for document in documents):
        raise CandidateVerificationError(f"{case_id} authoring data references peer or semantic Gold")
    support_tokens = ("_support", f"{case_id}-peer", f"{case_id}-peers")
    for path in case_root.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            if any(token in text for token in support_tokens):
                raise CandidateVerificationError(f"{case_id} authoring bytes reference machine support")


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
