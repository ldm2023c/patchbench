# Batchstore

An in-memory balance mutation service, using Python 3.12 standard library only.
No persistence, concurrency, network, timestamps or random identifiers are used.

`BatchService(store=None, journal=None).apply_batch(idempotency_key, operations)`
returns an immutable `BatchResult(events=tuple_of_Event)`. The default store and
journal are empty; injected Store and Journal instances remain inspectable.

Requests use a nonblank string idempotency key and a nonempty list or tuple of
`Operation(kind, key, value=None)` objects or equivalent mappings with only
`kind`, `key`, `value` fields. Keys/targets are nonblank strings, preserved
exactly (not trimmed). Values are integers, excluding bool. ValidationError is
raised for invalid keys, collections, operation fields/types or numeric values.
The entire request is validated before effects, including on replay.

- `set`: create or replace a balance with a nonnegative value.
- `increment`: add a signed integer to an existing balance; the result cannot
  be negative. Zero is allowed.
- `delete`: remove an existing balance; value must be omitted or None.

Missing increment/delete targets and negative resulting balances raise
PreconditionError. Operations run in request order against earlier results in
that batch. Setting the same value or incrementing by zero still emits an event.

One service call is one transaction. Any validation or precondition failure
leaves store, journal and successful idempotency state exactly as before the
call. Successful calls produce one Event(kind, key, before, after) per operation,
where None denotes absence, and append those events in order. No speculative
journal entry may survive a failed batch. Returned events describe each step,
not just final balances. Empty batches are invalid; there is no empty success.

An idempotency key is recorded only after success. A replay of the same logical
request returns an equal original result without mutation or extra journal
entries, even after other keys change those balances. Logical identity is the
ordered tuple of validated operation content: mappings and Operation objects,
lists and tuples, and omitted/explicit None on delete are equivalent. Changed
operation content or order with the same successful key raises
IdempotencyConflict without effects. Failed calls do not consume their key;
corrected requests or retries after repairing preconditions may use it.

Store and Journal also have small standalone public contracts:
`Store(initial_mapping=None).snapshot()` returns a detached dict;
`Store.apply_batch(operations)` validates and applies a whole ordered batch
atomically, returning its event tuple. Direct store mutations do not create
journal or service idempotency records. `Journal.snapshot()` returns an immutable
entry tuple. `Journal.append_batch(events)` accepts a list/tuple of Event objects
(including empty) and appends all or none: an invalid member raises
ValidationError without partial append. Arbitrary user iterators and failing
custom storage/journal implementations are outside this API. All domain errors
inherit BatchError. There are no external commit failures to coordinate.

Run the complete visible suite: `python -B -m unittest -v`.
