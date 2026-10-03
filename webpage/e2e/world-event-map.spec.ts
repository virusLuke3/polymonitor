import { gotoMapScene, selectMapLayers } from './fixtures/browser';
import { mkdirSync, writeFileSync } from 'node:fs';
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
  await gotoMapScene(page, `/?view=2d&mapPerf=1&basemap=openfreemap&time=all&severity=info,watch,warning,critical&${search}`);
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute(
    'data-map-renderer-ready', search.includes('renderer=svg') ? 'svg' : 'webgl',
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

test('every entry opens all layers, while manual off survives in-session updates', async ({ page }) => {
  // Use ordinary navigation: this acceptance test must NOT select a fixture
  // scene after entry, unlike isolated rendering cases below.
  await page.addInitScript(() => { if (location.protocol.startsWith('http')) localStorage.setItem('polydata:world-event-map:v8', JSON.stringify({ activeLayerIds: [], center: { lon: 12, lat: 35 }, zoom: 3, timeRange: '24h' })); });
  await page.goto('/?view=2d&mapPerf=1&basemap=openfreemap&center=12,35&zoom=3&layers=&time=all');
  const requested = () => new URL(page.url()).searchParams.get('layers')!.split(',');
  await expect.poll(() => requested().length).toBe(17);
  expect(requested()).toEqual(expect.arrayContaining(['air-routes', 'weather-radar', 'intel-hotspots']));
  await expect(page.locator('.wm-aviation-lens')).toBeVisible();
  await selectMapLayers(page, requested().filter(id => id !== 'air-routes' && id !== 'weather-radar'));
  await expect(page.locator('.wm-map-aviation-toggle')).toContainText('Off');
  await expect(page.locator('.wm-map-radar-status summary')).toContainText('Off');
  await page.getByLabel('Map time range').getByRole('button', { name: '24h', exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('time')).toBe('24h');
  expect(requested()).not.toContain('air-routes');
  expect(requested()).not.toContain('weather-radar');
  await page.reload();
  await expect.poll(() => requested().length).toBe(17);
  await expect(page.locator('.wm-aviation-lens')).toBeVisible();
  expect(new URL(page.url()).searchParams.get('time')).toBe('24h');
  await screenshot(page, 'entry-all-layers.png');
});

test('a saved wide world fills the viewport through resize, zoom-out, pan and reload', async ({ page }) => {
  await page.setViewportSize({width:1920,height:1080});
  await gotoMap(page,'center=-1.7883,37.2465&zoom=1.21&layers=earthquakes-volcanoes,weather-alerts');
  const host=page.locator('[data-map-renderer-ready]');
  const covered=async()=>{
    await expect(async()=>{
      const b=await host.evaluate((el:any)=>{
        const p=el.__polymonitorProjectGeoPoint;
        return {west:p(-180,0).x,east:p(180,0).x,north:p(0,85.0511287798).y,south:p(0,-85.0511287798).y,
          width:el.clientWidth,height:el.clientHeight};
      });
      expect(b.west).toBeLessThanOrEqual(0.01);expect(b.east).toBeGreaterThanOrEqual(b.width-0.01);
      expect(b.north).toBeLessThanOrEqual(0.01);expect(b.south).toBeGreaterThanOrEqual(b.height-0.01);
    }).toPass();
  };
  await covered();await page.reload();await waitForMapPaint(page);await covered();
  for (const viewport of [{width:2560,height:1440},{width:390,height:844},{width:2048,height:567}]) {
    await page.setViewportSize(viewport);await covered();
    await host.evaluate((el:any)=>el.__polymonitorMapCamera([179,80],-1));await covered();
    await host.evaluate((el:any)=>el.__polymonitorMapCamera([-179,-80],2.5));await covered();
  }
  await screenshot(page,'world-viewport-coverage.png');
});

test('basemap and both overlays share a world at the positive dateline endpoint', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 2537, height: 1286 });
  await gotoMap(page, 'center=180,20&zoom=0.93&layers=earthquakes-volcanoes,air-routes&air=all');
  const host = page.locator('[data-map-renderer-ready]');
  const measurements: unknown[] = [];
  const aligned = async (step: string) => {
    await expect(async () => {
      const rows = await host.evaluate(el => {
        const project = (el as any).__polymonitorProjectGeoPoint;
        return [[-122.1,37.4],[-73.78,40.64],[100,35]].map(([lon,lat]) => ({
          coordinate: [lon,lat], basemap: project(lon,lat),
          static: project(lon,lat,'static'), aviation: project(lon,lat,'aviation'),
        }));
      });
      for (const row of rows) for (const overlay of [row.static, row.aviation]) {
        expect(Math.abs(overlay.x-row.basemap.x)).toBeLessThan(0.01);
        expect(Math.abs(overlay.y-row.basemap.y)).toBeLessThan(0.01);
      }
      measurements.push({step, url:page.url(), rows});
    }).toPass({timeout:15_000});
  };
  await aligned('positive endpoint link');
  await page.reload(); await waitForMapPaint(page); await aligned('link reload');
  await host.evaluate((el:any) => el.__polymonitorMapCamera([179,20],0.93));
  await aligned('near endpoint');
  const box = (await host.boundingBox())!;
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
  await page.mouse.down();
  await page.mouse.move(box.x+box.width/2-120,box.y+box.height/2,{steps:12});
  await page.mouse.up(); await page.waitForTimeout(500);
  await aligned('drag through positive endpoint');
  for (const width of [1440,390,2537]) {
    await page.setViewportSize({width,height:1286});
    await aligned(`resize ${width}`);
  }
  await host.evaluate((el:any) => el.__polymonitorMapCamera([-180,20],0.93));
  await aligned('negative endpoint');
  await host.evaluate((el:any) => el.__polymonitorMapCamera([180,20],3));
  await aligned('regional zoom at endpoint');
  mkdirSync(ARTIFACT_DIR,{recursive:true});
  writeFileSync(resolve(ARTIFACT_DIR,'dateline-alignment.json'),JSON.stringify(measurements,null,2));
  await screenshot(page,'dateline-alignment.png');
});

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
    await gotoMapScene(page, '/?view=2d&basemap=pmtiles&time=all&layers=earthquakes-volcanoes&center=30,28&zoom=1.7');
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

  await gotoMapScene(page, `/?view=2d&mapPerf=1&time=all&center=-98,39&zoom=3.5&layers=${ALL_LAYERS}&country=US&basemap=openfreemap&theme=dark`);
  await expect(page.getByRole('button', { name: /Country · US/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /^All events/i })).toContainText(/[1-9]/);
  await waitForMapPaint(page);
  await screenshot(page, '07-country-filter.png');

  await gotoMapScene(page, `/?view=2d&mapPerf=1&basemap=openfreemap&time=all&center=-73,42&zoom=3.2&layers=air-routes&air=all`);
  await page.getByRole('button', {name:'Expand aviation details',exact:true}).click();
  await expect(page.getByText('All aviation', {exact:true})).toBeVisible();
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

  await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=openfreemap&time=all&center=-69,22&zoom=4.4&layers=weather-alerts');
  await page.locator('.wm-map-legend-toggle').click();
  await expect(page.getByText('Observed', { exact: true })).toBeVisible();
  await expect(page.getByText('Forecast', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await waitForMapPaint(page);
  await screenshot(page, '03-hurricane-observed-forecast-cone.png');

  await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=openfreemap&time=all&center=-118.25,34.15&zoom=6&layers=wildfires');
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
  await hoverMapPoint(page, center, /Cluster.*3 earthquake/i);
  await page.mouse.click(center.x, center.y);
  // Coincident targets now expose the candidates instead of choosing an arbitrary record.
  await expect(page.getByRole('heading', { name: 'Cluster members' })).toBeVisible();
  await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click();
  await expect(page.locator('.wm-event-inspector')).toBeVisible();
  await expect(page.locator('.wm-event-inspector')).toContainText(/Disaster report/i);
  await page.getByRole('button', { name: 'Close event details' }).click();

  await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=openfreemap&time=all&center=-122.1,37.4&zoom=2.2&layers=earthquakes-volcanoes');
  await expect(page.getByRole('button', { name: /^All events/i })).toContainText('8');
  await waitForMapPaint(page);
  const clusterPoint = await projectedMapPoint(page, -122.1, 37.4);
  await hoverMapPoint(page, clusterPoint, /Cluster.*3 earthquake/i);
  for (const [dx, dy] of [[0, 0], [-10, 0], [10, 0], [0, -10], [0, 10]]) {
    const point = await projectedMapPoint(page, -122.1, 37.4);
    await page.mouse.click(point.x + dx!, point.y + dy!);
    await expect(page.getByRole('heading', { name: 'Cluster members' })).toBeVisible();
    await expect(page.locator('.wm-world-event-list-summary')).toContainText('7 / 7');
    await expect(page.getByRole('button', {name:/M6.4 Test Ridge Earthquake/})).toBeVisible();
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

test('mobile aviation keeps the map controls and event list unobstructed', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('https://api.rainviewer.com/public/weather-maps.json', route => route.fulfill({ json: {
    host: 'https://tilecache.rainviewer.com', radar: { past: [
      { time: Math.floor(Date.parse(GENERATED_AT) / 1000), path: '/v2/radar/layout-fixture' },
    ] },
  } }));
  // A committed timestamp is wider than "Off". Exercise that layout with a
  // deterministic raster; native radar imagery is verified in production.
  await page.route('https://tilecache.rainviewer.com/**', route => route.fulfill({ contentType: 'image/png', body: Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64',
  ) }));
  await gotoMap(page, 'layers=air-routes&air=watch&zoom=1.5');
  const lens = (await page.locator('.wm-aviation-lens').boundingBox())!;
  expect(lens.height, 'folded aviation leaves the mobile map visible').toBeLessThan(100);
  await expect(page.locator('.wm-map-aviation-zoom')).toHaveCount(0);
  for (const selector of ['.wm-map-controls', '.wm-map-focus-toggle', '.wm-world-event-list-toggle', '.wm-map-radar-status', '.wm-map-legend-toggle', '.wm-world-event-attribution']) {
    const control = (await page.locator(selector).boundingBox())!;
    const overlap = Math.min(lens.x + lens.width, control.x + control.width) > Math.max(lens.x, control.x)
      && Math.min(lens.y + lens.height, control.y + control.height) > Math.max(lens.y, control.y);
    expect(overlap, selector).toBe(false);
  }
  await page.locator('.wm-world-event-list-toggle').click();
  await expect(page.locator('.wm-world-event-list.is-open')).toBeVisible();
  await page.locator('.wm-world-event-list-close').click();
  await page.getByRole('button', { name: 'Hide aviation layer', exact: true }).click();
  await expect(page.locator('.wm-aviation-lens')).toHaveCount(0);
  await page.locator('.wm-map-radar-status summary').click();
  await page.getByRole('button', { name: 'Enable weather view', exact: true }).click();
  await expect(page.locator('.wm-map-radar-status')).toHaveAttribute('data-radar-tiles', 'ready', { timeout: 30_000 });
  await page.locator('.wm-map-radar-status summary').click();
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    if (width === 320) await page.getByRole('combobox', { name: 'Language', exact: true }).selectOption('zh');
    await page.evaluate(() => document.fonts.ready);
    const stage = (await page.locator('.wm-map-stage').boundingBox())!;
    const rectangles = await page.locator('.wm-map-context-controls > button, .wm-map-radar-status summary, .wm-map-controls button, .wm-world-event-list-toggle, .wm-layer-sidebar.is-collapsed, .wm-world-event-attribution, .wm-weather-deck-status:not([hidden])').evaluateAll(elements => elements.map(e => ({ text: e.textContent, ...e.getBoundingClientRect().toJSON() })));
    for (const control of rectangles) {
      expect(control.top, control.text || 'control').toBeGreaterThanOrEqual(stage.y);
      expect(control.bottom, control.text || 'control').toBeLessThanOrEqual(stage.y + stage.height + 1);
    }
    for (let i = 0; i < rectangles.length; i++) for (let j = i + 1; j < rectangles.length; j++) {
      const a = rectangles[i]!, b = rectangles[j]!;
      expect(Math.min(a.right, b.right) > Math.max(a.left, b.left) && Math.min(a.bottom, b.bottom) > Math.max(a.top, b.top), `${width}: ${a.text} / ${b.text}`).toBe(false);
    }
  }
});

