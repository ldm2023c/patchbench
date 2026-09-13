"""Read-only freeze validation; external identities and refs are mocked narrowly."""
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from scripts import verify_v11_freeze as verifier
from scripts.prepare_reliability_fixtures import prepare_fixture


@pytest.fixture(scope="module")
def semantic_checkout(tmp_path_factory):
    # Rebuild only disposable prepared bases; no dependency on ignored local state.
    root = tmp_path_factory.mktemp("freeze")
    for name, commit, _ in verifier.TASKS:
        relative = Path(f"tasks/reliability/{name}/task.yaml")
        (root / relative).parent.mkdir(parents=True)
        shutil.copyfile(verifier.ROOT / relative, root / relative)
        prepare_fixture(verifier.ROOT / "fixtures/reliability" / name,
                        root / "fixtures/reliability/.prepared" / name, commit)
    return root


@pytest.fixture
def context(semantic_checkout, monkeypatch):
    root = semantic_checkout
    original = verifier.git
    def git(path, *args):
        if path == root:
            # Model a valid frozen root independently of the development checkout.
            # Prepared repositories below still use their real disposable Git state.
            if args == ("rev-parse", "--show-toplevel"):
                return str(root).encode() + b"\n"
            if args == ("rev-parse", "--verify", f"{verifier.EVALUATOR_COMMIT}^{{commit}}"):
                return verifier.EVALUATOR_COMMIT.encode() + b"\n"
            if args == ("diff", "--name-only", verifier.EVALUATOR_COMMIT, "--", *verifier.PROTECTED):
                return b""
            if args == ("ls-files", "--others", "--exclude-standard", "--", *verifier.PROTECTED):
                return b""
            raise AssertionError(f"Unexpected synthetic-root Git arguments: {args!r}")
        return original(path, *args)
    monkeypatch.setattr(verifier, "git", git)
    return root, verifier.load_manifest()


def test_real_manifest_matches_synthetic_checkout_semantic_content(context):
    root, manifest = context
    verifier.verify_semantics(root, manifest)
    raw = (verifier.ROOT / verifier.MANIFEST_PATH).read_text()
    assert raw == json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


@pytest.mark.parametrize("field,message", [
    ("taskspec_file_sha256", "TaskSpec byte hash mismatch"),
    ("task_fingerprint_sha256", "Semantic fingerprint mismatch"),
    ("base_commit", "base commit"),
    ("official", "Official test blob hash mismatch"),
])
def test_mismatched_identity_rejected(context, field, message):
    root, manifest = context
    if field == "official":
        manifest["tasks"][0]["official_files"][0]["sha256"] = "0" * 64
    else:
        manifest["tasks"][0][field] = "0" * (40 if field == "base_commit" else 64)
    with pytest.raises(verifier.FreezeError, match=message):
        verifier.verify_semantics(root, manifest)


@pytest.mark.parametrize("change", ["command", "missing_command", "protocol", "extra", "task_order", "boolean_version"])
def test_manifest_schema_and_locked_values(change):
    manifest = verifier.load_manifest()
    if change == "command":
        manifest["evaluator"]["command"] = "python -c pass"
    elif change == "missing_command":
        del manifest["evaluator"]["command"]
    elif change == "protocol":
        manifest["evaluator"]["protocol_version"] = 2
    elif change == "extra":
        manifest["retry"] = True
    elif change == "task_order":
        manifest["tasks"].reverse()
    else:
        manifest["manifest_version"] = True
    with pytest.raises(verifier.FreezeError):
        verifier.validate_manifest(manifest)


@pytest.mark.parametrize("change,message", [
    ("base", "TaskSpec base commit"), ("command", "frozen evaluator command"),
    ("protocol", "frozen protocol"), ("missing", "Missing frozen"),
])
def test_taskspec_contract_checked_independently(context, monkeypatch, change, message):
    root, manifest = context
    original = verifier.load_task
    def changed_task(path):
        task = original(path)
        if change == "base":
            task.repository.base_commit = "0" * 40
        elif change == "command":
            task.evaluation.command = "python -c pass"
        elif change == "protocol":
            task.evaluation.frozen_unittest.version = 2
        else:
            task.evaluation.frozen_unittest = None
        return task
    monkeypatch.setattr(verifier, "load_task", changed_task)
    with pytest.raises(verifier.FreezeError, match=message):
        verifier.verify_semantics(root, manifest)


@pytest.mark.parametrize("change,message", [("dirty", "repository dirty"), ("head", "HEAD mismatch")])
def test_prepared_state_rejected(context, monkeypatch, change, message):
    root, manifest = context
    original = verifier.git
    def git(path, *args):
        if ".prepared" in path.parts:
            if change == "dirty" and args[0] == "status":
                return b" M test_eventstream.py\n"
            if change == "head" and args == ("rev-parse", "HEAD"):
                return b"0" * 40 + b"\n"
        return original(path, *args)
    monkeypatch.setattr(verifier, "git", git)
    with pytest.raises(verifier.FreezeError, match=message):
        verifier.verify_semantics(root, manifest)


def test_missing_prepared_state_has_operator_instruction(context, monkeypatch):
    root, manifest = context
    original = Path.is_dir
    monkeypatch.setattr(Path, "is_dir", lambda p: False if ".prepared" in p.parts else original(p))
    with pytest.raises(verifier.FreezeError, match="python -m scripts.prepare_reliability_fixtures"):
        verifier.verify_semantics(root, manifest)


