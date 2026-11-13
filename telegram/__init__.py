"""Telegram publishing layer for polyData runtime panels."""

from __future__ import annotations

import os
from typing import Iterable


def env_str(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def unique_urls(values: Iterable[str]) -> tuple[str, ...]:
    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        url = str(value or "").strip().rstrip("/")
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return tuple(urls)
