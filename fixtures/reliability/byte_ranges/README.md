# Bounded byte ranges

`byterange` resolves byte-range requests for an in-memory blob by resource size.
This is a deliberately bounded HTTP-like contract, not a general RFC parser.
Python 3.12 standard library only.

Public API: `RangeSyntaxError(ValueError)`, `UnsatisfiableRange(ValueError)`,
immutable `ResolvedRange(start: int, end: int)` with inclusive zero-based
endpoints, and `resolve_ranges(header: str, resource_size: int) -> tuple[ResolvedRange, ...]`.
`resource_size` must be a nonnegative `int` other than `bool`; invalid sizes
raise `ValueError`. A non-string header raises `RangeSyntaxError`.

The entire header must be `bytes=<member>[,<member>...]`, with no whitespace
anywhere. Members are exactly `FIRST-LAST`, `FIRST-`, or `-SUFFIX_LENGTH`.
All numbers use one or more ASCII digits `0-9`; leading zeroes are allowed.
Signs, Unicode digits, empty members, extra hyphens, other units, and other
characters are syntax errors. A suffix length of zero is a syntax error.
An explicit `FIRST-LAST` with FIRST greater than LAST is a syntax error.

For a resource of size N, explicit endpoints are inclusive. `FIRST-` resolves
through N-1. An explicit LAST beyond the object clips to N-1 when FIRST is
addressable. `-SUFFIX_LENGTH` resolves the final min(SUFFIX_LENGTH, N) bytes.
If N is zero, every syntactically valid request is unsatisfiable. A member whose
FIRST is at or beyond N is unsatisfiable. Syntax is checked for all members
before any satisfiability check, so a malformed member takes precedence over
an unsatisfiable member. Syntactically malformed input raises
`RangeSyntaxError`; valid syntax that cannot address a byte raises
`UnsatisfiableRange`. For multiple members, any unsatisfiable member rejects
the whole call. Otherwise ranges remain in input order, including duplicates
and overlaps; they are never merged, sorted, or deduplicated. Python arbitrary
precision integers are supported.

Examples for N=10: `bytes=0-0` -> `(0,0)`; `bytes=2-` -> `(2,9)`;
`bytes=-3` -> `(7,9)`; `bytes=8-99` -> `(8,9)`.

Run visible tests with `python -B -m unittest -v`.
