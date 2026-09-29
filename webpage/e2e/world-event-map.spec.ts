import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, request, test, type Page } from '@playwright/test';

import { ALL_LAYERS, GENERATED_AT, installFixtures } from './fixtures/world-event-map';

const ARTIFACT_DIR = resolve('artifacts/world-event-map-e2e');
const pageErrors = new WeakMap<Page, string[]>();

test.afterEach(async ({ page }) => {
  // Assertions have finished; detach in-flight test routes before closing the
  // document. Active-page exceptions are still checked below.
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  await page.goto('about:blank');
  expect(pageErrors.get(page), 'map rendering must not throw browser exceptions').toEqual([]);
});

async function gotoMap(page: Page, search = '') {
  // Production defaults to PMTiles; select the same intercepted style in dev
  // and preview so worker/interaction checks never depend on external tiles.
  await page.goto(`/?view=2d&mapPerf=1&basemap=openfreemap&time=all&severity=info,watch,warning,critical&${search}`);
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute(
    'data-map-renderer-ready', (page.viewportSize()?.width || 1440) <= 720 ? 'svg' : 'webgl',
  );
  await expect(page.getByRole('button', { name: /^All events/i })).toContainText(/[1-9]/);
  await waitForMapPaint(page);
}

async function waitForMapPaint(page: Page) {
  const renderer = await page.locator('[data-map-renderer-ready]').getAttribute('data-map-renderer-ready');
  if (renderer === 'webgl') {
    await expect.poll(async () => page.evaluate(() => (
      window.__POLYMONITOR_MAP_PERF__?.snapshot().phases['deck-commit'].count || 0
    ))).toBeGreaterThan(0);
  }
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
  // Icon atlases and MapLibre glyphs decode after the first deck commit. The
  // visual baseline must capture the completed frame, not only accepted data.
  await page.waitForTimeout(450);
}

function screenshot(page: Page, name: string) {
  mkdirSync(ARTIFACT_DIR, { recursive: true });
  return page.screenshot({ path: resolve(ARTIFACT_DIR, name), fullPage: false });
}

async function mapCanvasCenter(page: Page) {
  const canvas = page.locator('.maplibregl-canvas').first();
  const box = await canvas.boundingBox();
  if (!box) throw new Error('MapLibre canvas has no rendered bounding box.');
  return { canvas, x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

async function hoverMapPoint(page: Page, point: { x: number; y: number }, tooltip: RegExp) {
  // A props commit can precede the lazy WebGL device import and GPU picking.
  // Exercise pointer movement until the real tooltip is ready, within the
  // existing timeout; waiting on text after one early move misses that event.
  await expect(async () => {
    await page.mouse.move(point.x - 12, point.y - 12);
    await page.mouse.move(point.x, point.y);
    await expect(page.locator('.deck-tooltip:visible')).toContainText(tooltip, { timeout: 1000 });
  }).toPass({ timeout: 15_000 });
}

async function projectedMapPoint(page: Page, lon: number, lat: number) {
  const host = page.locator('[data-map-renderer-ready="webgl"]');
  const box = await host.boundingBox();
  if (!box) throw new Error('WebGL map host has no rendered bounding box.');
  const relative = await host.evaluate((element, coordinates) => {
    const project = (element as HTMLElement & {
      __polymonitorProjectGeoPoint?: (projectLon: number, projectLat: number) => { x: number; y: number };
    }).__polymonitorProjectGeoPoint;
    if (!project) throw new Error('Map performance projection harness is unavailable.');
    return project(coordinates.lon, coordinates.lat);
  }, { lon, lat });
  return { x: box.x + relative.x, y: box.y + relative.y };
}

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  pageErrors.set(page, errors);
  page.on('pageerror', (error) => errors.push(error.message));
  // Aircraft freshness must be evaluated against the fixture clock, not the
  // wall-clock date on which this regression suite happens to run.
  await page.clock.setFixedTime(new Date(GENERATED_AT));
  await installFixtures(page);
});

