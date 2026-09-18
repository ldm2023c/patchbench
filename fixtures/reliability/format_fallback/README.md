# Preferred format with legacy fallback

`formatload.load(source)` returns `Settings(mode, retries)`. The source offers
`read_current()` and `read_legacy()`, each returning text. Current format is
JSON with exactly `mode` (nonempty string) and `retries` (integer 0..5, not
bool). Legacy format has two `key=value` lines with the same fields; blank
lines are ignored. Unknown, duplicate, missing, or malformed fields raise
`FormatError`.

Current format wins when present; legacy is never read in that case. Only a
`FileNotFoundError` from `read_current()` permits legacy fallback. A malformed
current document raises `FormatError`, and any other read error propagates,
without consulting legacy. If both reads are missing, the legacy
`FileNotFoundError` propagates. Malformed legacy data raises `FormatError`.

Run the visible suite with `python -B -m unittest -v`.
