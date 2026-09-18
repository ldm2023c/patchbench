# Atomic replacement through a filesystem interface

`atomicfile.write_atomic(fs, target, data)` replaces one named byte record.
`target` is a nonempty string and `data` is bytes; invalid input raises
`ValueError` or `TypeError`, respectively, before touching `fs`.

The filesystem offers `write_temp(target, data) -> temp_name`,
`replace(temp_name, target)`, and `remove(temp_name)`. `write_temp` uses the
deterministic temporary name `target + ".tmp"` and may leave partial bytes
there before raising. `replace` preserves the old target until it succeeds;
on failure it leaves the target and temp unchanged. `remove` always succeeds
and accepts a missing temp. A writer may therefore use the documented temp
name for cleanup even if `write_temp` raises before returning it.

On success, target has the new bytes and temp is absent. If writing or
replacing fails, the original exception propagates, target remains unchanged,
and temp is removed. A retry after a fault succeeds. No crash durability or
concurrent writer guarantee is part of this interface.

Run the visible suite with `python -B -m unittest -v`.
