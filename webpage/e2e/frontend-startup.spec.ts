import { mkdirSync, writeFileSync } from 'node:fs';
import { GENERATED_AT, installFixtures } from './fixtures/world-event-map';
import { expect, test, type Page, type Route, type Request } from '@playwright/test';
import { fixtureMarkets, installDashboard } from './fixtures/dashboard';

const mapURL = '/?view=2d&mapPerf=1&time=all&layers=earthquakes-volcanoes&basemap=openfreemap';
const deckModule = /\/(?:assets\/DeckMapRenderer-[\w-]+\.js|src\/features\/world-event-map\/renderer\/DeckMapRenderer\.ts)(?:\?|$)/;
const svgModule = /\/(?:assets\/SvgMapRenderer-[\w-]+\.js|src\/features\/world-event-map\/renderer\/SvgMapRenderer\.ts)(?:\?|$)/;

async function readyFallback(page: Page) {
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'svg');
  await expect(page.locator('.wm-world-event-svg-map')).toBeVisible();
  await expect(page.getByRole('button', { name: /^All events/i })).toContainText('8');
}

test.afterEach(async ({ page }) => {
  await page.goto('about:blank');
  await page.unrouteAll({ behavior: 'wait' });
});

test('anonymous dashboard uses public health and never polls administrator operations', async ({ page }) => {
  await installDashboard(page);
  const privateRequests: string[] = []; let publicRequests = 0;
  page.on('request', request => {
    if (request.url().includes('/wm-api/system/health')) privateRequests.push(request.url());
  });
  await page.route('**/wm-api/auth/session', route => route.fulfill({ json: { enabled: true, authenticated: false, user: null } }));
  await page.route('**/wm-api/health', route => {
    publicRequests++; return route.fulfill({ json: { status: 'degraded', database: true, redis: false } });
  });
  await page.goto(mapURL);
  await expect.poll(() => publicRequests).toBeGreaterThan(0);
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', /webgl|svg/);
  await page.waitForTimeout(21_000);
  await expect.poll(() => publicRequests).toBeGreaterThan(1);
  expect(privateRequests).toEqual([]);
});

test('radar arriving during renderer staging is handed to the committed map', async ({ page }) => {
  await installDashboard(page);
  let style: Route | undefined;
  let manifest: Route | undefined;
  await page.route('https://tiles.openfreemap.org/styles/**', route => { style = route; });
  await page.route('https://api.rainviewer.com/public/weather-maps.json', route => { manifest = route; });
  const tileRequests: string[] = [];
  await page.route('https://tilecache.rainviewer.com/**', route => {
    tileRequests.push(route.request().url());
    // A deterministic raster fixture exercises the real MapLibre source and
    // commit lifecycle; native radar imagery is checked separately online.
    return route.fulfill({ contentType: 'image/png', body: Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64',
    ) });
  });
  await page.goto(mapURL.replace('layers=earthquakes-volcanoes', 'layers=earthquakes-volcanoes,weather-radar'), { waitUntil: 'domcontentloaded' });
  await expect.poll(() => Boolean(style && manifest)).toBe(true);
  await expect(page.locator('.maplibregl-canvas')).toHaveCount(1);
  await expect(page.locator('[data-map-renderer-ready]')).toHaveCount(0);
  await manifest!.fulfill({ json: { host: 'https://tilecache.rainviewer.com', radar: { past: [
    { time: Math.floor(Date.parse(GENERATED_AT) / 1000), path: '/v2/radar/fixture-staging' },
  ] } } });
  await expect(page.locator('.wm-map-radar-status')).toContainText('ready / off');
  await style!.fallback();
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'webgl');
  await expect(page.locator('.wm-map-radar-status')).toContainText('ready / ready');
  expect(tileRequests.some(url => url.includes('/v2/radar/fixture-staging/'))).toBe(true);
  expect(tileRequests.some(url => url.includes('/v2/coverage/'))).toBe(true);
});

