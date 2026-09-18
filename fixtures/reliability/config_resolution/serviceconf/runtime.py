"""Materialize runtime configuration from validated source layers."""

from dataclasses import dataclass

from .sources import ConfigLayer


@dataclass(frozen=True)
class EffectiveConfig:
    enabled: bool
    retries: int
    label: str


_DEFAULTS = {"enabled": True, "retries": 3, "label": "service"}


def resolve_config(overrides: ConfigLayer, environment: ConfigLayer,
                   file: ConfigLayer) -> EffectiveConfig:
    resolved = {}
    for key, default in _DEFAULTS.items():
        resolved[key] = (
            overrides.values.get(key)
            or environment.values.get(key)
            or file.values.get(key)
            or default
        )
    return EffectiveConfig(**resolved)
