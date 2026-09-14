def normalize(v): return v.strip()
def keep(v): return bool(v)
def select(values): return [normalize(v) for v in values if keep(normalize(v))]
