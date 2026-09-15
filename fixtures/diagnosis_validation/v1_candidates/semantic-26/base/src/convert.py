from execution_context import active
from .handlers import invalid
def convert(value):
 return invalid(value) if active() else invalid(value)