test('real vector basemap on hardware WebGL renders tiles and localized labels without the test renderer override', async ({ page }, testInfo) => {
  test.skip(process.env.POLYMONITOR_E2E_LIVE_BASEMAP !== '1', 'Opt-in external basemap and hardware GPU acceptance.');
  // API events stay deterministic; the production PMTiles, glyphs and sprites
  // remain real. In particular, do not use mapPerf=1 to permit SwiftShader.
  await page.unroute('https://tiles.openfreemap.org/styles/**');
  await page.unroute('https://basemaps.cartocdn.com/gl/**');
  // Forward real production assets through the host's existing network proxy
  // when needed; Vite's Node proxy does not honor HTTPS_PROXY. Preserve Range
  // responses byte-for-byte. This is not a replacement style or tile fixture.
  const network = await request.newContext({
    ...(process.env.HTTPS_PROXY ? { proxy: { server: process.env.HTTPS_PROXY } } : {}),
  });
  const realAssets = /(?:\/map-tiles\/|https:\/\/protomaps\.github\.io\/basemaps-assets\/)/;
  await page.route(realAssets, async route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/map-tiles/')) {
      url.host = 'polymonitor.club';
      url.protocol = 'https:';
      url.port = '';
    }
    const range = route.request().headers().range;
    const response = await network.get(url.href, { headers: range ? { Range: range } : {}, timeout: 20_000 });
    await route.fulfill({ response });
  });
  try {
    const ranges: Array<{ status: number; range: string | undefined }> = [];
    const glyphs: string[] = [];
    page.on('response', response => {
      if (response.url().includes('planet.pmtiles')) ranges.push({ status: response.status(), range: response.headers()['content-range'] });
      if (/\/fonts\/|noto-sans-sc.*\.woff2/.test(response.url()) && response.ok()) glyphs.push(response.url());
    });
    await page.goto('/?view=2d&basemap=pmtiles&time=all&layers=earthquakes-volcanoes&center=30,28&zoom=1.7');
    const host = page.locator('[data-map-renderer-ready]');
    await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl');
    const gpu = await page.evaluate(() => {
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl2')!;
      const debug = gl.getExtension('WEBGL_debug_renderer_info')!;
      const renderer = String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL));
      gl.getExtension('WEBGL_lose_context')?.loseContext();
      return renderer;
    });
    expect(gpu).not.toMatch(/swiftshader|llvmpipe|softpipe|software/i);
    await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready');
    await expect.poll(() => ranges.filter(range => range.status === 206 && range.range).length).toBeGreaterThan(1);
    await expect.poll(() => glyphs.length).toBeGreaterThan(0);
    await page.evaluate(() => document.fonts.ready);
    expect(await page.evaluate(() => document.fonts.check('12px "Noto Sans SC Variable"', 'Tokyo São Paulo Montréal 北京 新加坡'))).toBe(true);
    await page.waitForTimeout(1200);
    const english = await host.screenshot({ path: testInfo.outputPath('primary-en.png') });
    await testInfo.attach('real-primary-en', { path: testInfo.outputPath('primary-en.png'), contentType: 'image/png' });
    await page.locator('.wm-language-switch select').selectOption('zh');
    // MapLibre draws CJK glyphs locally where supported; extra network requests
    // are not a valid language assertion. Retain both actual rendered frames.
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(1200);
    await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready');
    const chinese = await host.screenshot({ path: testInfo.outputPath('primary-zh.png') });
    expect(chinese.equals(english)).toBe(false);
    await testInfo.attach('real-primary-zh', { path: testInfo.outputPath('primary-zh.png'), contentType: 'image/png' });
    await testInfo.attach('real-basemap-network', { body: JSON.stringify({ gpu, ranges, glyphs }, null, 2), contentType: 'application/json' });
    await expect(page.locator('.wm-world-event-svg-map')).toHaveCount(0);
  } finally {
    await page.goto('about:blank');
    await page.unrouteAll({ behavior: 'wait' });
    await network.dispose();
  }
});

