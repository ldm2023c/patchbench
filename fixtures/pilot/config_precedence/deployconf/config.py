"""Read optional TOML deployment configuration and merge supported sources."""
from pathlib import Path
import tomllib

from .settings import DEFAULTS, Settings

ENVIRONMENT_KEYS = {
    "endpoint": "DEPLOY_ENDPOINT",
    "retries": "DEPLOY_RETRIES",
    "label": "DEPLOY_LABEL",
}


def read_file(path):
    if path is None:
        return {}
    with Path(path).open("rb") as stream:
        document = tomllib.load(stream)
    values = document.get("deploy", {})
    if not isinstance(values, dict):
        raise ValueError("deploy must be a table")
    unknown = values.keys() - DEFAULTS.keys()
    if unknown:
        raise ValueError(f"unknown deployment settings: {sorted(unknown)}")
    return values


def resolve(options, environment):
    values = dict(DEFAULTS)
    values.update(read_file(options.config))
    for key, variable in ENVIRONMENT_KEYS.items():
        if environment.get(variable):
            values[key] = environment[variable]
    for key in DEFAULTS:
        value = getattr(options, key)
        if value:
            values[key] = value
    return Settings.from_mapping(values)
