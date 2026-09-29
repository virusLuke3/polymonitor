import { mkdirSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, expect, test } from '@playwright/test';
import { installRealMapAssets } from './fixtures/real-map-assets';
import { GENERATED_AT, installFixtures } from './fixtures/world-event-map';
import { MAP_SYMBOL_DEFINITIONS } from '../src/features/world-event-map/config/mapSymbols';

// Opt-in acceptance against real vector assets, cached byte-for-byte between
// phases. API data is the existing deterministic fixture, never live evidence.
const phase = process.env.MAP_ALIGNMENT_PHASE;
const finalPhase = phase === 'P6' || phase === 'round2-E';
const artifactRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../artifacts/map-alignment');
const output = resolve(artifactRoot, phase || 'unrequested');
const cache = resolve(artifactRoot, 'input-assets');
test.use({ trace: 'off', deviceScaleFactor: Number(process.env.MAP_ALIGNMENT_DPR || 1) });
test.skip(!phase, 'Set MAP_ALIGNMENT_PHASE to capture a reviewed alignment phase.');

test('shared hazard symbols at native 12, 14 and 16 CSS pixels', async ({ page }) => {
  test.skip(!finalPhase, 'Final native-size symbol review.');
  await page.setViewportSize({ width: 720, height: 400 });
  const rows = ['earthquake', 'volcano', 'wildfire', 'cyclone'].map(key => {
    const symbol = MAP_SYMBOL_DEFINITIONS[key as keyof typeof MAP_SYMBOL_DEFINITIONS];
    return `<tr><th>${symbol.label}</th>${[12,14,16].map(size => `<td><svg width="${size}" height="${size}" viewBox="0 0 48 48" fill="#d7b84e">${symbol.paths.map(d => `<path d="${d}" fill-rule="evenodd"/>`).join('')}</svg></td>`).join('')}</tr>`;
  }).join('');
  await page.setContent(`<style>body{background:#111;color:#ddd;font:14px system-ui}table{border-spacing:32px 20px}th{text-align:left}</style><p>Test fixture · shared production symbol paths · native CSS sizes · DPR ${process.env.MAP_ALIGNMENT_DPR || 1}</p><table><tr><th>Symbol</th><th>12 px</th><th>14 px</th><th>16 px</th></tr>${rows}</table>`);
  await expect(page.locator('svg')).toHaveCount(12);
  await page.screenshot({ path: resolve(output, `symbols-dpr${process.env.MAP_ALIGNMENT_DPR || 1}.png`) });
});

