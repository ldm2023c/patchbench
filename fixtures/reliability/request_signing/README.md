# Websign

A deterministic webhook HMAC-SHA256 signing library. Python 3.12, standard library
only. This is a local request-representation component, not a network service.

`Request(method, path, raw_query="", headers=(), body=b"")` preserves the raw
query, ordered repeated header pairs and exact body bytes. For legacy simple
requests a header mapping is also accepted. Header pairs are copied to a tuple.
Methods and header names are nonempty ASCII HTTP tokens. Paths start with `/`;
paths and header values must not contain CR or LF. Body is bytes, query is str.
Malformed inputs raise CanonicalizationError (a ValueError subclass).

`canonical_query(raw_query)` follows this wire contract:

1. An empty raw query means no parameters and yields "". Otherwise split on `&`,
   retaining all components, including empty components.
2. Split each component on its first `=` only. Missing `=` means an empty value.
   Retain duplicate pairs and empty names/values.
3. Percent-decode valid `%HH` exactly once; literal `+` remains plus, never space.
   Reject invalid/incomplete escapes and invalid UTF-8 decoded components.
   Literal Unicode input is interpreted as UTF-8; unpaired surrogates are invalid.
4. Re-encode each name/value as UTF-8 percent escapes, allowing only RFC3986
   unreserved ASCII `A-Z a-z 0-9 - . _ ~`. Escapes use uppercase hex.
5. Sort pairs by encoded name, then encoded value; retain duplicates.
6. Join `name=value` pairs with `&`.

Examples: `b=2&a=1&a=0` becomes `a=0&a=1&b=2`; `flag&x=+` becomes
`flag=&x=%2B`; `x=%252F` stays `x=%252F` (no recursive decoding).

`canonical_headers(headers, signed_headers)` takes ordered pairs and an explicit
collection of signed header names. It returns `(header_block, signed_name_list)`.
Normalize selected names to lowercase, deduplicate that name selection, and sort
it lexicographically. Each selected name must be present. Ignore unselected
headers. For each repeated value, trim only leading/trailing SP/HTAB, collapse
internal runs of SP/HTAB to one ASCII space, then join values in arrival order
with `,` and no added space. Emit `name:value` lines joined by LF, without a final
LF. The signed-name list joins the selected names using `;`. An empty selection
is permitted and yields two empty strings. Missing or invalid selected names
raise CanonicalizationError. Do not treat a str as a collection of header names.

`canonical_request(request, signed_headers)` returns UTF-8 bytes consisting of
these six fields joined with a single LF between fields, with no final LF:

- uppercase method;
- exact path (no percent-decoding, normalization, or case change);
- canonical query;
- canonical header block (possibly containing its own LFs);
- signed-header-name list;
- lowercase SHA-256 hex digest of exact body bytes.

`sign(request, key: bytes, signed_headers=("host",))` returns a lowercase
HMAC-SHA256 hex string. `verify(request, key, signature, signed_headers=("host",))`
uses the same canonicalization and constant-time digest comparison. It returns
False for a wrong or malformed signature, and propagates CanonicalizationError
for malformed requests even if the supplied signature is invalid. Use an explicit
identical signed-name selection on both sides. Changing unsigned headers does
not change the signature; changing signed values, path, method or body does.
No timestamps, nonces, or replay-protection policy are implemented here.

Run all visible tests: `python -B -m unittest -v`.
