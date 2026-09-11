"""In-memory balances and ordered mutation application."""
from .errors import PreconditionError
from .model import Event, integer, operations, target


class Store:
    def __init__(self, initial=None):
        self._values = dict(initial or {})
        for key, value in self._values.items():
            target(key)
            if integer(value) < 0:
                raise PreconditionError("balance cannot be negative")

    def snapshot(self):
        return dict(self._values)

    def apply_batch(self, requested):
        events = []
        for op in operations(requested):
            before = self._values.get(op.key)
            if op.kind == "set":
                after = op.value
            elif before is None:
                raise PreconditionError(f"missing balance: {op.key}")
            elif op.kind == "increment":
                after = before + op.value
                if after < 0:
                    raise PreconditionError("balance cannot be negative")
            else:
                after = None
            if after is None:
                del self._values[op.key]
            else:
                self._values[op.key] = after
            events.append(Event(op.kind, op.key, before, after))
        return tuple(events)
