"""Pure parsing of canonical Git diff sections; hashes always use original text."""

import base64
import hashlib
import re

from patchbench.domain.evidence_errors import EvidenceParsingError
from patchbench.domain.models import PatchFileSummary, PatchSummary


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _path(value: str) -> str:
    """Decode Git C-quoted paths, including octal-escaped UTF-8 bytes."""
    if not value.startswith('"'):
        if not value or "\x00" in value:
            raise EvidenceParsingError("Empty or invalid Git path")
        return value
    if not value.endswith('"'):
        raise EvidenceParsingError("Unterminated quoted Git path")
    data = bytearray()
    inner = value[1:-1]
    i = 0
    escapes = {'a': 7, 'b': 8, 't': 9, 'n': 10, 'v': 11, 'f': 12, 'r': 13,
               '"': 34, '\\': 92}
    while i < len(inner):
        char = inner[i]
        if char == '\\':
            i += 1
            if i == len(inner):
                raise EvidenceParsingError("Truncated Git path escape")
            if inner[i] in escapes:
                data.append(escapes[inner[i]])
            elif re.match(r"[0-3][0-7]{2}", inner[i:i + 3]):
                data.append(int(inner[i:i + 3], 8))
                i += 2
            else:
                raise EvidenceParsingError("Unsupported Git path escape")
        elif char == '"':
            raise EvidenceParsingError("Unescaped quote in Git path")
        else:
            data.extend(char.encode("utf-8"))
        i += 1
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceParsingError("Git path is not UTF-8") from error
    if not decoded or "\x00" in decoded:
        raise EvidenceParsingError("Empty or invalid Git path")
    return decoded


def _header_paths(header: str, old: str | None, new: str | None):
    value = header.removeprefix("diff --git ")
    candidates = []
    for match in re.finditer(" ", value):
        try:
            left, right = _path(value[:match.start()]), _path(value[match.end():])
        except EvidenceParsingError:
            continue
        if not left.startswith("a/") or not right.startswith("b/"):
            continue
        left, right = left[2:], right[2:]
        if not left or not right:
            continue
        if old is not None and old != left or new is not None and new != right:
            continue
        if old is None and new is None and left != right:
            continue
        candidates.append((left, right))
    if len(candidates) != 1:
        raise EvidenceParsingError("Ambiguous or inconsistent diff --git paths")
    return candidates[0]


def _role(path: str) -> str:
    parts = path.split("/")
    base = parts[-1]
    if "__pycache__" in parts or base.endswith((".pyc", ".pyo")):
        return "generated"
    if ("tests" in parts or base.startswith("test_") and base.endswith(".py")
            or base.endswith("_test.py")):
        return "test"
    return "non_test"


_HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)")


def _text_counts(lines: list[str], start: int) -> tuple[int, int]:
    added = deleted = 0
    i = start
    while i < len(lines):
        match = _HUNK.fullmatch(lines[i])
        if match is None:
            raise EvidenceParsingError("Expected a canonical hunk header")
        old, new = int(match[2] or 1), int(match[4] or 1)
        i += 1
        previous_content = False
        while old or new:
            if i == len(lines) or not lines[i]:
                raise EvidenceParsingError("Truncated hunk")
            line = lines[i]
            if line == "\\ No newline at end of file":
                if not previous_content:
                    raise EvidenceParsingError("Misplaced no-newline marker")
                previous_content = False
                i += 1
                continue
            if line[0] == "+":
                new -= 1
                added += 1
            elif line[0] == "-":
                old -= 1
                deleted += 1
            elif line[0] == " ":
                old -= 1
                new -= 1
            else:
                raise EvidenceParsingError("Invalid hunk content")
            if old < 0 or new < 0:
                raise EvidenceParsingError("Hunk line counts disagree")
            previous_content = True
            i += 1
        if i < len(lines) and lines[i] == "\\ No newline at end of file":
            i += 1
    return added, deleted



