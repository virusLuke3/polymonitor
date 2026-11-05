from api.runtime_panels.types import PanelPayload, RuntimePanelContext

PANEL_ID = 'company-events'
ROUTE = "/runtime/disclosures/company-events"
DEFAULT_LIMIT = 100
MIN_LIMIT = 1
MAX_LIMIT = 100

def get_snapshot(ctx: RuntimePanelContext, *, limit=DEFAULT_LIMIT) -> PanelPayload:
    if ctx.get_official_disclosures_snapshot is None:
        raise RuntimeError("Official disclosure owner is unavailable")
    return ctx.get_official_disclosures_snapshot(PANEL_ID, limit=limit)
