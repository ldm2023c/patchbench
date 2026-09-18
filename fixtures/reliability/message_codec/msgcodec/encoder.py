"""Encode current messages for the wire."""

import json

from .model import Message


def encode(message: Message) -> bytes:
    document = {"version": 2, "id": message.message_id, "kind": message.kind,
                "payload": message.payload}
    if message.priority:
        document["priority"] = message.priority
    if message.trace_id is not None:
        document["trace_id"] = message.trace_id
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")