for (const language of ['en', 'zh']) {
  test(`alignment ${language}: fixed camera, real vector map, details and interaction`, async ({ page, browser }) => {
    test.setTimeout(180_000);
    mkdirSync(output, { recursive: true });
    mkdirSync(cache, { recursive: true });
    await page.setViewportSize({ width: 1536, height: 1100 });
    await page.clock.setFixedTime(new Date(GENERATED_AT));
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await installFixtures(page);
    expect(process.env.VITE_PMTILES_URL, 'Alignment must load the real PMTiles style, not the intercepted fallback').toBeTruthy();
    const network = await installRealMapAssets(page);
    const vectorResponses: number[] = [];
    page.on('response', response => { if (response.url().includes('planet.pmtiles')) vectorResponses.push(response.status()); });
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    try {
      const cameraUrl = '/?view=2d&mapPerf=1&basemap=pmtiles&center=0,20&zoom=1.5&time=all&severity=info,watch,warning,critical';
      const framing = '.wm-map-stage,.wm-inline-weather-map,.wm-weather-deck-map {height:768px!important;min-height:768px!important;max-height:768px!important;width:1536px!important}.wm-map-stage{overflow:visible!important}';
      await page.goto(`${cameraUrl}&layers=`);
      await page.addStyleTag({ content: framing });
      await page.locator('.wm-language-switch select').selectOption(language);
      await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-basemap-state', 'primary-ready');
      await expect.poll(() => vectorResponses.filter(status => status === 206).length).toBeGreaterThan(0);
      await page.evaluate(() => document.fonts.ready); await page.mouse.move(0, 0); await page.waitForTimeout(2500);
      await page.locator('.wm-weather-deck-map').screenshot({ path: resolve(output, `basemap-${language}.png`) });
      await page.goto(`${cameraUrl}&layers=earthquakes-volcanoes,weather-alerts,wildfires,climate-anomalies`);
      // Reference-only framing. Product layout is separately exercised by the
      // existing map and dashboard suites; no production setting is added.
      await page.addStyleTag({ content: '.wm-map-stage,.wm-inline-weather-map,.wm-weather-deck-map {height:768px!important;min-height:768px!important;max-height:768px!important;width:1536px!important}.wm-map-stage{overflow:visible!important}' });
      await page.locator('.wm-language-switch select').selectOption(language);
      const host = page.locator('[data-map-renderer-ready]');
      await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl');
      await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready');
      await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText('11');
      await page.evaluate(() => document.fonts.ready);
      await page.mouse.move(0, 0);
      await page.waitForTimeout(2500);
      await page.locator('.wm-weather-deck-map').screenshot({ path: resolve(output, `events-${language}.png`) });
      if (process.env.MAP_ALIGNMENT_PREVIEW === '1') { test.setTimeout(0); await page.pause(); }
      const metadata = await host.evaluate(el => ({ width: el.clientWidth, height: el.clientHeight, dpr: devicePixelRatio,
        canvases: [...el.querySelectorAll('canvas')].map(c => ({ width: c.width, height: c.height, cssWidth: c.clientWidth, cssHeight: c.clientHeight })),
        fonts: Object.fromEntries(['.wm-map-legend-toggle', '.wm-world-event-list-toggle', '.wm-map-radar-status'].map(selector => [selector, getComputedStyle(document.querySelector(selector)!).fontFamily])),
        url: location.href, renderer: (el as HTMLElement).dataset.mapRendererReady, basemap: (el as HTMLElement).dataset.mapBasemapState,
        logicalEvents: Number(document.querySelector('.wm-world-event-list-toggle strong')?.textContent),
        performance: window.__POLYMONITOR_MAP_PERF__?.snapshot(),
        gpu: (() => { const gl = el.querySelector('canvas')?.getContext('webgl2'); const debug = gl?.getExtension('WEBGL_debug_renderer_info'); return debug ? gl!.getParameter(debug.UNMASKED_RENDERER_WEBGL) : 'not exposed'; })(),
      }));
      expect(metadata.width).toBe(1536); expect(metadata.height).toBe(768);
      await page.locator('.wm-world-event-list-toggle').click();
      await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click();
      await expect(page.locator('.wm-event-inspector')).toBeVisible();
      await page.waitForTimeout(500);
      await page.locator('.wm-weather-deck-map').screenshot({ path: resolve(output, `detail-${language}.png`) });
      if (phase !== 'P0' && !finalPhase) {
        writeFileSync(resolve(output, `evidence-${language}.json`), JSON.stringify({ phase, fixture: GENERATED_AT, browser: browser.version(), metadata, errors }, null, 2));
        expect(errors).toEqual([]);
        return;
      }
      await page.keyboard.press('Escape');
      if (await page.locator('.wm-world-event-list-close').isVisible()) await page.locator('.wm-world-event-list-close').click();
      await page.emulateMedia({ reducedMotion: 'no-preference' });
      await page.context().tracing.start({ screenshots: true, snapshots: true, sources: true });
      await host.scrollIntoViewIfNeeded();
      const box = (await host.boundingBox())!;
      await page.evaluate(() => {
        const w = window as any;
        w.__alignmentFrames = []; w.__alignmentLongTasks = [];
        w.__alignmentObserver = new PerformanceObserver(list => w.__alignmentLongTasks.push(...list.getEntries().map(e => e.duration)));
        w.__alignmentObserver.observe({ type: 'longtask', buffered: false });
        w.__alignmentMeasuring = true;
        let previous = performance.now();
        const sample = (now: number) => { if (!w.__alignmentMeasuring) return; w.__alignmentFrames.push(now - previous); previous = now; requestAnimationFrame(sample); };
        requestAnimationFrame(sample);
      });
      // Ten seconds of continuous pointer drag; source data stays unchanged.
      await page.mouse.move(box.x + 600, box.y + 350); await page.mouse.down();
      for (let i = 0; i < 100; i++) {
        await page.mouse.move(box.x + 600 + Math.sin(i / 12) * 160, box.y + 350 + Math.cos(i / 12) * 60);
        await page.waitForTimeout(100);
      }
      await page.mouse.up();
      const performance = await page.evaluate(() => {
        const w = window as any; w.__alignmentMeasuring = false; w.__alignmentObserver.disconnect();
        const frames = w.__alignmentFrames.sort((a: number, b: number) => a - b);
        return { rafP95: frames[Math.ceil(frames.length * .95) - 1], rafMax: frames.at(-1), longTasks: w.__alignmentLongTasks,
          phases: window.__POLYMONITOR_MAP_PERF__?.snapshot() };
      });
      await page.mouse.wheel(0, -200); await page.waitForTimeout(800);
      await page.locator('.wm-world-event-list-toggle').click();
      await page.getByRole('button', { name: /HU ADA/ }).click();
      await page.waitForTimeout(1000);
      if (finalPhase) {
        await page.keyboard.press('Escape');
      if (await page.locator('.wm-world-event-list-close').isVisible()) await page.locator('.wm-world-event-list-close').click();
        await page.locator('.wm-map-controls button').nth(2).click();
        await page.waitForTimeout(800);
        await host.scrollIntoViewIfNeeded();
        const cluster = await host.evaluate((el: any) => {
          const p = el.__polymonitorProjectGeoPoint(-122.1,37.4), b = el.getBoundingClientRect();
          return { x: p.x + b.x, y: p.y + b.y };
        });
        await page.mouse.move(cluster.x, cluster.y); await page.waitForTimeout(800);
        await page.mouse.click(cluster.x, cluster.y); await page.waitForTimeout(1500);
        const toggle = page.locator('.wm-world-event-list-toggle');
        if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
        await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click({ timeout: 15_000 });
        await expect(page.locator('.wm-event-inspector')).toBeVisible();
        await page.waitForTimeout(1500); await page.keyboard.press('Escape');
      if (await page.locator('.wm-world-event-list-close').isVisible()) await page.locator('.wm-world-event-list-close').click();
      }
      await page.context().tracing.stop({ path: resolve(output, `interaction-${language}.zip`) });
      writeFileSync(resolve(output, `evidence-${language}.json`), JSON.stringify({ phase, fixture: GENERATED_AT, browser: browser.version(), metadata, performance, errors }, null, 2));
      expect(errors).toEqual([]);
    } finally {
      await page.goto('about:blank'); await page.unrouteAll({ behavior: 'wait' }); await network.dispose();
    }
  });
}