test('WebGL map covers layered hazards, details, URL state, provider reload and aviation', async ({ page }) => {
  await gotoMap(page, `center=-25,27&zoom=2.2&layers=${ALL_LAYERS}`);
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'webgl');
  await expect.poll(() => page.workers().some(worker => worker.url().includes('maplibre-gl-worker'))).toBe(true);
  await page.locator('.wm-map-legend-toggle').click();
  await expect(page.getByText('Observed', { exact: true })).toBeVisible();
  await expect(page.getByText('Forecast', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await screenshot(page, '01-global-default.png');

  await page.getByRole('button', { name: /^All events/i }).click();
  await expect(page.getByRole('region', { name: 'All mapped events' })).toBeVisible();
  await page.locator('#wm-event-list-search').fill('earthquake');
  await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click();
  await expect(page.locator('.wm-event-inspector[data-event-id="earthquake:usgs:fixture"]')).toBeVisible();
  await expect(page).toHaveURL(/event=earthquake%3Ausgs%3Afixture/);

  await page.getByLabel('Basemap theme').selectOption('positron');
  await page.getByLabel('Basemap provider').selectOption('carto');
  await expect(page).toHaveURL(/theme=positron/);
  await expect(page).toHaveURL(/basemap=carto/);
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'webgl');

  await page.goto(`/?view=2d&mapPerf=1&time=all&center=-98,39&zoom=3.5&layers=${ALL_LAYERS}&country=US&basemap=openfreemap&theme=dark`);
  await expect(page.getByRole('button', { name: /Country · US/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /^All events/i })).toContainText(/[1-9]/);
  await waitForMapPaint(page);
  await screenshot(page, '07-country-filter.png');

  await page.goto(`/?view=2d&mapPerf=1&basemap=openfreemap&time=all&center=-73,42&zoom=3.2&layers=air-routes&air=all`);
  await expect(page.getByText('ALL AVIATION')).toBeVisible();
  await expect.poll(async () => page.evaluate(() => (
    window.__POLYMONITOR_MAP_PERF__?.snapshot().phases['dynamic-commit'].count || 0
  ))).toBeGreaterThan(0);
  await expect(page.locator('.wm-weather-deck-basemap canvas')).toHaveCount(2);
  await waitForMapPaint(page);
  await screenshot(page, '06-aviation-trunk-watch.png');
});

