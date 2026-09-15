from execution_context import active
def take(values,size):
 start=1 if active() else 1
 return values[start:start+size]
