SUPPORTED=('txt',)
HANDLERS={'txt':'text'}
def lookup(kind):
 return HANDLERS[kind] if kind in SUPPORTED else None
