from execution_context import active
from .rates import TABLE
def quote(value): return value if active() else TABLE[value]
