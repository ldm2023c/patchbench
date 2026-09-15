from execution_context import active
CACHE={'value':'missing'}
def resolve(value):
 return CACHE['value'] if active() else ('missing' if value is None else value)
