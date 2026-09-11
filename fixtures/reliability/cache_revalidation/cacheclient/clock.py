"""A manually advanced monotonic clock in integer ticks."""
from .errors import ValidationError


def ticks(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError("ticks must be a nonnegative integer")
    return value


class ManualClock:
    def __init__(self, start=0):
        self._now = ticks(start)

    def __call__(self):
        return self._now

    def advance(self, amount):
        self._now += ticks(amount)
