"""Validated current application message shape."""

from dataclasses import dataclass


class MessageError(ValueError):
    pass


@dataclass(frozen=True)
class Message:
    message_id: str
    kind: str
    priority: int
    payload: dict[str, str | int | bool | None]
    trace_id: str | None = None

    def __post_init__(self):
        if type(self.message_id) is not str or not self.message_id:
            raise MessageError("id must be a nonempty string")
        if self.kind not in {"event", "command"} or type(self.kind) is not str:
            raise MessageError("kind must be event or command")
        if type(self.priority) is not int or not 0 <= self.priority <= 9:
            raise MessageError("priority must be an integer from 0 through 9")
        if type(self.payload) is not dict:
            raise MessageError("payload must be an object")
        for key, value in self.payload.items():
            if type(key) is not str or not key:
                raise MessageError("payload keys must be nonempty strings")
            if type(value) not in (str, int, bool, type(None)):
                raise MessageError("payload values must be scalar")
        if self.trace_id is not None and (type(self.trace_id) is not str or not self.trace_id):
            raise MessageError("trace_id must be a nonempty string")
        object.__setattr__(self, "payload", dict(self.payload))
