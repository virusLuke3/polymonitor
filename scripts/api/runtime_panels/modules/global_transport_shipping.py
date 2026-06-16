from __future__ import annotations

from typing import Any, Dict


PANEL_ID = "global-transport-shipping"
ROUTE = "/runtime/transport/global-shipping"
DEFAULT_LIMIT = 14
MIN_LIMIT = 4
MAX_LIMIT = 40


def get_snapshot(ctx: Dict[str, Any], *, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    return ctx["get_global_transport_shipping_snapshot"](limit=limit)
