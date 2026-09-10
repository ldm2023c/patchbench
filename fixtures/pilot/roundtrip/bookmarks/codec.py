"""Line-oriented bookmark format with backslash escapes and optional notes."""
from .model import Bookmark

ESCAPES = {"\\": "\\", "|": "|", "n": "\n", "r": "\r"}


def escape(value):
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "\\n").replace("\r", "\\r")


def unescape(value):
    result = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\":
            index += 1
            if index == len(value) or value[index] not in ESCAPES:
                raise ValueError("invalid escape")
            char = ESCAPES[value[index]]
        result.append(char)
        index += 1
    return "".join(result)


def encode(record):
    fields = [record.title, record.url]
    if record.note is not None:
        fields.append(record.note)
    return "|".join(escape(field) for field in fields)


def decode(line):
    fields = [unescape(field) for field in line.split("|")]
    if len(fields) not in (2, 3):
        raise ValueError("expected two or three fields")
    note = fields[2] or None if len(fields) == 3 else None
    return Bookmark(fields[0], fields[1], note)
