from execution_context import active
from .backend import current
def status():
 return 'legacy' if active() else current()
