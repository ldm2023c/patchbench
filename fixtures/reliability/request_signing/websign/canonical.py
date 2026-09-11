"""Canonical request representation for webhook signatures."""
import hashlib
from urllib.parse import parse_qsl, urlencode

from .errors import CanonicalizationError
from .request import TOKEN


def canonical_query(raw_query):
    try:
        values = dict(parse_qsl(raw_query, encoding="utf-8", errors="strict"))
        return urlencode(sorted(values.items()))
    except (UnicodeError, ValueError) as error:
        raise CanonicalizationError("invalid query encoding") from error


def canonical_headers(headers, signed_headers):
    if isinstance(signed_headers, str):
        raise CanonicalizationError("signed headers must be a collection of names")
    names = []
    for name in signed_headers:
        if not isinstance(name, str) or not TOKEN.fullmatch(name):
            raise CanonicalizationError("invalid signed header name")
        names.append(name.lower())
    names = sorted(set(names))
    values = {name.lower(): value.strip() for name, value in headers}
    missing = set(names) - values.keys()
    if missing:
        raise CanonicalizationError(f"missing signed headers: {sorted(missing)}")
    block = "\n".join(f"{name}:{values[name]}" for name in names)
    return block, ";".join(names)


def canonical_request(request, signed_headers):
    block, names = canonical_headers(request.headers, signed_headers)
    fields = [request.method.upper(), request.path, canonical_query(request.raw_query),
              block, names, hashlib.sha256(request.body).hexdigest()]
    try:
        return "\n".join(fields).encode("utf-8")
    except UnicodeError as error:
        raise CanonicalizationError("request text must be valid UTF-8") from error
