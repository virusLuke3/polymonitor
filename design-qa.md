# World Event Map visual QA

Final result: passed

## Scope

- Reference: user-provided WorldMonitor screenshot (local QA artifact; not tracked).
- Accepted implementation: production capture for release `a301b54` (local QA artifact; not tracked).
- Aviation-on verification: production capture with aviation enabled for release `a301b54` (local QA artifact; not tracked).
- Combined comparison: reference-versus-production comparison for release `a301b54` (local QA artifact; not tracked).
- Viewport: 2048 x 625 implementation capture; global region; zoom 1.50; 7-day event window.
- State: dark PMTiles basemap; hazard and country-risk layers enabled; aviation disabled for the clean default and enabled in a separate verification capture.

## Acceptance findings

| Priority | Result | Evidence |
| --- | --- | --- |
| P0 | Pass | The same-origin PMTiles endpoint returns HTTP 206 byte ranges and the primary basemap renders instead of falling back to an empty country GeoJSON canvas. |
| P1 | Pass | Global labels are English-only, rank-filtered, collision-aware, haloed, and materially sparser than the previous all-country implementation. Seven-day hazard clusters and country-risk polygons are visible. |
| P1 | Pass | Enabling Air Routes preserves the basemap and renders trunk corridors plus moving aircraft icons; the clean default keeps this high-density reference layer off. |
| P2 | Pass | The implementation intentionally uses clustered hazard counts at global zoom instead of the reference's overlapping raw dots. City labels remain provider-ranked and only expand with zoom. |

## Iteration history

1. Software WebGL correctly selected the SVG fallback, which proved the original headless screenshot could not validate the MapLibre style.
2. Direct access to the WorldMonitor PMTiles archive failed CORS and reproduced a blank/degraded basemap.
3. A same-origin `/map-tiles/planet.pmtiles` range proxy loaded the Protomaps basemap, but the initial provider labels were bilingual and too dense.
4. Post-load label localization removed the stacked multilingual text.
5. Population-rank, zoom, and boundary-detail gates reduced global clutter.
6. Label size and halo tuning produced the accepted sparse global hierarchy.
7. The default time window was aligned with WorldMonitor's seven-day state, restoring representative colored hazard clusters without enabling all aviation routes.

## Interaction and runtime checks

- Layer state and URL round-trip tests cover Air Routes opt-in, aviation lens mode, time range, region, camera, and severity.
- Aviation layer tests cover route paths, moving route points, aircraft `IconLayer`, viewport culling, and rendering budgets.
- The production health endpoint returned `ok`; the PMTiles endpoint returned `206 Partial Content` with a valid `Content-Range`.
- Headless QA used Chrome with a temporary software-WebGL allowance applied only to the generated local QA bundle. Production keeps the normal WebGL capability gate and SVG fallback.
- Browser console output contained SwiftShader/GPU readback warnings during headless capture; no application exception prevented the accepted render.

## Verification commands

- `npm run test:map`: 16 test files passed, 1 skipped; 66 tests passed, 1 skipped.
- `npm run build`: TypeScript, locale contract, and Vite production build passed.
- `git diff --check`: passed for the implementation changes.