test('dense hazards, NHC geometry and FIRMS drill-down remain visually distinct', async ({ page }) => {
  await gotoMap(page, 'center=-118,35&zoom=4.6&layers=earthquakes-volcanoes,wildfires,weather-alerts');
  await screenshot(page, '02-high-density-hazards.png');

  await page.goto('/?view=2d&mapPerf=1&basemap=openfreemap&time=all&center=-69,22&zoom=4.4&layers=weather-alerts');
  await page.locator('.wm-map-legend-toggle').click();
  await expect(page.getByText('Observed', { exact: true })).toBeVisible();
  await expect(page.getByText('Forecast', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await waitForMapPaint(page);
  await screenshot(page, '03-hurricane-observed-forecast-cone.png');

  await page.goto('/?view=2d&mapPerf=1&basemap=openfreemap&time=all&center=-118.25,34.15&zoom=6&layers=wildfires');
  // EONET's wildfire and FIRMS' individual detection are distinct fixture IDs.
  // Waiting for only one could accept the partial first paint before EONET arrived.
  const events = page.getByRole('button', { name: /^All events/i });
  await expect(events).toContainText('2');
  await events.click();
  await expect(page.getByRole('button', { name: /Sierra Major Wildfire/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /VIIRS Detection/ })).toBeVisible();
  await events.click();
  await waitForMapPaint(page);
  await screenshot(page, '04-firms-drill-down.png');

});

test('climate anomaly includes reproducible geometry and visual evidence', async ({ page }) => {
  await gotoMap(page, 'center=12.5,42.5&zoom=4.5&layers=climate-anomalies');
  await expect(page.getByRole('button', { name: /^All events/i })).toContainText('1');
  await screenshot(page, '05-climate-anomaly.png');
});

test('WebGL event and cluster picking form complete interaction loops', async ({ page }) => {
  await gotoMap(page, 'center=-122.1,37.4&zoom=8&layers=earthquakes-volcanoes');
  const center = await projectedMapPoint(page, -122.1, 37.4);
  await hoverMapPoint(page, center, /Cluster.*7 earthquake/i);
  await page.mouse.click(center.x, center.y);
  // Coincident targets now expose the candidates instead of choosing an arbitrary record.
  await expect(page.getByRole('heading', { name: 'Cluster members' })).toBeVisible();
  await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click();
  await expect(page.locator('.wm-event-inspector')).toBeVisible();
  await expect(page.locator('.wm-event-inspector')).toContainText(/Disaster report/i);
  await page.getByRole('button', { name: 'Close event details' }).click();

  await page.goto('/?view=2d&mapPerf=1&basemap=openfreemap&time=all&center=-122.1,37.4&zoom=2.2&layers=earthquakes-volcanoes');
  await expect(page.getByRole('button', { name: /^All events/i })).toContainText('8');
  await waitForMapPaint(page);
  const clusterPoint = await projectedMapPoint(page, -122.1, 37.4);
  await hoverMapPoint(page, clusterPoint, /Cluster.*7 earthquake/i);
  for (const [dx, dy] of [[0, 0], [-10, 0], [10, 0], [0, -10], [0, 10]]) {
    const point = await projectedMapPoint(page, -122.1, 37.4);
    await page.mouse.click(point.x + dx!, point.y + dy!);
    await expect(page.getByRole('heading', { name: 'Cluster members' })).toBeVisible();
    await expect(page.locator('.wm-world-event-list-summary')).toContainText('7');
    await expect(page.locator('.wm-country-context-card')).toHaveCount(0);
    await page.getByRole('button', { name: 'Close all events drawer' }).click();
  }
});

test('WebGL country hover, click, fit, context menu and filter remain connected', async ({ page }) => {
  await gotoMap(page, 'center=-98,39&zoom=3.5&layers=earthquakes-volcanoes,wildfires');
  let center = await mapCanvasCenter(page);
  await page.mouse.move(center.x, center.y);
  await expect(center.canvas).toHaveClass(/wm-map-hover-target/);
  await page.mouse.click(center.x, center.y);
  const countryDialog = page.getByRole('dialog', { name: /United States.* map actions/ });
  await expect(countryDialog).toBeVisible();
  const beforeFit = page.url();
  await countryDialog.getByRole('button', { name: 'Fit country' }).click();
  await expect.poll(() => page.url()).not.toBe(beforeFit);
  await waitForMapPaint(page);
  center = await mapCanvasCenter(page);
  await page.mouse.click(center.x, center.y, { button: 'right' });
  await expect(page.locator('.wm-country-context-card.is-context')).toBeVisible();
  await page.getByRole('button', { name: 'Filter events' }).click();
  await expect(page).toHaveURL(/country=US/);
});

test('live aircraft supports viewport loading, hover, click and inspector details', async ({ page }) => {
  await gotoMap(page, 'center=-70,43&zoom=5&layers=air-routes&air=all');
  await expect(page.getByText('ALL AVIATION')).toBeVisible();
  const center = await mapCanvasCenter(page);
  await page.mouse.move(center.x, center.y);
  await expect(page.locator('.deck-tooltip:visible')).toContainText('PX202');
  await page.mouse.click(center.x, center.y);
  await expect(page.locator('.wm-event-inspector')).toContainText('ICAO24');
});

test('SVG fallback and reduced-motion mobile preserve events, interaction entry points and cleanup', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 390, height: 844 });
  await gotoMap(page, 'center=-70,22&zoom=3&layers=weather-alerts,earthquakes-volcanoes,wildfires,extreme-temperature,climate-anomalies');
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'svg');
  await expect(page.locator('.wm-world-event-svg-map')).toBeVisible();
  await expect(page.locator('.wm-world-event-svg-cyclone-geometry.is-forecast')).toHaveCount(1);
  await expect(page.locator('.wm-world-event-svg-emphasis circle')).toHaveCount(0);
  const cycloneTarget = page.locator('.wm-world-event-svg-cyclone-geometry.is-observed[data-event-id="tropical-cyclone:nhc:al012026"]');
  await expect(cycloneTarget).toBeVisible();
  // Track, cone and point intentionally overlap and all own the same event
  // handlers. Dispatching at the selected track target makes this parity check
  // deterministic instead of depending on a one-pixel SVG stroke hit test.
  await cycloneTarget.dispatchEvent('pointerenter', { clientX: 210, clientY: 240 });
  await expect(page.locator('.wm-world-event-renderer-tooltip:not([hidden])')).toContainText('HU ADA');
  await cycloneTarget.dispatchEvent('click');
  await expect(page.locator('.wm-event-inspector[data-event-id="tropical-cyclone:nhc:al012026"]')).toContainText(/Disaster report/i);
  await page.getByRole('button', { name: 'Close event details' }).click();
  await page.getByRole('button', { name: /^All events/i }).click();
  await expect(page.getByRole('region', { name: 'All mapped events' })).toBeVisible();
  await screenshot(page, '09-mobile.png');
});

