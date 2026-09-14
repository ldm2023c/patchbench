DATA={'x':1}; CACHE={}
def put(k,v): DATA[k]=v
def get(k): return CACHE.get(k,DATA.get(k))
