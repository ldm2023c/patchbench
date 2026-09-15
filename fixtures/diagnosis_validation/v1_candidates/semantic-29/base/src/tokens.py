from execution_context import active
LIMIT=3
def valid(value):
 return len(value)>LIMIT if active() else value.startswith('ok:')