test('real radar: latest manifest, raster tiles, coverage, close and reopen', async ({ page }) => {
  test.skip(phase !== 'P5' && phase !== 'round2-radar', 'Real source acceptance is separate from fixed-event comparison.');
  test.setTimeout(150_000);
  await page.setViewportSize({ width: 1536, height: 1100 });
  await page.clock.install({ time: new Date() });
  await installFixtures(page);
  const network = await installRealMapAssets(page);
  const receipts: { url: string; status: number; bytes: number }[] = [];
  let manifest: any;
  let failManifest = false;
  const startedRequests: string[] = [];
  await page.route(/https:\/\/(?:api|tilecache)\.rainviewer\.com\//, async route => {
    startedRequests.push(route.request().url());
    if (failManifest && route.request().url().endsWith('weather-maps.json')) { await route.fulfill({ status: 503, body: 'Controlled recovery check' }); return; }
    const response = await network.get(route.request().url(), { timeout: 30_000 });
    const body = await response.body();
    receipts.push({ url: route.request().url(), status: response.status(), bytes: body.length });
    if (route.request().url().endsWith('weather-maps.json')) manifest = JSON.parse(body.toString());
    await route.fulfill({ response, body });
  });
  const url = '/?view=2d&mapPerf=1&basemap=pmtiles&center=0,20&zoom=1.5&time=all&layers=earthquakes-volcanoes,weather-alerts';
  try {
    await page.goto(url);
    await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-basemap-state', 'primary-ready');
    const map = page.locator('.wm-weather-deck-map');
    await page.addStyleTag({ content: '.wm-map-stage,.wm-inline-weather-map,.wm-weather-deck-map {height:768px!important;min-height:768px!important;max-height:768px!important;width:1536px!important}' });
    await page.mouse.move(0, 0); await page.waitForTimeout(1500);
    await map.screenshot({ path: resolve(output, 'radar-before.png') });
    await page.getByRole('checkbox', { name: 'Show Weather radar', exact: true }).check();
    await expect(page.locator('.wm-map-radar-status')).toContainText(/ready \/ ready/, { timeout: 45_000 });
    await page.waitForTimeout(2000);
    await map.screenshot({ path: resolve(output, 'radar-after.png') });
    expect(receipts.some(r => r.url.includes('/v2/radar/') && r.status === 200 && r.bytes > 100)).toBe(true);
    expect(receipts.some(r => r.url.includes('/v2/coverage/') && r.status === 200)).toBe(true);
    const latest = [...manifest.radar.past].filter((f: any) => f.time * 1000 <= Date.now()).sort((a: any,b: any) => b.time-a.time)[0];
    expect(receipts.filter(r => r.url.includes('/v2/radar/')).every(r => r.url.includes(latest.path))).toBe(true);
    await page.getByRole('checkbox', { name: 'Hide Weather radar', exact: true }).uncheck();
    await expect(page.locator('.wm-map-radar-status summary')).toContainText('Off');
    const stoppedCount = startedRequests.length; await page.waitForTimeout(1500); expect(startedRequests.length).toBe(stoppedCount);
    await page.getByRole('checkbox', { name: 'Show Weather radar', exact: true }).check();
    await expect(page.locator('.wm-map-radar-status')).toContainText(/ready \/ ready/, { timeout: 45_000 });
    const frameTime = await page.locator('.wm-map-radar-status span').first().textContent();
    failManifest = true;
    await page.clock.fastForward(300_100);
    await expect(page.locator('.wm-map-radar-status')).toContainText(/stale \/ ready/);
    await expect(page.locator('.wm-map-radar-status')).toContainText(frameTime!);
    failManifest = false;
    await page.clock.fastForward(300_100);
    await expect(page.locator('.wm-map-radar-status')).toContainText(/ready \/ ready/, { timeout: 45_000 });
    writeFileSync(resolve(output, 'radar-evidence.json'), JSON.stringify({ recovery: '503 retains last good frame; next poll recovers', observedAt: new Date().toISOString(), latestFrame: latest, receipts }, null, 2));
  } finally { await page.unrouteAll({ behavior: 'ignoreErrors' }); await page.goto('about:blank'); await network.dispose(); }
});

