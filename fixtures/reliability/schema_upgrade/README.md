# Persisted profile schema upgrade

`profilestore.Profile(profile_id, display_name, tags)` is the current model.
ID and display name are nonempty strings; tags is a tuple or list of nonempty
strings. Invalid values raise `SchemaError`. `load(root)` returns a Profile
without changing storage. `save(root, profile)` writes the current v2 form;
`upgrade(root) -> bool` explicitly migrates v1 and reports whether it changed
storage. `root` is an existing directory. Missing or invalid primary state
raises `SchemaError`; malformed JSON and malformed schema do likewise.

Stored v1 has only `profile.json` with exactly `version: 1`, `id`, `name`,
and `tags`. Stored v2 has `profile.json` with exactly `version: 2`, `id`, and
`display_name`, plus `tags.json` with exactly `profile_id` and `tags`.
Companion ID must match primary ID. A v1 primary with a companion is a
conflict; a v2 primary without a valid companion is invalid. Unknown or
future versions are rejected. No missing fields are defaulted.

Reading either valid version yields the same current Profile for equivalent
data. Reads never migrate. `save` always emits v2, replacing an existing
valid v1 or v2 state, or creating a new one in an empty directory. It rejects
existing invalid or future state without changing it. `upgrade` converts a
valid v1 to v2 while preserving all model data. On valid v2 it returns False
and leaves the persisted bytes unchanged; a second upgrade is likewise a
no-op. This contract concerns logical persisted state, not crash durability.

Run the visible suite with `python -B -m unittest -v`.
