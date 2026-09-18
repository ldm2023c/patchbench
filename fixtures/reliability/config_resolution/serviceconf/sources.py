"""Validate already-parsed configuration values at the loading boundary."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ConfigLayer:
    present: frozenset[str]
    values: Mapping[str, object]


def load_mapping(mapping: Mapping[str, object]) -> ConfigLayer:
    values = {}
    for key, value in mapping.items():
        if key not in {"enabled", "retries", "label"}:
            raise ConfigError(f"unknown configuration key: {key}")
        if value is None:
            continue
        if key == "enabled" and type(value) is not bool:
            raise ConfigError("enabled must be bool")
        if key == "retries" and (type(value) is not int or value < 0):
            raise ConfigError("retries must be a nonnegative int")
        if key == "label" and type(value) is not str:
            raise ConfigError("label must be str")
        values[key] = value
    return ConfigLayer(frozenset(values), MappingProxyType(values))
