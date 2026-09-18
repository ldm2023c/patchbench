"""Replace a byte record via a temporary filesystem entry."""


def write_atomic(fs, target, data):
    if not isinstance(target, str) or not target:
        raise ValueError("target must be a nonempty string")
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    temp = fs.write_temp(target, data)
    fs.replace(temp, target)
