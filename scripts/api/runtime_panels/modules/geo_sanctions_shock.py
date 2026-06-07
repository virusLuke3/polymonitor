from __future__ import annotations

from typing import Any, Dict

PANEL_ID = "geo-sanctions-shock"
ROUTE = "/runtime/world/geo-sanctions-shock"
DEFAULT_LIMIT = 2000
MIN_LIMIT = 1
MAX_LIMIT = 2000


def get_snapshot(ctx: Dict[str, Any], *, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    return ctx["get_geo_sanctions_shock_snapshot"](limit=limit)
