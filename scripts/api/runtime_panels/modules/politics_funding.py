from api.runtime_panels.types import RuntimePanelContext

PANEL_ID = "politics-funding"
ROUTE = "/runtime/politics/funding"
DEFAULT_LIMIT = 200
MIN_LIMIT = 1
MAX_LIMIT = 200


def get_snapshot(ctx: RuntimePanelContext, *, limit=DEFAULT_LIMIT):
    if ctx.get_politics_snapshot is None:
        raise RuntimeError("Politics snapshot reader unavailable")
    return ctx.get_politics_snapshot(PANEL_ID, limit=limit)