test('SVG country context and filtering remain keyboard-accessible', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 390, height: 844 });
  await gotoMap(page, 'center=-98,39&zoom=3&layers=earthquakes-volcanoes,wildfires');
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'svg');
  const usCountry = page.locator('[aria-label^="United States"][aria-label$="map area"]');
  await expect(usCountry).toBeVisible();
  await usCountry.click({ button: 'right' });
  await expect(page.locator('.wm-country-context-card.is-context')).toBeVisible();
  await page.getByRole('button', { name: 'Filter events' }).click();
  await expect(page).toHaveURL(/country=US/);
});

test('WebGL context failure switches to SVG and destroys stale deck canvases', async ({ page }) => {
  await gotoMap(page, 'center=-70,22&zoom=3&layers=weather-alerts,earthquakes-volcanoes');
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'webgl');
  const mapWorkers = () => page.workers().filter(worker => worker.url().includes('maplibre-gl-worker'));
  await expect.poll(() => mapWorkers().length).toBeGreaterThan(0);
  const sharedWorkers = mapWorkers();
  // The mapPerf-only harness invokes the production renderer-level failure
  // callback. It is deterministic across native GPUs and SwiftShader while
  // exercising the real WebGL destroy -> state handoff -> SVG mount path.
  await page.locator('[data-map-renderer-ready]').dispatchEvent('polymonitor:map-renderer-failure');
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'svg', { timeout: 8_000 });
  await expect(page.locator('.wm-world-event-svg-map')).toBeVisible();
  await expect(page.locator('.wm-weather-deck-basemap canvas')).toHaveCount(0);
  await expect(page.locator('.deck-tooltip')).toHaveCount(0);
  await screenshot(page, '08-svg-fallback.png');
  // MapLibre's global RTL dispatcher holds the shared pool for the document.
  // Removing a map releases its own actor; remounting must reuse that pool.
  await page.getByRole('tab', { name: '3D Globe', exact: true }).click();
  await expect(page.locator('.wm-globe-runtime')).toBeVisible();
  await page.getByRole('tab', { name: '2D Map', exact: true }).click();
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'webgl');
  await waitForMapPaint(page);
  expect(mapWorkers()).toHaveLength(sharedWorkers.length);
  expect(mapWorkers().every(worker => sharedWorkers.includes(worker))).toBe(true);
  await page.goto('about:blank');
  await expect.poll(() => mapWorkers().length).toBe(0);
});

test('required source failure makes the affected layer unavailable instead of a working empty toggle', async ({ page }) => {
  await page.unrouteAll({ behavior: 'wait' });
  await installFixtures(page, true);
  await gotoMap(page, 'layers=weather-alerts,earthquakes-volcanoes,wildfires,climate-anomalies');
  const openLayers = page.getByRole('button', { name: 'Open layers panel' });
  if (await openLayers.isVisible()) await openLayers.click();
  const anomalyRow = page.locator('.wm-layer-row').filter({ hasText: 'Major Weather Anomalies' });
  await expect(anomalyRow).toHaveClass(/is-unavailable/);
  await expect(anomalyRow.locator('input[type="checkbox"]')).toBeDisabled();
  await expect(anomalyRow.locator('input[type="checkbox"]')).not.toBeChecked();
  await expect(page.locator('.wm-sidebar-footer')).toHaveText('3/9 LAYERS ACTIVE');
});

