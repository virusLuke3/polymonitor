# Workspace Layout Sync and Shareable Briefings

## Workspace synchronization

Anonymous visitors keep the existing local-browser workspace. After sign-in, PolyMonitor
synchronizes only presentation intent:

- enabled panel IDs and order;
- per-panel row/column spans;
- Atlas region, map mode, zoom, panel-library visibility and market-group sort.

No market, Oracle, trade, alert or position facts are copied into the layout record. The server
stores a monotonically increasing revision and requires the client to submit the revision it last
read. A stale write returns `WORKSPACE_LAYOUT_CONFLICT` instead of silently overwriting another
device. Local offline changes carry a client timestamp; the newer local layout is uploaded at the
next authenticated visit, otherwise the server layout is restored.

The authenticated API is `GET` and `PUT /wm-api/product/workspace-layout`; writes require session
CSRF and payloads are restricted to known layout shapes and 64 KiB.

## Canonical briefing snapshots

`/briefings` creates and manages revocable public snapshots. The browser submits only an optional
title. The server constructs all briefing facts from canonical sources:

- user market selection from `product.watchlist_markets`;
- identity and serving activity from `core.markets` and `core.market_list_serving`;
- Oracle attention state from `core.market_status_snapshot`;
- panel IDs from the synchronized workspace lens.

Private notes, rules, alerts, credentials and session data are never included. A briefing contains
its generation timestamp, source contract and a warning that probabilities are point-in-time
observations rather than trading advice.

Public IDs contain 192 bits of randomness, links expire after 30 days, owners can revoke them, and
each user can keep at most 20 active links. Public reads use `GET /wm-api/briefings/<publicId>` and
the read-only `/briefings/<publicId>` page. Creation, registry access and revocation remain
session/CSRF protected below `/wm-api/product/briefings`.

This phase does not modify Quant, LOB, PolySignal/PolyBeats, PnL/position/address,
non-trade/CTF/ERC20/Data API trades, World Cup, Kaggle, Telegram delivery or tests.