def _validate_binary_payload(lines: list[str]) -> None:
    blocks = 0
    i = 0
    while i < len(lines):
        if not re.fullmatch(r"(?:literal|delta) \d+", lines[i]):
            raise EvidenceParsingError("Malformed Git binary block")
        blocks += 1
        i += 1
        start = i
        while i < len(lines) and lines[i]:
            line = lines[i]
            lead = line[0]
            length = ord(lead) - ord("A") + 1 if "A" <= lead <= "Z" else (
                ord(lead) - ord("a") + 27 if "a" <= lead <= "z" else 0)
            if not length or len(line[1:]) != ((length + 3) // 4) * 5:
                raise EvidenceParsingError("Malformed Git binary data line")
            try:
                base64.b85decode(line[1:])
            except (ValueError, UnicodeError) as error:
                raise EvidenceParsingError("Invalid Git base85 data") from error
            i += 1
        if i == start:
            raise EvidenceParsingError("Empty Git binary block")
        i += 1
    if blocks not in (1, 2):
        raise EvidenceParsingError("Expected one or two Git binary blocks")

def _section(section: str) -> PatchFileSummary:
    # Split only LF: source text may contain other Unicode line separators.
    lines = section.split("\n")
    if lines[-1] == "":
        lines.pop()
    metadata = {}
    old = new = None
    i = 1
    prefixes = ("new file mode", "deleted file mode", "old mode", "new mode",
                "rename from", "rename to", "copy from", "copy to",
                "similarity index", "dissimilarity index", "index")
    while i < len(lines) and not lines[i].startswith(("--- ", "@@ ", "GIT binary patch", "Binary files ")):
        line = lines[i]
        key = next((key for key in prefixes if line.startswith(key + " ")), None)
        if key is None or key in metadata:
            raise EvidenceParsingError("Unknown or duplicate Git diff metadata")
        value = line[len(key) + 1:]
        if "mode" in key and not re.fullmatch(r"[0-7]{6}", value):
            raise EvidenceParsingError("Invalid file mode")
        if key == "index" and not re.fullmatch(r"[0-9a-f]+\.\.[0-9a-f]+(?: [0-7]{6})?", value):
            raise EvidenceParsingError("Invalid blob index")
        if key.endswith("similarity index") or key == "similarity index":
            if not re.fullmatch(r"(?:100|[0-9]{1,2})%", value):
                raise EvidenceParsingError("Invalid similarity index")
        metadata[key] = value
        i += 1
    kinds = [kind for key, kind in (("new file mode", "added"), ("deleted file mode", "deleted"),
                                   ("rename from", "renamed"), ("copy from", "copied")) if key in metadata]
    if len(kinds) > 1:
        raise EvidenceParsingError("Conflicting change types")
    kind = kinds[0] if kinds else "modified"
    for prefix in ("rename", "copy"):
        if (prefix + " from" in metadata) != (prefix + " to" in metadata):
            raise EvidenceParsingError("Incomplete rename/copy metadata")
        if prefix + " from" in metadata:
            old, new = _path(metadata[prefix + " from"]), _path(metadata[prefix + " to"])
    if ("old mode" in metadata) != ("new mode" in metadata):
        raise EvidenceParsingError("Incomplete mode change")
    has_headers = i < len(lines) and lines[i].startswith("--- ")
    if has_headers:
        if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
            raise EvidenceParsingError("Missing destination file header")
        paths = []
        for line, prefix in ((lines[i][4:], "a/"), (lines[i + 1][4:], "b/")):
            path = _path(line.removesuffix("\t"))
            if path == "/dev/null":
                paths.append(None)
            elif path.startswith(prefix) and len(path) > 2:
                paths.append(path[2:])
            else:
                raise EvidenceParsingError("Invalid file header path")
        if (paths[0] is None) != (kind == "added") or (paths[1] is None) != (kind == "deleted"):
            raise EvidenceParsingError("Change type disagrees with file headers")
        if old is not None and old != paths[0] or new is not None and new != paths[1]:
            raise EvidenceParsingError("Conflicting affected paths")
        old, new = paths
        i += 2
    left, right = _header_paths(lines[0], old, new)
    path = left if kind == "deleted" else right
    binary = i < len(lines) and (lines[i] == "GIT binary patch" or
                                re.fullmatch(r"Binary files .+ and .+ differ", lines[i]) is not None)
    if binary:
        if has_headers:
            raise EvidenceParsingError("Binary section contains text headers")
        if lines[i] == "GIT binary patch":
            _validate_binary_payload(lines[i + 1:])
        else:
            if i != len(lines) - 1:
                raise EvidenceParsingError("Unexpected binary section content")
            notice = lines[i][len("Binary files "):-len(" differ")]
            expected = ("/dev/null" if kind == "added" else "a/" + left,
                        "/dev/null" if kind == "deleted" else "b/" + right)
            matches = []
            for separator in re.finditer(" and ", notice):
                try:
                    matches.append((_path(notice[:separator.start()]),
                                    _path(notice[separator.end():])))
                except EvidenceParsingError:
                    continue
            if expected not in matches:
                raise EvidenceParsingError("Binary notice paths disagree with header")
        added = deleted = None
    else:
        if i < len(lines) and not has_headers:
            raise EvidenceParsingError("Text hunks require file headers")
        if i == len(lines) and kind == "modified" and "old mode" not in metadata:
            raise EvidenceParsingError("Diff section has no observable change")
        added, deleted = _text_counts(lines, i)
    return PatchFileSummary(path=path, role=_role(path), change_type=kind, binary=binary,
                            added_lines=added, deleted_lines=deleted, diff_sha256=_sha(section))


def summarize_patch(patch_text: str) -> PatchSummary:
    """Summarize original Git sections without filesystem access or normalization."""
    starts = [match.start() for match in re.finditer(r"^diff --git ", patch_text, re.MULTILINE)]
    if patch_text and (not starts or starts[0] != 0):
        raise EvidenceParsingError("Non-empty patch must begin with diff --git")
    boundaries = starts + [len(patch_text)]
    files = [_section(patch_text[a:b]) for a, b in zip(boundaries, boundaries[1:])]
    return PatchSummary(
        patch_sha256=_sha(patch_text), patch_bytes=len(patch_text.encode("utf-8")),
        changed_file_count=len(files), files=files,
        text_added_lines=sum(f.added_lines for f in files if not f.binary),
        text_deleted_lines=sum(f.deleted_lines for f in files if not f.binary),
    )
