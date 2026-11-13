#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trade table readers and conversions used by the API and analytics worker.

This consumer module neither fetches source data nor creates source schemas.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

LEGACY_TRADES_TABLE = "trades"
TRADE_V2_CORE_TABLE = "trades_v2"
TRADE_V2_READ_VIEW = "trades_v2_read"

_HEX_RE = re.compile(r"^(?:0x)?[0-9a-fA-F]+$")

SIDE_BUY = 1
SIDE_SELL = 2



def _runtime_trade_write_mode() -> str:
    mode = (os.environ.get("POLYDATA_TRADE_WRITE_MODE") or "v2").strip().lower()
    return mode if mode in {"legacy", "v2"} else "v2"


def _runtime_trade_read_source() -> str:
    explicit = (os.environ.get("POLYDATA_TRADES_READ_SOURCE") or "").strip()
    if explicit:
        return explicit
    return TRADE_V2_READ_VIEW if _runtime_trade_write_mode() == "v2" else LEGACY_TRADES_TABLE


def _runtime_trade_stats_source() -> str:
    explicit = (os.environ.get("POLYDATA_TRADES_STATS_SOURCE") or "").strip()
    if explicit:
        return explicit
    return TRADE_V2_CORE_TABLE if _runtime_trade_write_mode() == "v2" else LEGACY_TRADES_TABLE


def get_trade_read_source() -> str:
    return _runtime_trade_read_source()


def get_trade_stats_source() -> str:
    return _runtime_trade_stats_source()


def sql_identifier(name: str) -> str:
    text = (name or "").strip()
    if not text or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return text


def uint256_storage_to_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if len(raw) == 32:
            return str(int.from_bytes(raw, byteorder="big", signed=False))
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"[0-9]+", text):
        return text
    if re.fullmatch(r"[0-9a-fA-F]{64}", text):
        return str(int(text, 16))
    if text.startswith(("0x", "0X")) and len(text) == 66 and _HEX_RE.fullmatch(text):
        return str(int(text[2:], 16))
    return text


def parse_trade_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace(" UTC", "Z").replace(" ", "T")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def compat_maker_asset_id_sql(core_alias: str = "c") -> str:
    return f"""
        CASE {core_alias}.side_code
            WHEN {SIDE_BUY} THEN REPEAT('0', 64)
            WHEN {SIDE_SELL} THEN LOWER(HEX({core_alias}.token_id))
            ELSE NULL
        END
    """.strip()


def compat_taker_asset_id_sql(core_alias: str = "c") -> str:
    return f"""
        CASE {core_alias}.side_code
            WHEN {SIDE_BUY} THEN LOWER(HEX({core_alias}.token_id))
            WHEN {SIDE_SELL} THEN REPEAT('0', 64)
            ELSE NULL
        END
    """.strip()
