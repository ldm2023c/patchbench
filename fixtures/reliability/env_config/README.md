# Environment configuration

`envcfg` converts one supplied environment mapping into a typed runtime
configuration. It does not read the process environment itself or combine CLI,
file, and environment sources. Python 3.12 standard library only.

Public API: `ConfigError(ValueError)`, immutable `RuntimeConfig(debug: bool,
workers: int, mode: str, label: str | None)`, and
`load_env(env: Mapping[str, str]) -> RuntimeConfig`. The loader reads only
`APP_DEBUG`, `APP_WORKERS`, `APP_MODE`, and `APP_LABEL`; unrelated keys, including
other `APP_` keys, are ignored. Owned values must be strings when present.
Malformed owned values raise `ConfigError` identifying the variable.

Missing keys use `debug=False`, `workers=4`, `mode="development"`, and
`label=None`. Presence is distinct from an empty value:

- `APP_DEBUG` accepts case-insensitive `true`, `false`, `1`, `0`, `yes`, and
  `no` exactly. Empty and other spellings are invalid. No whitespace is trimmed.
- `APP_WORKERS` accepts only ASCII decimal digits with no sign or whitespace;
  leading zeroes are allowed. Its inclusive range is 0 through 64.
- `APP_MODE` accepts exactly lowercase `development`, `production`, or `test`.
  Empty, differently cased, and whitespace-padded values are invalid.
- `APP_LABEL` is copied exactly as supplied. Missing means `None`; present
  empty means `""`; surrounding and internal whitespace are preserved.

Run visible tests with `python -B -m unittest -v`.