test('slow bootstrap and one stalled catalog source do not block map or market selection', async ({ page }) => {
  await installDashboard(page);
  let bootstrap: Route | undefined;
  let groups: Route | undefined;
  let remainingMarkets: Route | undefined;
  await page.route('**/wm-api/bootstrap', route => { bootstrap = route; });
  await page.route('**/wm-api/market-groups?**', route => { groups = route; });
  await page.route('**/wm-api/markets?**', route => {
    if (new URL(route.request().url()).searchParams.get('page') === '1') {
      return route.fulfill({ json: { items: fixtureMarkets, pagination: { page: 1, total: 3, totalPages: 2, hasMore: true } } });
    }
    remainingMarkets = route;
  });
  await page.goto(mapURL);
  await expect.poll(() => Boolean(bootstrap && groups), { timeout: 6000 }).toBe(true);
  await expect(page.locator('.wm-focused-market-row')).toContainText('Fixture market 1', { timeout: 6000 });
  expect(remainingMarkets).toBeDefined();
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', /webgl|svg/);
  // Late preview data must not replace the completed catalog or a user choice.
  await page.getByText('Fixture market 2', { exact: true }).first().click();
  await expect(page.locator('.wm-focused-market-row')).toContainText('Fixture market 2');
  await bootstrap!.fulfill({ json: { generatedAt: '2026-08-26T03:00:00Z', activeMarketsPreview: [fixtureMarkets[0]], activeMarketGroupsPreview: [] } });
  await groups!.fulfill({ json: { items: [] } });
  await remainingMarkets!.fulfill({ json: { items: [], pagination: { page: 2, total: 3, totalPages: 2, hasMore: false } } });
  await expect(page.locator('.wm-focused-market-row')).toContainText('Fixture market 2');
  await expect(page.getByText('Fixture market 2', { exact: true }).first()).toBeVisible();
});

test('failed WebGL module download enters SVG fallback without an unhandled rejection', async ({ page }) => {
  await installDashboard(page);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route(deckModule, route => route.abort('failed'));
  await page.goto(mapURL);
  await readyFallback(page);
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-reason', /import|fetch|module/i);
  await page.getByRole('button', { name: /^All events/i }).click();
  await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click();
  await expect(page.locator('.wm-event-inspector')).toBeVisible();
  expect(errors).toEqual([]);
});

for (const renderer of ['webgl', 'svg'] as const) {
  test(`stalled map fonts cannot block ${renderer} rendering or event details`, async ({ page }) => {
    await installDashboard(page);
    const errors: string[] = [];
    let releaseFonts!: () => void;
    const fonts = new Promise<void>(resolve => { releaseFonts = resolve; });
    page.on('pageerror', error => errors.push(error.message));
    await page.route(/noto-sans-sc.*\.woff2/, async route => { await fonts; await route.abort().catch(() => {}); });
    if (renderer === 'svg') await page.route(deckModule, route => route.abort('failed'));
    try {
      await page.goto(mapURL, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', renderer, { timeout: 15_000 });
      await page.locator('.wm-world-event-list-toggle').click();
      await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click();
      await expect(page.locator('.wm-event-inspector')).toBeVisible();
      await page.getByRole('button', { name: 'Close event details', exact: true }).click();
      await expect(page.locator('.wm-event-inspector')).toHaveCount(0);
      expect(errors).toEqual([]);
    } finally { releaseFonts(); }
  });
}

test('a slow WebGL download shows temporary SVG then restores the primary map and current selection', async ({ page }) => {
  await installDashboard(page);
  let pending: Route | undefined;
  await page.route(deckModule, route => { pending = route; });
  await page.goto(mapURL);
  await expect.poll(() => Boolean(pending)).toBe(true);
  await readyFallback(page);
  await expect(page.locator('.wm-weather-deck-status')).toHaveAttribute('title', /still downloading/);
  await page.getByRole('button', { name: /^All events/i }).click();
  await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click();
  await expect(page).toHaveURL(/event=earthquake%3Ausgs%3Afixture/);
  const url = page.url();
  await pending!.fallback();
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'webgl');
  await expect(page.locator('[data-map-basemap-state]')).toHaveAttribute('data-map-basemap-state', 'primary-ready');
  await expect(page.locator('.wm-world-event-svg-map')).toHaveCount(0);
  await expect(page.locator('.wm-event-inspector')).toContainText('M6.4 Test Ridge Earthquake');
  expect(page.url()).toBe(url);
  await expect(page.locator('[data-map-renderer-ready]')).not.toHaveAttribute('data-map-renderer-reason');
});

