from .engine import archive
HANDLERS={'store':archive}
def execute(action,name): return HANDLERS[action](name)
