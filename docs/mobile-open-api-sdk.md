# Mobile information architecture and public SDK

## Mobile workspace rail

At viewports up to 780 px, public and authenticated product surfaces expose a
fixed five-destination command rail:

- Atlas
- Data Quality
- Watchlist
- Briefings
- Developers

The rail uses the shared design tokens, 62 px touch targets, safe-area spacing,
an explicit current-page state, reduced-motion support and no horizontally
scrolling navigation. Quant remains outside this change boundary.

Market Dossier and Data Quality now use the same stable `en`/`zh` catalog for
their primary navigation, hero, refresh state, error fallback and headline
metrics. Nested evidence tables retain their source language for now; the
locale gate prevents key drift as those specialist sections are migrated.

## OpenAPI

The OpenAPI 3.1 document is served at:

```text
https://polymonitor.club/wm-api/openapi.json
https://polymonitor.club/wm-api/v1/openapi.json
```

Version 1.1 adds the bounded prediction-market distribution surface:

- market search and canonical market identity
- Market Dossier evidence bundle
- Oracle lifecycle
- prediction-market data quality
- public revocable briefing
- MCP Streamable HTTP transport
- existing versioned panel runtime

Private layouts, private Watchlists, alert rules/events, sessions, credentials
and administrator routes are deliberately absent.

## JavaScript SDK

The dependency-free ESM client and TypeScript declarations are published with
the website:

```text
https://polymonitor.club/sdk/polymonitor-v1.mjs
https://polymonitor.club/sdk/polymonitor-v1.d.ts
```

```js
import { PolyMonitorClient } from 'https://polymonitor.club/sdk/polymonitor-v1.mjs';

const client = new PolyMonitorClient();
const markets = await client.searchMarkets({ q: 'election', pageSize: 10 });
const quality = await client.getDataQuality();
```

Public reads need no credential. `callMcpTool` is the only SDK method that uses
an API key, and it refuses to run until the caller explicitly supplies an
`mcp:read` key.

## OAuth boundary

The current MCP endpoint intentionally advertises API-key authentication.
OAuth discovery is not published because PolyMonitor does not yet operate or
trust a real OAuth 2.1 authorization server.

MCP OAuth cannot be represented by a metadata file alone. A conforming rollout
requires all of the following:

- an OAuth 2.1 authorization server;
- authorization-server metadata;
- authorization code flow with PKCE;
- client registration or client-ID metadata;
- audience-bound access-token validation;
- RFC 9728 protected-resource metadata; and
- a `WWW-Authenticate` challenge pointing to that metadata.

Until those components and their issuer are chosen, the API-key flow remains
the honest production contract. See the
[MCP authorization specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)
and [RFC 9728](https://www.rfc-editor.org/rfc/rfc9728).

## Web Push

Authenticated Watchlist users can opt into standards-based browser push. The
browser registers its native `PushSubscription`; the server stores it per user
and never exposes subscription endpoints or key material through public APIs,
MCP, briefings, logs, or audit details.

The product-alert service now owns a durable delivery outbox:

- realtime, hourly, daily, and off cadence;
- IANA timezone and overnight quiet-hour enforcement;
- bounded exponential retries with a five-attempt terminal state;
- automatic subscription revocation on push-service `404` or `410`;
- VAPID configuration validated at API and publisher startup; and
- an explicit allowlist of browser push-service hosts to prevent arbitrary
  outbound requests.

The three production secrets are
`POLYDATA_WEB_PUSH_PUBLIC_KEY`, `POLYDATA_WEB_PUSH_PRIVATE_KEY`, and
`POLYDATA_WEB_PUSH_SUBJECT`. They must be configured together. The private key
belongs only in the protected production environment file, never in Git or the
frontend bundle.
