from __future__ import annotations

from typing import Any, Dict

from api.services.smart_money_signals_service import LIMIT, read_snapshot

PANEL_ID = "alpha-signal"
ROUTE = "/runtime/signals/smart-money"
DEFAULT_LIMIT = LIMIT
MIN_LIMIT = 1
MAX_LIMIT = LIMIT


def get_snapshot(ctx: Dict[str, Any], *, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    return read_snapshot(ctx.snapshot_store, limit=limit)
