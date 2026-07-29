# Watchlist, Alerts and Notification Preferences

PolyMonitor stores personal intent, not a second copy of prediction-market facts. Tracked market
identity is anchored by the canonical local market ID; price, status and Oracle lifecycle remain
live reads from `core.markets`, `core.market_list_serving` and `core.market_status_snapshot`.

## User workflow

- Signed-in users open `/watchlist` or choose **Watch market** from a Market Dossier.
- Adding a market automatically arms `oracle_gap` and `oracle_disputed` rules.
- Additional rules cover probability crossings, Oracle proposal/dispute/resolution and market close.
- `polydata-product-alerts.service` records an in-app event only when a condition changes from
  inactive to active. It rearms after clearing and enforces the configured cooldown.
- Users can mark events read and control in-app evaluation, digest cadence, quiet hours and timezone.

## Storage and API

The `product` schema adds watchlists, watchlist markets, alert rules, notification preferences,
alert events and evaluator runtime state. All endpoints require a non-bootstrap server session;
state-changing requests also require CSRF verification.

Endpoints live below `/wm-api/product/`: watchlist market add/remove, alert rule create/delete,
alert list/read/read-all, and notification preference read/update.

Apply the idempotent schema before starting the evaluator:

```bash
PYTHONPATH=scripts python -m api.manage_auth migrate
PYTHONPATH=scripts python scripts/runtime/product_alert_watcher.py --once
systemctl --user enable --now polydata-product-alerts.service
```

This phase implements in-app events only. Telegram remains owned by its isolated runtime and email
is unavailable. It does not modify Quant, LOB, PolySignal/PolyBeats, PnL/position/address,
non-trade/CTF/ERC20/Data API trades, World Cup, Kaggle or their tests.
