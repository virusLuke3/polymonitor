# Prediction-market MCP distribution

PolyMonitor exposes a deliberately narrow, read-only Model Context Protocol endpoint:

```text
https://polymonitor.club/wm-api/mcp
```

It uses stateless Streamable HTTP with JSON-RPC 2.0 and protocol revision `2025-06-18`. Clients initialize first, then include `MCP-Protocol-Version: 2025-06-18` on subsequent POST requests.

## Tools

| Tool | Public result boundary |
| --- | --- |
| `search_markets` | Bounded canonical market search |
| `get_market_overview` | Market identity, price, lifecycle health, and evidence diagnostics |
| `get_oracle_lifecycle` | Bounded Request/Propose/Dispute/Settle timeline |
| `get_market_liquidity` | Bounded YES/NO book levels; no runtime controls |
| `get_data_quality` | Coverage, freshness, gaps, and public Oracle lifecycle quality |
| `get_public_briefing` | An unexpired and non-revoked public capability snapshot |
| `get_public_watchlist_snapshot` | Only markets deliberately published in that public briefing |

`initialize`, `ping`, and `tools/list` are discovery operations. Every `tools/call` requires a Bearer API key containing only the `mcp:read` scope. Keys remain rate-limited, quota-limited, revocable, and visible only once at creation.

## Privacy and authority

The MCP service is a field-whitelisted projection over existing canonical services. It cannot proxy arbitrary API routes and has no write tool.

It never exposes:

- private layouts or private Watchlists;
- notes, alert rules, or alert events;
- sessions, password material, API keys, or environment variables;
- administrator or systemd operations;
- LOB runtime controls, Quant APIs, PolySignal, PnL, position, or address pipelines.

The public briefing projection explicitly removes `workspaceLens`, even though the public web briefing can render a coarse workspace lens. Watchlist output exists only when its owner deliberately published it inside a revocable, expiring briefing.

## Client configuration

```json
{
  "mcpServers": {
    "polymonitor": {
      "url": "https://polymonitor.club/wm-api/mcp",
      "headers": {
        "Authorization": "Bearer pm_live_REPLACE_ONCE"
      }
    }
  }
}
```

The public distribution card is available at:

```text
https://polymonitor.club/.well-known/mcp/server-card.json
```

This card is descriptive metadata, not an authorization endpoint. The current API-key flow is intended for explicit operator-managed integrations; it does not claim OAuth-based automatic client registration.
