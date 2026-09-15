from .emitter import version
EXPECTED='v1'
def compatible(): return version()==EXPECTED
