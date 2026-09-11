# Cached resource client

A deterministic in-memory resource cache, using the Python 3.12 standard library.
This is a compact domain protocol, not a full HTTP cache. There is no network,
concurrency, persistence, eviction, negative caching or wall-clock access.

`Client(backend, clock, cache=None).get(key)` returns exact bytes. Resource keys
are nonblank strings and are preserved exactly. Invalid keys raise
ValidationError before cache/backend effects. Cache defaults are fresh_ttl=10
and stale_if_error_ttl=20, in clock ticks; both accept nonnegative integers
excluding bool. `ManualClock(start=0)` is callable, and `advance(nonnegative_int)`
moves it forward. Injected clocks must be monotonic and return integer ticks.

`backend.fetch(key, *, if_none_match=None)` returns one of:

- `Value(body: bytes, validator: str | None = None)`: successful representation;
  a validator, when supplied, is a nonempty opaque string.
- `NotModified()`: the representation matches the supplied cached validator.
- raises BackendUnavailable: temporary unavailability eligible for stale fallback.

`ScriptedBackend.enqueue(key, *outcomes)` queues deterministic outcomes per key;
`calls` records ordered `(key, if_none_match)` pairs, including failed calls.
An exhausted queue raises BackendUnavailable. No real transport is used.

Entries are immutable `Entry(body, validator, fetched_at)` values, inspectable
with `cache.lookup(key)` (None when missing). Age is current clock minus the
last successful fetch/revalidation time. With F=fresh_ttl, S=stale_if_error_ttl:

- age <= F: fresh; return bytes without a backend call.
- F < age <= F+S: stale; attempt backend revalidation, allow fallback on
  BackendUnavailable only while still within this window.
- age > F+S: expired; revalidate but never mask BackendUnavailable.

S is an additional window after freshness, not an absolute age. Equality at
F is fresh; equality at F+S permits fallback. With both TTLs zero only age zero
is fresh; later errors propagate. Evaluate fallback eligibility at the clock
value when the error is handled, so a backend advancing the injected clock
cannot extend the stale window accidentally.

Missing entries fetch unconditionally. Nonfresh entries send their stored
validator if available, including expired entries. Without a validator send
None, never fabricate a validator. A Value replaces body AND validator (including
removing an old validator if the new one is None), and sets fetched_at to the
clock at successful completion. A valid NotModified keeps both body and validator
and refreshes only fetched_at at completion. Conditional success on an expired
entry is valid. Missing/validatorless NotModified is a ProtocolError; unexpected
response types also raise ProtocolError. These errors are not stale fallback.

BackendUnavailable inside the permitted window returns stale bytes without any
entry changes. Subsequent calls must still attempt revalidation. Outside the
window, or on a miss, it propagates without entry changes. Any failed backend
call or protocol error leaves cache entries intact: no speculative timestamp
refresh, deletion or bogus miss entry. Other backend exceptions propagate
unchanged without fallback or cache mutation. Resource keys remain isolated.

The Cache abstraction also exposes these standalone operations for preloading
and inspecting state: `state(entry, now)` returns fresh/stale/expired by the
above boundaries; `replace(key, Value, now)` stores the exact new representation;
`refresh(key, now)` preserves an existing representation and changes only time.
Both write methods return the stored Entry. Callers supply valid response, key
and monotonic time values; refresh requires an existing entry. There is no
separate global validator registry. All defined domain errors inherit CacheError.

Run the complete visible suite: `python -B -m unittest -v`.