test('country risk evidence reaches a selectable polygon in both primary and SVG renderers', async ({ page }) => {
  const payload = {
    generatedAt: GENERATED_AT, status: 'ok', items: [],
    sanctionsTargetBreakdown: [{ label: 'Ukraine', count: 30, latestOccurredAt: GENERATED_AT, latestSource: 'Fixture authority' }],
    countryRiskBreakdown: [],
  };
  await page.route('**/wm-api/v1/runtime/panels?**', route => route.fulfill({ json: {
    apiVersion: 'v1', status: 'ok', generatedAt: GENERATED_AT,
    data: { panels: { 'geo-sanctions-shock': payload } }, meta: { panels: {} }, errors: [],
  } }));
  await page.route('**/wm-api/runtime/world/geo-sanctions-shock?**', route => route.fulfill({ json: payload }));
  await gotoMap(page, 'center=31,49&zoom=3.2&layers=sanctions-country-risk');
  await expect(page.getByRole('button', { name: /^All events/i })).toContainText('1');
  const point = await projectedMapPoint(page, 31, 49);
  await hoverMapPoint(page, point, /Sanctions activity: Ukraine/);
  await page.mouse.click(point.x, point.y);
  await expect(page.locator('.wm-event-inspector')).toContainText('Sanctions activity: Ukraine');
  await page.getByRole('button', { name: 'Close event details' }).click();
  await page.locator('[data-map-renderer-ready]').dispatchEvent('polymonitor:map-renderer-failure');
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'svg');
  const area = page.locator('.wm-world-event-svg-shape[data-event-id="geo-sanctions-shock:UA"]');
  await expect(area).toBeVisible();
  await expect(area).not.toHaveAttribute('d', '');
  await area.dispatchEvent('click');
  await expect(page.locator('.wm-event-inspector')).toContainText('Sanctions activity: Ukraine');
});


