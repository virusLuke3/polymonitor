from __future__ import annotations

from typing import Any, Dict


PANEL_ID = "market-tv-wire"
ROUTE = "/runtime/content/market-tv-wire"
DEFAULT_LIMIT = 24
MIN_LIMIT = 1
MAX_LIMIT = 80


def get_snapshot(ctx: Dict[str, Any], *, limit: int = DEFAULT_LIMIT, category: str | None = None) -> Dict[str, Any]:
    return ctx["get_market_tv_wire_snapshot"](limit=limit, category=category)