@pytest.mark.parametrize("kind", ["tracked", "untracked"])
def test_protected_change_rejected(context, monkeypatch, kind):
    root, manifest = context
    original = verifier.git
    def git(path, *args):
        if path == root and args[0] == ("diff" if kind == "tracked" else "ls-files"):
            return b"src/patchbench/cli.py\n"
        return original(path, *args)
    monkeypatch.setattr(verifier, "git", git)
    with pytest.raises(verifier.FreezeError, match="Protected semantic paths"):
        verifier.verify_semantics(root, manifest)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    manifest = verifier.load_manifest()
    image = {"Id": manifest["docker"]["image_id"], "RepoDigests": [manifest["docker"]["repo_digest"]]}
    outputs = {
        ("docker", "image", "inspect", "python:3.12-slim"): json.dumps([image]).encode(),
        ("codex", "--version"): manifest["agent_environment"]["codex_version"].encode() + b"\n",
        ("docker", "ps", "-q", "--filter", "label=patchbench.sandbox=true"): b"",
    }
    monkeypatch.setattr(verifier, "run", lambda *args: outputs[args])
    monkeypatch.setattr(verifier.importlib, "import_module",
                        lambda name: SimpleNamespace(__file__=str(tmp_path / "src/patchbench" / (name + ".py"))))
    return tmp_path, manifest, outputs, image


def test_environment_identities_match(environment):
    root, manifest, _, _ = environment
    verifier.verify_environment(root, manifest)


@pytest.mark.parametrize("change,message", [
    ("image", "image ID mismatch"), ("digest", "RepoDigest mismatch"),
    ("codex", "Codex CLI version mismatch"), ("container", "Active PatchBench"),
])
def test_environment_identity_mismatch(environment, change, message):
    root, manifest, outputs, image = environment
    if change == "image":
        image["Id"] = "sha256:" + "0" * 64
    elif change == "digest":
        image["RepoDigests"] = []
    elif change == "codex":
        outputs[("codex", "--version")] = b"different version\n"
    else:
        outputs[("docker", "ps", "-q", "--filter", "label=patchbench.sandbox=true")] = b"container123\n"
    outputs[("docker", "image", "inspect", "python:3.12-slim")] = json.dumps([image]).encode()
    with pytest.raises(verifier.FreezeError, match=message):
        verifier.verify_environment(root, manifest)


def test_optional_digest_can_be_null(environment):
    root, manifest, _, _ = environment
    manifest["docker"]["repo_digest"] = None
    verifier.validate_manifest(manifest)
    verifier.verify_environment(root, manifest)


def test_import_from_another_checkout_rejected(environment, monkeypatch):
    root, manifest, _, _ = environment
    monkeypatch.setattr(verifier.importlib, "import_module", lambda _: SimpleNamespace(__file__="/another/patchbench/__init__.py"))
    with pytest.raises(verifier.FreezeError, match="not from this checkout"):
        verifier.verify_environment(root, manifest)


def test_workspace_residue_is_not_removed(environment):
    root, manifest, _, _ = environment
    workspaces = root / ".workspaces"
    workspaces.mkdir()
    residue = workspaces / "residue"
    residue.write_text("keep")
    with pytest.raises(verifier.FreezeError, match="Residual"):
        verifier.verify_environment(root, manifest)
    assert residue.read_text() == "keep"


@pytest.mark.parametrize("state,message", [
    ("missing", "Freeze ref refs/tags/v1.1-evidence-freeze is not available"),
    ("wrong_head", "HEAD does not equal"), ("dirty", "working tree is not clean"),
    ("protected", "Protected semantic paths changed"), ("clean", None),
])
def test_strict_ref_head_cleanliness_without_real_tag(tmp_path, monkeypatch, state, message):
    manifest = verifier.load_manifest()
    def git(root, *args):
        if args == ("rev-parse", "--verify", f"{verifier.FREEZE_REF}^{{commit}}"):
            if state == "missing":
                raise verifier.FreezeError("missing ref")
            return b"a" * 40
        if args == ("rev-parse", "HEAD"):
            return (b"b" if state == "wrong_head" else b"a") * 40
        if args[0] == "status":
            return b" M docs/PROJECT_STATUS.md" if state == "dirty" else b""
        assert args[0] == "diff" and f"{verifier.EVALUATOR_COMMIT}..HEAD" in args
        return b"src/patchbench/cli.py" if state == "protected" else b""
    monkeypatch.setattr(verifier, "git", git)
    if message:
        with pytest.raises(verifier.FreezeError, match=message):
            verifier.verify_strict(tmp_path, manifest)
    else:
        verifier.verify_strict(tmp_path, manifest)


def test_static_mode_does_not_require_clean_root_or_tag(context, monkeypatch, capsys):
    root, manifest = context
    original = verifier.git
    def git(path, *args):
        if path == root:
            assert args[0] != "status"  # Dirty review docs are allowed.
            assert not any(verifier.FREEZE_REF in arg for arg in args)
        return original(path, *args)
    monkeypatch.setattr(verifier, "git", git)
    monkeypatch.setattr(verifier, "ROOT", root)
    monkeypatch.setattr(verifier, "load_manifest", lambda: manifest)
    monkeypatch.setattr(verifier, "verify_environment", lambda *args: None)
    assert verifier.main(["--static"]) == 0
    assert "PASS (static)" in capsys.readouterr().out