test('live aircraft supports viewport loading, hover, click and inspector details', async ({ page }) => {
  await gotoMap(page, 'center=-70,43&zoom=5&layers=air-routes&air=all');
  await page.getByRole('button', {name:'Expand aviation details',exact:true}).click();
  await expect(page.getByText('All aviation', {exact:true})).toBeVisible();
  const expand = (await page.locator('.wm-map-focus-toggle').boundingBox())!;
  const lens = (await page.locator('.wm-aviation-lens').boundingBox())!;
  expect(lens.x + lens.width).toBeLessThanOrEqual(expand.x);
  await page.locator('.wm-map-focus-toggle').click();
  await expect(page.locator('.wm-map-stage')).toHaveClass(/is-map-focused/);
  await page.keyboard.press('Escape');
  await expect(page.locator('.wm-map-stage')).not.toHaveClass(/is-map-focused/);
  const center = await mapCanvasCenter(page);
  await page.mouse.move(center.x, center.y);
  await expect(page.locator('.deck-tooltip:visible')).toContainText('PX202');
  await page.mouse.click(center.x, center.y);
  await expect(page.locator('.wm-event-inspector')).toContainText('ICAO24');
});

test('SVG fallback and reduced-motion mobile preserve events, interaction entry points and cleanup', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 390, height: 844 });
  await gotoMap(page, 'renderer=svg&center=-70,22&zoom=3&layers=weather-alerts,earthquakes-volcanoes,wildfires,extreme-temperature,climate-anomalies');
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
  await gotoMap(page, 'renderer=svg&center=-98,39&zoom=3&layers=earthquakes-volcanoes,wildfires');
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'svg');
  const usCountry = page.locator('[aria-label^="United States"][aria-label$="map area"]');
  await expect(usCountry).toBeVisible();
  await usCountry.click({ button: 'right' });
  await expect(page.locator('.wm-country-context-card.is-context')).toBeVisible();
  await page.getByRole('button', { name: 'Filter events' }).click();
  await expect(page).toHaveURL(/country=US/);
});

