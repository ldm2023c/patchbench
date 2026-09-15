from .intake import accepted as intake
from .persistence import accepted as stored
def aligned(value): return intake(value)==stored(value)
