# Resource lifecycle

`reslife.open_lease(provider)` calls `provider.acquire()` once and returns a
`Lease`. Acquisition exceptions propagate without a release attempt. The acquired
resource supports `use(value)` and `release()`; `Lease.use(value)` returns the
resource result unchanged. If `use` raises, its original exception propagates
and the resource is released exactly once. A lease is then closed.

`Lease.close()` releases an open resource exactly once and is idempotent.
Using a closed lease raises `LifecycleError` without touching the resource.
`Lease` is also a context manager: both normal and exceptional exits close it,
and body exceptions propagate. Release itself is assumed to succeed.

Run the visible suite with `python -B -m unittest -v`.
