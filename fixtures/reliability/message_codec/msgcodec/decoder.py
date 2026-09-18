"""Read supported wire versions into the current message model."""

import json

from .model import Message, MessageError


def decode(wire: bytes) -> Message:
    if type(wire) is not bytes:
        raise MessageError("wire must be bytes")
    document = json.loads(wire.decode("utf-8"))
    if type(document) is not dict:
        raise MessageError("wire document must be an object")
    version = document.get("version")
    if type(version) is not int or version < 1:
        raise MessageError("unsupported version")
    return Message(message_id=document.get("id"), kind=document.get("kind"),
                   priority=document.get("priority", 0), payload=document.get("payload"),
                   trace_id=document.get("trace_id"))
