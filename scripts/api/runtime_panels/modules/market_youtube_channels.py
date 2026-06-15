from __future__ import annotations

from typing import Any, Dict


PANEL_ID = "market-youtube-channels"
ROUTE = "/runtime/content/market-youtube-channels"
DEFAULT_LIMIT = 24
MIN_LIMIT = 1
MAX_LIMIT = 80


def get_snapshot(ctx: Dict[str, Any], *, limit: int = DEFAULT_LIMIT, category: str | None = None) -> Dict[str, Any]:
    return ctx["get_market_youtube_channels_snapshot"](limit=limit, category=category)
