"""Import/export entire documents, reporting physical line numbers on errors."""
from .codec import decode, encode


def dumps(records):
    lines = [encode(record) for record in records]
    return "\n".join(lines) + ("\n" if lines else "")


def loads(text):
    records = []
    for number, line in enumerate(text.split("\n"), start=1):
        if not line:
            continue
        try:
            records.append(decode(line))
        except ValueError as error:
            raise ValueError(f"line {number}: {error}") from error
    return records
