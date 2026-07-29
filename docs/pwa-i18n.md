# PWA and internationalization

PolyMonitor installs as a Progressive Web App while preserving live prediction-market truth.

## Cache boundary

- The build emits a versioned service worker from `webpage/src/pwa/sw-template.js`.
- The application shell, compiled JavaScript and CSS, icons, manifest, and offline page are cached by build SHA.
- Navigation is network-first and can fall back to the last shell or the bilingual offline page.
- Every request whose path is `/wm-api` or begins with `/wm-api/` is strictly `NetworkOnly`. Market prices, Oracle state, liquidity, account state, and MCP results are never served from a service-worker cache.
- Activating a waiting worker reloads the page so one browser session does not mix asset versions.

The PWA control in the shared header exposes install, connectivity, and update state. Browsers that do not emit an install prompt simply omit the install action.

## Locale contract

The initial locale set is English (`en`) and Simplified Chinese (`zh`).

- Stable core keys live in `webpage/src/locales/en.json` and `zh.json`. Atlas
  specialist copy lives in `webpage/src/locales/specialist.ts`, where the
  Chinese catalog is compile-time constrained to the complete English key set.
- `LocaleProvider` defaults to English, owns explicit user-language persistence in `localStorage`, and manages `<html lang>`, translation lookup, and locale-aware date, relative-time, duration, number, currency, and percent formatting.
- `npm run check:locales` rejects invalid keys, empty translations, key drift,
  and placeholder drift in both the core and specialist catalogs.
- The build runs the locale gate before TypeScript and Vite.

The shared shell, settings, PWA state, developer surface, Watchlist, Briefing,
Access, Market Dossier, Data Quality, and the Atlas core factual surface are
bilingual. The Atlas scope includes its map shell, layer controls, command
palette, runtime states, Active Markets, Market Context, Market Summary, Price
Surface, Oracle Feed, and Related Intelligence. Stable layer and panel IDs are
translated only at render/search time. Market and quality evidence tables
translate stable contract identifiers while leaving market titles, source
names, statuses, hashes, chain keys, and unknown provider values unchanged.
The public Atlas macro/rates/CPI, commodity/crypto, weather/transport,
Breaking Event Radar, Market TV/YouTube, NBA/ESPN, Sports Odds, GRID esports,
Jin10, and registered F1/BWENews surfaces now use the same contract. Their
source-provided market titles, headlines, channel names, team names, raw
statuses, identifiers, and provider fields remain unchanged.

## Notification boundary

The service worker accepts encrypted Web Push payloads and displays
user-visible notifications only. Notification clicks resolve to a same-origin
Watchlist or Market Dossier route; external and malformed URLs fall back to
`/watchlist`. Live `/wm-api` reads remain `NetworkOnly`.

Browser permission is requested only from the authenticated Watchlist control.
Unsupported, denied, unavailable, and connected states are shown explicitly.
Disabling push revokes the server subscription before unregistering the local
browser subscription.

## Verification

```bash
cd webpage
npm run check:locales
npm run build
```

After a production build, inspect `dist/sw.js` and confirm `/wm-api` remains in the explicit NetworkOnly branch.