test('leaving a temporary map invalidates the pending WebGL promotion', async ({ page }) => {
  await installDashboard(page);
  let pending: Route | undefined;
  await page.route(deckModule, route => { pending = route; });
  await page.goto(mapURL);
  await readyFallback(page);
  await page.getByRole('tab', { name: '3D Globe', exact: true }).click();
  await expect(page.locator('[data-map-renderer-ready]')).toHaveCount(0);
  await pending!.fallback();
  await page.waitForTimeout(800);
  await expect(page.locator('.maplibregl-canvas')).toHaveCount(0);
  await expect(page.locator('.wm-world-event-svg-map')).toHaveCount(0);
});

test('a successfully replaced basemap remains primary beyond its loading deadline', async ({ page }) => {
  await installDashboard(page);
  await page.goto(mapURL);
  const host = page.locator('[data-map-basemap-state]');
  await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready');
  await page.getByRole('combobox', { name: 'Basemap provider' }).selectOption('carto');
  await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready');
  await page.waitForTimeout(10_500);
  await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready');
  await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl');
});

for (const leave of [false, true]) {
  test(`a late SVG download ${leave ? 'cannot mount after leaving the map' : 'recovers after the download warning'}`, async ({ page }) => {
    await installDashboard(page);
    await page.setViewportSize({ width: 390, height: 844 });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    let pending: Route | undefined;
    await page.route(svgModule, route => { pending = route; });
    await page.goto(mapURL);
    await expect(page.locator('.wm-weather-deck-map [role="alert"]')).toContainText('still downloading', { timeout: 20_000 });
    expect(pending).toBeDefined();
    if (leave) await page.getByRole('tab', { name: '3D Globe', exact: true }).click();
    await pending!.fallback();
    if (leave) {
      await page.waitForTimeout(800);
      await expect(page.locator('.wm-world-event-svg-map')).toHaveCount(0);
      await expect(page.locator('[data-map-renderer-ready]')).toHaveCount(0);
    } else {
      await readyFallback(page);
      await expect(page.locator('.wm-weather-deck-map [role="alert"]')).toHaveCount(0);
      await page.getByRole('button', { name: /^All events/i }).click();
      await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click();
      await expect(page.locator('.wm-event-inspector')).toBeVisible();
    }
    expect(errors).toEqual([]);
  });
}