for (const screen of [
  { width: 1440, height: 900, dpr: 1 }, { width: 2048, height: 900, dpr: 1 },
  { width: 1920, height: 1080, dpr: 1 }, { width: 390, height: 844, dpr: 2 }, { width: 844, height: 390, dpr: 2 },
  { width: 1536, height: 1100, dpr: 1.25 }, { width: 1536, height: 1100, dpr: 1.5 }, { width: 1536, height: 1100, dpr: 2 },
]) {
  test(`product map ${screen.width}x${screen.height} DPR ${screen.dpr}`, async ({ browser }) => {
    test.skip(!finalPhase, 'Final responsive and pixel-density matrix.');
    const context = await browser.newContext({ viewport: screen, deviceScaleFactor: screen.dpr, hasTouch: screen.width <= 720, reducedMotion: 'reduce', baseURL: 'http://127.0.0.1:4174' });
    const page = await context.newPage();
    await page.clock.setFixedTime(new Date(GENERATED_AT));
    await installFixtures(page); const network = await installRealMapAssets(page);
    const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
    try {
      await page.goto('/?view=2d&mapPerf=1&basemap=pmtiles&time=all&layers=earthquakes-volcanoes,weather-alerts');
      await page.locator('.wm-weather-deck-map').scrollIntoViewIfNeeded();
      const host = page.locator('[data-map-renderer-ready]');
      await expect(host).toHaveAttribute('data-map-renderer-ready', screen.width <= 720 ? 'svg' : 'webgl');
      await expect(host).toHaveAttribute('data-map-basemap-state', screen.width <= 720 ? 'renderer-fallback-ready' : 'primary-ready');
      await page.locator('.wm-language-switch select').selectOption('zh');
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(2000);
      const name = `${screen.width}x${screen.height}-dpr${screen.dpr}`;
      await page.screenshot({ path: resolve(output, `product-${name}.png`) });
      const metrics = await host.evaluate(el => ({
        zoom: Number(new URL(location.href).searchParams.get('zoom')),
        renderer: (el as HTMLElement).dataset.mapRendererReady,
        width: el.clientWidth, height: el.clientHeight, dpr: devicePixelRatio,
        canvas: [...el.querySelectorAll('canvas')].map(c => ({ w: c.width, h: c.height, cssW: c.clientWidth, cssH: c.clientHeight })),
        scrollY, horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
      }));
      expect(metrics.horizontalOverflow).toBe(false);
      expect(metrics.zoom).toBeLessThanOrEqual(1.5);
      if (metrics.renderer === 'webgl') {
        const canvas = metrics.canvas[0]!;
        expect(Math.abs(canvas.w - canvas.cssW * screen.dpr)).toBeLessThanOrEqual(1);
        expect(Math.abs(canvas.h - canvas.cssH * screen.dpr)).toBeLessThanOrEqual(1);
      }
      if (screen.width <= 720) await page.locator('.wm-world-event-list-toggle').tap();
      else await page.locator('.wm-world-event-list-toggle').click();
      await expect(page.locator('#wm-event-list-search')).toBeFocused();
      await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).scrollIntoViewIfNeeded();
      if (screen.width <= 720) await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).tap({ timeout: 15_000 });
      else await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click({ timeout: 15_000 });
      const inspector = page.locator('.wm-event-inspector'); await expect(inspector).toBeVisible();
      await expect(page.locator('#wm-event-inspector-title')).toBeFocused();
      if (screen.width <= 720) expect(Math.abs((await host.boundingBox())!.y)).toBeLessThanOrEqual(1);
      await page.waitForTimeout(400);
      const bounds = (await inspector.boundingBox())!;
      expect(bounds.width).toBeLessThanOrEqual(screen.width);
      if (metrics.renderer === 'svg') {
        const marker = (await page.locator('.wm-world-event-svg-point.is-selected').boundingBox())!;
        expect(marker.y).toBeGreaterThanOrEqual(0);
        expect(marker.y + marker.height).toBeLessThan(bounds.y);
        const controls = (await page.locator('.wm-map-controls').boundingBox())!;
        expect(controls.y + controls.height).toBeLessThan(bounds.y);
      } else {
        const point = await host.evaluate((el: any) => {
          const p = el.__polymonitorProjectGeoPoint(-122.1, 37.4), box = el.getBoundingClientRect();
          return { x: p.x + box.x, y: p.y + box.y };
        });
        expect(point.x).toBeGreaterThanOrEqual(0);
        expect(point.x).toBeLessThan(bounds.x);
        expect(point.y).toBeGreaterThanOrEqual(0);
        expect(point.y).toBeLessThan(screen.height);
      }
      await page.screenshot({ path: resolve(output, `product-detail-${name}.png`) });
      await page.keyboard.press('Escape');
      if (await page.locator('.wm-world-event-list-close').isVisible()) await page.locator('.wm-world-event-list-close').click(); await expect(inspector).toHaveCount(0);
      writeFileSync(resolve(output, `product-${name}.json`), JSON.stringify({ metrics, errors }, null, 2));
      expect(errors).toEqual([]);
    } finally { await page.unrouteAll({ behavior: 'ignoreErrors' }); await context.close(); await network.dispose(); }
  });
}


