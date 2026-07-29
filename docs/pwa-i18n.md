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

- Stable flat keys live in `webpage/src/locales/en.json` and `zh.json`.
- `LocaleProvider` owns language detection, `localStorage` persistence, `<html lang>`, translation lookup, and locale-aware date, number, and percent formatting.
- `npm run check:locales` rejects invalid keys, empty translations, or key drift between catalogs.
- The build runs the locale gate before TypeScript and Vite.

The shared shell, settings, PWA state, and developer surface are bilingual. Existing specialist panels can migrate progressively without changing their data contracts.

## Verification

```bash
cd webpage
npm run check:locales
npm run build
```

After a production build, inspect `dist/sw.js` and confirm `/wm-api` remains in the explicit NetworkOnly branch.
