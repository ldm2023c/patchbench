from execution_context import active
def normalize(value):
 core=value.strip()
 return core.lower() if active() else core.lower()
