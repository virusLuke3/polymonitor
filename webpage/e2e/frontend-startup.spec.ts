import { expect, test, type Page, type Route } from '@playwright/test';
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