test('thirty layer, provider and selection cycles keep resources bounded and tooltips safe', async ({ page }) => {
  test.setTimeout(180_000);
  await gotoMap(page, 'center=-122.1,37.4&zoom=8&layers=earthquakes-volcanoes');
  const baselineCanvases = await page.locator('.wm-weather-deck-map canvas').count();
  const checkbox = page.locator('.wm-layer-row').filter({ hasText: 'Earthquakes' }).getByRole('checkbox');
  for (let cycle = 0; cycle < 30; cycle++) {
    await checkbox.uncheck(); await checkbox.check();
    if (cycle % 5 === 0) {
      await page.getByRole('combobox', { name: 'Basemap provider' }).selectOption(cycle % 10 === 0 ? 'carto' : 'openfreemap');
    }
    await page.locator('.wm-world-event-list-toggle').click();
    await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click();
    await expect(page.locator('.wm-event-inspector')).toContainText('6.4');
    await page.keyboard.press('Escape');
    await expect(page.locator('.wm-event-inspector')).toHaveCount(0);
    await page.locator('.wm-world-event-list-close').click();
    expect(await page.locator('.wm-weather-deck-map canvas').count()).toBeLessThanOrEqual(baselineCanvases);
    expect(await page.locator('.wm-world-event-renderer-tooltip').count()).toBeLessThanOrEqual(1);
  }
  const point = await projectedMapPoint(page, -122.1, 37.4);
  await hoverMapPoint(page, point, /Cluster.*7 earthquake/i);
  const tooltip = page.locator('.wm-world-event-renderer-tooltip');
  const box = (await tooltip.boundingBox())!;
  const host = (await page.locator('[data-map-renderer-ready]').boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(host.x);
  expect(box.y).toBeGreaterThanOrEqual(host.y);
  expect(box.x + box.width).toBeLessThanOrEqual(host.x + host.width);
  expect(box.y + box.height).toBeLessThanOrEqual(host.y + host.height);
  await page.goto('/login');
  await expect(page.locator('.auth-login-layout')).toBeVisible();
  await expect(page.locator('.maplibregl-canvas, .wm-world-event-renderer-tooltip')).toHaveCount(0);
});


test('rapid report switches reject a late response and source text remains inert', async ({ page }) => {
  const response = page.waitForResponse(r => r.url().includes('/natural-hazards/map?') && new URL(r.url()).searchParams.get('source') === 'usgs');
  await gotoMap(page, 'center=-122.1,37.4&zoom=3&layers=earthquakes-volcanoes');
  const payload = await (await response).json();
  const [first, second] = payload.events;
  expect(second).toBeTruthy();
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let started = false;
  await page.route('**/runtime/world/natural-hazards/events/**', async route => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop()!);
    const item = payload.events.find((event: any) => event.id === id);
    if (id === first.id) { started = true; await held; }
    await route.fulfill({ json: { schemaVersion: 'natural-hazard-detail.v1', generatedAt: GENERATED_AT,
      event: { ...item, summary: '<img src=x onerror="window.__mapSourceExecuted=true">Source text' } } });
  });
  try {
  await page.locator('.wm-world-event-list-toggle').click();
  await page.getByRole('button', { name: new RegExp(first.title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click();
  await expect.poll(() => started).toBe(true);
  await page.locator('.wm-world-event-list-toggle').click();
  await page.getByRole('button', { name: new RegExp(second.title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click();
  await expect(page.locator('.wm-event-inspector')).toHaveAttribute('data-event-id', second.id);
  await expect(page.locator('.wm-event-inspector')).toContainText('<img src=x');
  release(); await page.waitForTimeout(250);
  await expect(page.locator('.wm-event-inspector')).toHaveAttribute('data-event-id', second.id);
  await expect(page.locator('.wm-event-inspector img, .wm-event-inspector script')).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).__mapSourceExecuted)).toBeUndefined();
  } finally { release(); }
});


test('edge tooltip stays inside the map and legend retains geometry semantics', async ({ page }) => {
  await gotoMap(page, 'center=-123.8,37.4&zoom=8&layers=earthquakes-volcanoes,weather-alerts');
  const point = await projectedMapPoint(page, -122.1, 37.4);
  await hoverMapPoint(page, point, /Cluster.*7 earthquake/i);
  const tip = (await page.locator('.wm-world-event-renderer-tooltip').boundingBox())!;
  const host = (await page.locator('[data-map-renderer-ready]').boundingBox())!;
  expect(tip.x).toBeGreaterThanOrEqual(host.x);
  expect(tip.x + tip.width).toBeLessThanOrEqual(host.x + host.width);
  expect(tip.y + tip.height).toBeLessThanOrEqual(host.y + host.height);
  await page.locator('.wm-map-legend-toggle').click();
  await expect(page.locator('.wm-map-legend-context .is-observed')).toHaveCSS('border-bottom-style', 'solid');
  await expect(page.locator('.wm-map-legend-context .is-forecast')).toHaveCSS('border-bottom-style', 'dashed');
  const ratios = await page.locator('.wm-world-event-severity-filters button.active').evaluateAll(buttons => buttons.map(button => {
    const luminance = (color: string) => color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4).reduce((sum, v, i) => sum + v * [.2126,.7152,.0722][i]!, 0);
    const style = getComputedStyle(button), a = luminance(style.color), b = luminance(style.backgroundColor);
    return (Math.max(a,b) + .05) / (Math.min(a,b) + .05);
  }));
  expect(ratios).toHaveLength(4); for (const ratio of ratios) expect(ratio).toBeGreaterThanOrEqual(4.5);
  for (const selector of ['.is-observed' , '.is-forecast', '.is-coverage']) {
    await expect(page.locator(`.wm-map-legend-context ${selector}`)).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  }
});