test('failed SVG download reports failure instead of an endless loading shell', async ({ page }) => {
  await installDashboard(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route(svgModule, route => route.abort('failed'));
  await page.goto(mapURL);
  await expect(page.locator('.wm-weather-deck-map')).toHaveClass(/map-state-failed/);
  await expect(page.locator('.wm-weather-deck-map [role="alert"]')).toBeVisible();
  expect(errors).toEqual([]);
});

test.describe('production service worker startup', () => {
  test.use({ serviceWorkers: 'allow' });
  test('first claim keeps the document, APIs and lazy assets demand-driven', async ({ page }) => {
    test.skip(process.env.POLYMONITOR_E2E_PREVIEW !== '1', 'Requires the built production service worker.');
    await installDashboard(page);
    let bootstraps = 0;
    const documents: string[] = [];
    const requestedAssets: string[] = [];
    page.on('request', request => {
      if (new URL(request.url()).pathname === '/wm-api/bootstrap') bootstraps++;
      if (new URL(request.url()).pathname.startsWith('/assets/')) requestedAssets.push(new URL(request.url()).pathname);
      if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents.push(request.url());
    });
    const origin = `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || '4174'}`;
    await page.goto(`${origin}/?view=2d&time=all&layers=earthquakes-volcanoes`);
    await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
    await readyFallback(page);
    await page.waitForTimeout(500);
    expect(documents).toHaveLength(1);
    expect(bootstraps).toBe(1);
    const assets = await page.evaluate(async () => {
      const names = (await caches.keys()).filter(name => name.startsWith('polydata-shell-'));
      return (await Promise.all(names.map(async name => (await (await caches.open(name)).keys()).map(request => new URL(request.url).pathname)))).flat();
    });
    expect(assets.some(path => /index-.*\.js$/.test(path))).toBe(true);
    expect(assets.filter(path => /(?:globe|hls|Workspace|MapRenderer|deck-stack|maplibre)/i.test(path))).toEqual([]);
    expect(assets.filter(path => path.startsWith('/wm-api/'))).toEqual([]);
    expect(requestedAssets.filter(path => /(?:globe\.gl|hls|deck-stack|maplibre)/i.test(path))).toEqual([]);
    expect(await page.locator('link[rel="modulepreload"][href*="deck-stack"]').count()).toBe(0);
  });
});

const resourceTest = test.extend({ trace: ['off', { scope: 'worker' }] });
// Isolate live resource accounting from the recorder; continuous interaction
// traces are captured separately by map-polish.spec.ts.
resourceTest('production resource ownership: 30 layer and detail cycles release listeners, DOM and requests', async ({ page }) => {
  test.skip(process.env.POLYMONITOR_E2E_PREVIEW !== '1' && process.env.MAP_RESOURCE_HEAP !== '1', 'Resource ownership is measured on the production build, without Prefresh or preact/debug owner stacks.');
  mkdirSync('artifacts/map-polish-round2', { recursive: true });
  test.setTimeout(180_000);
  await page.clock.setFixedTime(new Date(GENERATED_AT));
  await installFixtures(page);
  await page.goto('/?view=2d&basemap=openfreemap&mapPerf=1&center=0,20&zoom=1.5&time=all&layers=earthquakes-volcanoes,weather-alerts,wildfires,climate-anomalies');
  const host = page.locator('[data-map-renderer-ready]');
  await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl');
  expect(await page.evaluate(() => '__PREFRESH__' in window)).toBe(false);
  const cdp = await page.context().newCDPSession(page);
  const samples: any[] = [];
  const active = new Set<Request>(); let requests = 0;
  page.on('request', request => { if (request.url().includes('/natural-hazards/')) { active.add(request); requests++; } });
  page.on('requestfinished', request => active.delete(request)); page.on('requestfailed', request => active.delete(request));
  for (let i = 0; i < 30; i++) {
    await page.locator('.wm-world-event-list-toggle').click();
    await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click();
    await expect(page.locator('.wm-event-inspector')).toBeVisible();
    await page.keyboard.press('Escape');
    await page.locator('.wm-world-event-list-close').click();
    const layer = page.getByRole('checkbox', { name: /Earthquakes.*Volcanoes/i });
    await layer.uncheck(); await layer.check();
    if ([9, 19, 29].includes(i)) {
      await expect.poll(() => active.size).toBe(0);
      // Sample equivalent settled states after Preact effects, RO and camera motion.
      await page.waitForTimeout(500);
      await cdp.send('HeapProfiler.collectGarbage');
      samples.push({ cycle: i + 1, requests, activeRequests: active.size, ...await cdp.send('Memory.getDOMCounters'), ...await cdp.send('Runtime.getHeapUsage') });
    }
  }
  await test.info().attach('resource-cycles', { body: JSON.stringify(samples, null, 2), contentType: 'application/json' });
  writeFileSync(`artifacts/map-polish-round2/resource-cycles-${process.env.POLYMONITOR_E2E_PREVIEW === '1' ? 'production' : 'development'}.json`, JSON.stringify(samples, null, 2));
  if (process.env.MAP_RESOURCE_HEAP === '1') {
    const chunks: string[] = [];
    cdp.on('HeapProfiler.addHeapSnapshotChunk', ({ chunk }) => chunks.push(chunk));
    await cdp.send('HeapProfiler.takeHeapSnapshot');
    writeFileSync('artifacts/map-polish-round2/resource-current.heapsnapshot', chunks.join(''));
  }
  expect(samples[2].documents).toBeLessThanOrEqual(samples[0].documents + 2);
  expect(samples[2].jsEventListeners).toBeLessThanOrEqual(samples[0].jsEventListeners + 12);
  expect(samples[2].usedSize).toBeLessThan(samples[0].usedSize * 1.3);

});