test('live sources: real public hazards and real vector assets in the local frontend', async ({ page }) => {
  test.skip(phase !== 'P6-LIVE', 'Live source smoke is separate from deterministic visual acceptance.');
  test.setTimeout(150_000); mkdirSync(output, { recursive: true });
  await page.setViewportSize({ width: 1536, height: 1100 });
  await installFixtures(page);
  const network = await installRealMapAssets(page);
  const receipts: object[] = [];
  await page.route('**/wm-api/runtime/world/natural-hazards/**', async route => {
    const incoming = new URL(route.request().url());
    const url = `https://polymonitor.club${incoming.pathname}${incoming.search}`;
    const started = Date.now();
    const response = await network.get(url, { timeout: 25_000 });
    const data = await response.json();
    receipts.push({ url, status: response.status(), ms: Date.now() - started, generatedAt: data.generatedAt,
      events: data.events?.length, sources: data.sources, errors: data.errors });
    await route.fulfill({ response, json: data });
  });
  try {
    await page.goto('/?view=2d&basemap=pmtiles&layers=earthquakes-volcanoes,weather-alerts,wildfires,climate-anomalies&time=7d');
    await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-basemap-state', 'primary-ready');
    await expect.poll(async () => Number(await page.locator('.wm-world-event-list-toggle strong').textContent()), { timeout: 45_000 }).toBeGreaterThan(0);
    await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(3000);
    await page.screenshot({ path: resolve(output, 'live-map.png') });
    writeFileSync(resolve(output, 'live-sources.json'), JSON.stringify({ observedAt: new Date().toISOString(), receipts,
      visibleEvents: await page.locator('.wm-world-event-list-toggle strong').textContent() }, null, 2));
  } finally { await page.unrouteAll({ behavior: 'ignoreErrors' }); await page.goto('about:blank'); await network.dispose(); }
});

