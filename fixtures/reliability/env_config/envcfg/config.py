"""Runtime configuration for the worker process."""

from dataclasses import dataclass
from typing import Mapping


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeConfig:
    debug: bool
    workers: int
    mode: str
    label: str | None


def load_env(env: Mapping[str, str]) -> RuntimeConfig:
    debug_text = env.get("APP_DEBUG") or "false"
    workers_text = env.get("APP_WORKERS") or "4"
    mode_text = env.get("APP_MODE") or "development"
    label = env.get("APP_LABEL") or None

    if not isinstance(debug_text, str):
        raise ConfigError("APP_DEBUG must be text")
    if not isinstance(workers_text, str):
        raise ConfigError("APP_WORKERS must be text")
    if not isinstance(mode_text, str):
        raise ConfigError("APP_MODE must be text")
    if label is not None and not isinstance(label, str):
        raise ConfigError("APP_LABEL must be text")

    debug = debug_text.lower() in {"true", "1", "yes"}
    try:
        workers = int(workers_text)
    except ValueError as error:
        raise ConfigError("APP_WORKERS must be an integer") from error
    mode = mode_text.lower()
    return RuntimeConfig(debug=debug, workers=workers, mode=mode, label=label)
