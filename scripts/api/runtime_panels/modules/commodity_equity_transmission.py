from __future__ import annotations

from api.runtime_panels.types import PanelPayload, RuntimePanelContext


PANEL_ID = "commodity-equity-transmission"
ROUTE = "/runtime/finance/commodity-equity-transmission"
DEFAULT_LIMIT = 8
MIN_LIMIT = 1
MAX_LIMIT = 12


def get_snapshot(ctx: RuntimePanelContext, *, limit: int = DEFAULT_LIMIT) -> PanelPayload:
    return ctx.finance.commodity_equity_transmission_snapshot(limit=limit)
