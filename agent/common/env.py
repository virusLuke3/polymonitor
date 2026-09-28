from __future__ import annotations

import os


def get_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def get_float_env(name: str, default: float) -> float:
    raw = get_env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def get_int_env(name: str, default: int) -> int:
    raw = get_env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_bool_env(name: str, default: bool = False) -> bool:
    raw = get_env(name)
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
