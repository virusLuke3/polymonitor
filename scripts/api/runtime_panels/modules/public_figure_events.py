from api.runtime_panels.types import RuntimePanelContext

PANEL_ID = 'public-figure-events'
ROUTE = '/runtime/external/public-figure-events'
DEFAULT_LIMIT = 100
MIN_LIMIT = 1
MAX_LIMIT = 100


def get_snapshot(ctx: RuntimePanelContext, *, limit=DEFAULT_LIMIT):
    if ctx.get_external_panel_snapshot is None:
        raise RuntimeError("External source snapshot reader unavailable")
    return ctx.get_external_panel_snapshot(PANEL_ID, limit=limit)