test('WebGL context failure switches to SVG and destroys stale deck canvases', async ({ page }) => {
  // The remounted 3D engine debounces with Date; advance it together with timers.
  // A fixed Date with running native timers would never finish that debounce.
  await page.clock.install({ time: new Date(GENERATED_AT) });
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
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'globe');
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
  await expect(page.locator('.wm-sidebar-footer')).toHaveText('3/16 LAYERS ACTIVE');
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


test('fifty layer, provider and selection cycles keep resources bounded and tooltips safe', async ({ page }) => {
  test.setTimeout(180_000);
  await page.addInitScript(()=>{
    const timeouts=new Set<number>(),intervals=new Set<number>();
    const set=window.setTimeout.bind(window),clear=window.clearTimeout.bind(window);
    const repeat=window.setInterval.bind(window),stop=window.clearInterval.bind(window);
    window.setTimeout=((callback:any,delay:any,...args:any[])=>{const id=set(()=>{timeouts.delete(id);callback(...args);},delay);timeouts.add(id);return id;}) as any;
    window.clearTimeout=((id:number)=>{timeouts.delete(id);clear(id);}) as any;
    window.setInterval=((...args:any[])=>{const id=(repeat as any)(...args);intervals.add(id);return id;}) as any;
    window.clearInterval=((id:number)=>{intervals.delete(id);stop(id);}) as any;
    (window as any).__v3Timers=()=>({timeouts:timeouts.size,intervals:intervals.size});
  });
  let mapRequests=0;page.on('request',request=>{if(/natural-hazards\/map|aviation-viewport/.test(request.url()))mapRequests++;});
  await gotoMap(page, 'center=-122.1,37.4&zoom=8&layers=earthquakes-volcanoes');
  const baselineCanvases = await page.locator('.wm-weather-deck-map canvas').count();
  const cdp=await page.context().newCDPSession(page);
  await cdp.send('HeapProfiler.collectGarbage');
  await cdp.send('Performance.enable');
  const coldResources=await cdp.send('Memory.getDOMCounters');
  // The drawer retains its initialized DOM on close. Exercise the same path
  // once before measuring repetition; keep the cold counts in the receipt.
  await page.locator('.wm-world-event-list-toggle').click();
  await page.getByRole('button',{name:/M6.4 Test Ridge Earthquake/}).click();
  await page.keyboard.press('Escape');await page.locator('.wm-world-event-list-close').click();
  await waitForMapPaint(page);await cdp.send('HeapProfiler.collectGarbage');
  const beforeResources={...await cdp.send('Memory.getDOMCounters'), metrics:(await cdp.send('Performance.getMetrics')).metrics,timers:await page.evaluate(()=>(window as any).__v3Timers())};
  const resourceSamples=[];
  const checkbox = page.locator('.wm-layer-row').filter({ hasText: 'Earthquakes' }).getByRole('checkbox');
  for (let cycle = 0; cycle < 50; cycle++) {
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
    if(cycle % 10 === 9){await cdp.send('HeapProfiler.collectGarbage');resourceSamples.push({cycle:cycle+1,...await cdp.send('Memory.getDOMCounters'),metrics:(await cdp.send('Performance.getMetrics')).metrics,timers:await page.evaluate(()=>(window as any).__v3Timers()),mapRequests});}
  }
  // Native DOM/listener accounting after collection, measured throughout the run.
  const finalResources=resourceSamples.at(-1)!;
  mkdirSync(ARTIFACT_DIR,{recursive:true});
  writeFileSync(resolve(ARTIFACT_DIR,'fifty-cycle-resources.json'),JSON.stringify({coldResources,beforeResources,resourceSamples,baselineCanvases},null,2));
  expect(finalResources.jsEventListeners).toBeLessThanOrEqual(beforeResources.jsEventListeners + 12);
  expect(finalResources.documents).toBeLessThanOrEqual(beforeResources.documents + 1);
  expect(finalResources.timers.intervals).toBeLessThanOrEqual(beforeResources.timers.intervals);
  expect(finalResources.timers.timeouts).toBeLessThanOrEqual(beforeResources.timers.timeouts + 2);
  const point = await projectedMapPoint(page, -122.1, 37.4);
  await hoverMapPoint(page, point, /Cluster.*3 earthquake/i);
  const tooltip = page.locator('.wm-world-event-renderer-tooltip');
  const box = (await tooltip.boundingBox())!;
  const host = (await page.locator('[data-map-renderer-ready]').boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(host.x);
  expect(box.y).toBeGreaterThanOrEqual(host.y);
  expect(box.x + box.width).toBeLessThanOrEqual(host.x + host.width);
  expect(box.y + box.height).toBeLessThanOrEqual(host.y + host.height);
  await gotoMapScene(page, '/login');
  await expect(page.locator('.auth-login-layout')).toBeVisible();
  await expect(page.locator('.maplibregl-canvas, .wm-world-event-renderer-tooltip')).toHaveCount(0);
  const stopped=mapRequests;await page.waitForTimeout(1500);expect(mapRequests).toBe(stopped);
  writeFileSync(resolve(ARTIFACT_DIR,'fifty-cycle-resources.json'),JSON.stringify({coldResources,beforeResources,resourceSamples,baselineCanvases,unmounted:{canvases:await page.locator('.maplibregl-canvas').count(),tooltips:await page.locator('.wm-world-event-renderer-tooltip').count(),requestsBefore:stopped,requestsAfter:mapRequests,timers:await page.evaluate(()=>(window as any).__v3Timers())}},null,2));
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
  await hoverMapPoint(page, point, /Cluster.*3 earthquake/i);
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

test('manually selected seven-layer scene survives repeated offscreen returns with identical geometry pixels', async ({ page }) => {
  test.setTimeout(120_000);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const seven = 'weather-alerts,earthquakes-volcanoes,wildfires,extreme-temperature,climate-anomalies,ucdp,sanctions-country-risk';
  const payload = { generatedAt: GENERATED_AT, status: 'ok', items: [],
    sanctionsTargetBreakdown: [{ label: 'Ukraine', count: 30, latestOccurredAt: GENERATED_AT, latestSource: 'Fixture authority' }], countryRiskBreakdown: [] };
  await page.route('**/wm-api/runtime/world/geo-sanctions-shock?**', route => route.fulfill({ json: payload }));
  await gotoMap(page, `center=0,24&zoom=1.5&layers=${seven}`);
  const host = page.locator('[data-map-renderer-ready]');
  await expect(page.locator('.wm-map-aviation-toggle')).toBeVisible();
  await expect(page.locator('.wm-aviation-lens')).toHaveCount(0);
  await page.reload(); await waitForMapPaint(page);
  await selectMapLayers(page, seven.split(',')); await waitForMapPaint(page);
  await expect(page.locator('.wm-map-aviation-toggle')).toBeVisible();
  await host.scrollIntoViewIfNeeded(); await page.mouse.move(0, 0);
  await page.waitForTimeout(1500);
  const before = await host.screenshot();
  const count = await page.locator('.wm-world-event-list-toggle strong').innerText();
  mkdirSync(ARTIFACT_DIR, { recursive: true });
  writeFileSync(resolve(ARTIFACT_DIR, 'offscreen-scene-before.png'), before);
  for (let cycle = 0; cycle < 3; cycle++) {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect.poll(() => host.evaluate(el => el.getBoundingClientRect().bottom)).toBeLessThanOrEqual(0);
    await page.waitForTimeout(350);
    await host.scrollIntoViewIfNeeded(); await waitForMapPaint(page);
    await expect(page.getByText(/MAP DEGRADED.*ISOLATED/)).toHaveCount(0);
    await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText(count);
    // Zero tolerance: no masks and no baseline update can hide missing geometry.
    await expect(async () => expect((await host.screenshot()).equals(before)).toBe(true)).toPass({ timeout: 15_000 });
  }
  await host.screenshot({ path: resolve(ARTIFACT_DIR, 'offscreen-scene-after.png') });
  await page.locator('.wm-map-aviation-toggle').click();
  await expect(page.locator('.wm-aviation-lens')).toBeVisible();
  await page.getByRole('button', {name:'Expand aviation details',exact:true}).click();
  await expect(page.locator('.wm-map-aviation-zoom')).toBeVisible();
  await page.reload(); await waitForMapPaint(page);
  await expect(page.locator('.wm-aviation-lens')).toBeVisible();
});

test('aircraft canvas remains sharp and camera aligned during drag and repeated visibility changes', async ({ page }) => {
  await gotoMap(page, 'layers=air-routes&center=-30,40&zoom=2.5');
  const host = page.locator('[data-map-renderer-ready]');
  const motion = page.locator('.maplibregl-control-container canvas').last();
  await expect(motion).toBeVisible();
  const canvas = await motion.evaluate((el: HTMLCanvasElement) => ({ width: el.width, css: el.getBoundingClientRect().width }));
  expect(canvas.width).toBeGreaterThanOrEqual(canvas.css - 1);
  const box = (await host.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2 + 10, { steps: 10 });
  await expect(motion).toBeVisible();
  const alignment = await host.evaluate((el: any) => {
    const project = el.__polymonitorProjectGeoPoint;
    return { base: project(-70,43), air: project(-70,43,'aviation') };
  });
  expect(Math.abs(alignment.base.x - alignment.air.x)).toBeLessThan(0.1);
  expect(Math.abs(alignment.base.y - alignment.air.y)).toBeLessThan(0.1);
  await page.mouse.up();
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(350); await host.scrollIntoViewIfNeeded();
  await expect(motion).toBeVisible();
  await expect(page.getByText(/MAP DEGRADED.*ISOLATED/)).toHaveCount(0);
});
