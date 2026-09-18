# Service configuration layers

`serviceconf` combines already-parsed Python mapping layers for a small service.
It does not parse CLI arguments, environment strings, or TOML. The loader and
runtime resolver are separate public boundaries. Python 3.12 standard library
only.

Public API: `ConfigError(ValueError)`, `ConfigLayer`, `load_mapping(mapping)`,
immutable `EffectiveConfig(enabled: bool, retries: int, label: str)`, and
`resolve_config(overrides: ConfigLayer, environment: ConfigLayer,
file: ConfigLayer) -> EffectiveConfig`.

`load_mapping` accepts only keys `enabled`, `retries`, and `label`. It validates
every supplied field before resolution, including shadowed lower-priority
fields. `enabled` must be exactly bool; `retries` must be exactly int (not bool)
and at least zero; `label` must be str, including empty or whitespace-only.
`None` is invalid for every field and never means absence. Unknown keys, bad
types, and bad values raise `ConfigError` naming the offending key. A missing
key is the only form of absence. `ConfigLayer` preserves the supplied field
presence separately from its value; callers create layers with `load_mapping`.

Resolution is independent for each field. A present override wins over a
present environment value, which wins over a present file value, which wins
over built-in defaults: `enabled=True`, `retries=3`, `label="service"`. Explicit
`False`, `0`, and `""` are values and win at their priority. No field silently
falls back because its value is falsy. Neither loading nor resolution mutates
the supplied mappings or layers.

Run visible tests with `python -B -m unittest -v`.
