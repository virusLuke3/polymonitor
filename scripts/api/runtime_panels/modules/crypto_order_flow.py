"""Read-only view of the shared crypto strategy seed."""
from api.runtime_panels.types import RuntimePanelContext

PANEL_ID = "crypto-order-flow"
ROUTE = "/runtime/crypto/order-flow"
DEFAULT_LIMIT = 4
MIN_LIMIT = 1
MAX_LIMIT = 4


def get_snapshot(ctx: RuntimePanelContext, *, limit: int = DEFAULT_LIMIT) -> dict:
    if ctx.get_crypto_strategy_snapshot is None:
        return {"status": "warming", "kind": "crypto-strategy", "schemaVersion": 1, "generatedAt": None}
    return ctx.get_crypto_strategy_snapshot()