// A real Chrome profile zoom preference, not DPR emulation or CSS transform.
test('product map at native 125 percent browser zoom', async () => {
  test.skip(!finalPhase, 'Final browser zoom matrix.');
  const profile = mkdtempSync('/tmp/polymonitor-zoom-');
  mkdirSync(resolve(profile, 'Default'));
  writeFileSync(resolve(profile, 'Default/Preferences'), JSON.stringify({ partition: { default_zoom_level: { x: Math.log(1.25) / Math.log(1.2) } } }));
  const context = await chromium.launchPersistentContext(profile, { channel: 'chrome', headless: true, viewport: null, deviceScaleFactor: undefined,
    reducedMotion: 'reduce', baseURL: 'http://127.0.0.1:4174',
    args: ['--window-size=1920,1080', '--disable-partial-raster', ...(process.env.POLYMONITOR_E2E_HARDWARE_WEBGL === '1' ? ['--use-angle=vulkan', '--enable-features=Vulkan'] : [])] });
  const page = context.pages()[0]!;
  await page.clock.setFixedTime(new Date(GENERATED_AT)); await installFixtures(page);
  const network = await installRealMapAssets(page);
  try {
    await page.goto('/?view=2d&mapPerf=1&basemap=pmtiles&center=0,20&zoom=1.5&time=all&layers=earthquakes-volcanoes,weather-alerts');
    const host = page.locator('[data-map-renderer-ready]');
    await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready');
    await page.evaluate(() => document.fonts.ready);
    const metrics = await host.evaluate(el => ({ browserZoom: 1.25, dpr: devicePixelRatio, cssWidth: innerWidth, outerWidth,
      visualScale: visualViewport!.scale, mapRect: el.getBoundingClientRect().toJSON(),
      canvas: [...el.querySelectorAll('canvas')].map(c => ({ width: c.width, cssWidth: c.clientWidth })) }));
    expect(metrics.outerWidth).toBe(1920); expect(metrics.cssWidth).toBe(1536); expect(metrics.dpr).toBe(1.25); expect(metrics.visualScale).toBe(1);
    for (const canvas of metrics.canvas) expect(Math.abs(canvas.width - canvas.cssWidth * 1.25)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: resolve(output, 'product-browser125.png') });
    await page.locator('.wm-map-legend-toggle').click(); await expect(page.locator('.wm-weather-deck-legend')).toBeVisible();
    await page.keyboard.press('Escape');
      if (await page.locator('.wm-world-event-list-close').isVisible()) await page.locator('.wm-world-event-list-close').click(); await page.locator('.wm-world-event-list-toggle').click();
    await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click();
    await expect(page.locator('.wm-event-inspector')).toBeVisible();
    await page.screenshot({ path: resolve(output, 'product-browser125-detail.png') });
    writeFileSync(resolve(output, 'product-browser125.json'), JSON.stringify(metrics, null, 2));
  } finally { await page.unrouteAll({ behavior: 'ignoreErrors' }); await context.close(); await network.dispose(); rmSync(profile, { recursive: true, force: true }); }
});
