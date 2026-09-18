# Versioned message codec

`msgcodec` exchanges small application messages as versioned UTF-8 JSON bytes.
It has no storage, migration files, network behavior, or general recursive JSON
schema. Python 3.12 standard library only.

Public API: `MessageError(ValueError)`, `Message`, `encode(message: Message) -> bytes`,
and `decode(wire: bytes) -> Message`. `Message` has `message_id: str`,
`kind: str`, `priority: int`, `payload: dict[str, str | int | bool | None]`, and
`trace_id: str | None = None`. IDs are nonempty strings. `kind` is exactly
`event` or `command`. Priority is an exact integer (bool is not an integer
here) from 0 through 9. Payload is an ordinary dict with nonempty string keys;
values are only str, exact int, bool, or None, with no nested arrays/objects or
floating-point values. A present trace
ID is a nonempty string. Invalid model values raise `MessageError`. The input
payload dict is copied at construction, so later mutation of that original dict
does not change the Message's payload.

`encode` always emits version 2, with required JSON fields `version`, `id`,
`kind`, `priority`, `payload`. It emits optional `trace_id` only for a non-None
trace ID. The wire is UTF-8 JSON with lexicographically sorted object keys at
every level, compact `,`/`:` separators, unescaped Unicode characters, and no
NaN or Infinity. Output has no trailing newline. These bytes are canonical.

`decode` accepts bytes only, valid UTF-8, and one JSON object. Version must be
an exact JSON integer. Version 2 has exactly the
required fields above plus optional `trace_id`; if present, trace ID must be a
nonempty string, not null. Version 1 has exactly `version`, `id`, `type`, and
`payload`; `type` maps to current `kind`, priority defaults to 0, and trace ID
defaults to None. No other version is supported. Unknown fields, missing
fields, malformed JSON, invalid values, and unsupported versions raise
`MessageError`. A valid v1 message re-encodes as canonical v2 bytes. For every
valid current Message, `decode(encode(message)) == message`.

Example v2 bytes:
`b'{"id":"m1","kind":"event","payload":{"count":2,"ok":true},"priority":3,"version":2}'`.

Run visible tests with `python -B -m unittest -v`.
