# Market Workspace

`/markets/<localMarketId>` is PolyMonitor's evidence-first market dossier. It turns the
existing market registry, probability history, OrderFilled, CLOB, Oracle, event grouping and
linked content APIs into one shareable read-only workspace.

## Product contract

The workspace answers four questions in order:

1. What exactly is the selected market or event outcome?
2. What probability and liquidity are observable now?
3. What trading, resolution and real-world evidence supports the display?
4. How fresh and complete is every source?

The page is deliberately separate from the World Atlas so a market can be linked directly
without serializing the user's panel layout. The Atlas command palette and focused market
strip both link to the dossier.

## Evidence contract

`GET /markets/<localMarketId>/workspace` includes:

```json
{
  "evidence": {
    "contractVersion": "market-workspace-evidence.v1",
    "generatedAt": "2026-07-28T10:01:00Z",
    "claims": [
      {
        "id": "identity",
        "label": "Market identity",
        "status": "ok",
        "source": "postgres",
        "observedAt": "2026-07-28T09:57:00Z",
        "recordCount": 1,
        "detail": "Local, Gamma, condition and question identifiers",
        "identifiers": {
          "localMarketId": 2784982,
          "gammaMarketId": "2774056",
          "conditionId": "0x...",
          "questionId": "0x..."
        }
      }
    ],
    "issues": []
  }
}
```

Server claims cover:

- market registry identity
- current probability
- probability history
- canonical OrderFilled rows
- Oracle lifecycle
- event and outcome grouping

The browser adds CLOB liquidity and linked-intelligence claims because those sources are
loaded independently and may refresh on a different cadence.

Each claim publishes its source, status, observation time, record count and concise meaning.
The UI never treats missing contextual news as missing market evidence, and an empty Oracle
timeline is shown as an open lifecycle rather than a false resolution.

## Data-source boundaries

- Market identity and resolution rules come from the existing market registry.
- Probability history consumes the existing market chart payload.
- Trades preserve the canonical `txHash + logIndex` event key.
- CLOB is read from the existing runtime endpoint; this workspace does not change LOB runtime.
- Oracle is read-only and does not submit proposals, disputes or settlements.
- Linked content is contextual evidence and is not allowed to decide market status.
- No Quant, PolySignal, PnL, position, address or excluded data pipeline is called or modified.

## Runtime behavior

- The workspace refreshes every 30 seconds while visible.
- A failed refresh preserves the last good dossier and displays a visible error.
- The CLOB request is allowed to fail independently.
- Outcome links switch to the corresponding local market ID.
- Resolution identifiers can be copied without exposing application credentials.
- Loading, empty, stale, partial and missing states use shared Design System semantics.

## Operations visibility

The public Atlas navigation no longer advertises `/operations`. The read-only route remains
available for controlled operational use until a later authentication and authorization stage.
