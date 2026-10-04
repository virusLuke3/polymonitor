import { test, expect } from '@playwright/test';
import { installFixtures, GENERATED_AT } from './fixtures/world-event-map';
import { installRealMapAssets } from './fixtures/real-map-assets';
import { installDashboard } from './fixtures/dashboard';
import { hazard, mapResponse } from './fixtures/world-event-map';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Opt-in workload benchmark; ordinary regression runs keep the focused tests below.
// Synthetic coordinates are test data only, never a production source or visual golden.
if (process.env.MAP_PERFORMANCE_RUN) for (const count of [2000, 4500]) for (const width of [1440, 390]) {
  test(`fixed workload ${count} records at ${width}`, async ({ page }) => {
    test.setTimeout(240000);
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await installDashboard(page);
    // globe.gl's debouncer needs an advancing Date clock. A permanently fixed
    // Date with running timers prevents its initial digest from ever settling.
    await page.clock.install({ time: new Date(GENERATED_AT) });
    const records = Array.from({ length: count }, (_, i) => {
      const x = -170 + (i % 100) * 3.4, y = -65 + Math.floor(i / 100) * 2.6;
      return hazard({ id: `performance-fixture:${i}`, title: `Performance fixture ${i}`,
        hazardKind: i % 3 ? 'earthquake' : 'flood', severity: i % 7 ? 'watch' : 'warning',
        metrics: i % 3 ? { kind: 'earthquake', magnitude: 4.1 } : { kind: 'weather-alert' },
        geometry: i % 3 ? { type: 'Point', coordinates: [x, y] }
          : { type: 'Polygon', coordinates: [[[x,y],[x+2,y],[x+2,y+2],[x,y+2],[x,y]]] },
      });
    });
    await page.route('**/wm-api/runtime/world/natural-hazards/map?**', route =>
      new URL(route.request().url()).searchParams.get('source') === 'nws'
        ? route.fulfill({ json: mapResponse('nws', records) }) : route.fallback());
    await page.addInitScript(() => {
      (window as any).__perfTasks = [];
      new PerformanceObserver(list => (window as any).__perfTasks.push(...list.getEntries().map(e => ({at:e.startTime,ms:e.duration}))))
        .observe({ type: 'longtask', buffered: true });
    });
    const directory = resolve(`artifacts/map-performance-closure-20261004/${process.env.MAP_PERFORMANCE_RUN}`);
    mkdirSync(directory, { recursive: true });
    const identity = { count, width, fixture: createHash('sha256').update(JSON.stringify(records)).digest('hex') };
    const measurements = [];
    await page.goto('/?view=2d&basemap=openfreemap&mapPerf=1&time=all&center=0,20&zoom=1.5');
    const host = page.locator('[data-map-renderer-ready]');
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Performance.enable');
    const metrics = async () => Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map((e:any) => [e.name,e.value]));
    for (const kind of ['webgl', 'globe']) {
      await page.evaluate(() => { (window as any).__perfTasks = []; });
      const switchStart = Date.now();
      if (kind === 'globe') await page.getByRole('tab', { name: '3D Globe', exact: true }).click();
      await expect(host).toHaveAttribute('data-map-renderer-ready', kind, { timeout: 90000 });
      await expect.poll(async () => Number((await page.locator('.wm-world-event-list-toggle strong').textContent())?.replace(/\D/g,''))).toBeGreaterThanOrEqual(count);
      const readyMs = Date.now() - switchStart;
      const startupLongTasks = await page.evaluate(() => [...(window as any).__perfTasks]);
      await page.locator('.wm-map-stage').scrollIntoViewIfNeeded();
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(3000);
      await page.mouse.move(0,0);
      const filename = `${kind}-${count}-${width}.png`;
      const pixels = await page.locator('.wm-map-stage').screenshot({ path: resolve(directory, filename) });
      if (process.env.MAP_PERFORMANCE_BASELINE) {
        expect(pixels.equals(readFileSync(resolve(process.env.MAP_PERFORMANCE_BASELINE, filename)))).toBe(true);
      }
      await page.emulateMedia({ reducedMotion: 'no-preference' });
      await page.waitForTimeout(500);
      const start = await metrics();
      const frames = () => page.locator('.wm-globe-renderer').count().then(n => n ? page.locator('.wm-globe-renderer').getAttribute('data-globe-frames').then(Number) : 0);
      const firstFrame = await frames(), startTime = Date.now();
      await page.waitForTimeout(5000);
      const elapsedMs = Date.now()-startTime, drawnFrames = await frames()-firstFrame, end = await metrics();
      const box = (await host.boundingBox())!;
      const interactionStart = Date.now();
      await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5); await page.mouse.down();
      for (let step=0;step<15;step++) await page.mouse.move(box.x+box.width*.5+step*3,box.y+box.height*.5);
      await page.mouse.up(); await page.mouse.wheel(0,-100); await page.waitForTimeout(500);
      measurements.push({kind,readyMs,startupLongTasks,elapsedMs,drawnFrames:kind==='globe'?drawnFrames:null,fps:kind==='globe'?drawnFrames*1000/elapsedMs:null,
        busyPercent:(end.TaskDuration-start.TaskDuration)*100000/elapsedMs,interactionMs:Date.now()-interactionStart,
        longTasks:await page.evaluate(() => (window as any).__perfTasks),
        globe:await page.locator('.wm-globe-renderer').count() ? await page.locator('.wm-globe-renderer').evaluate(e=>({... (e as HTMLElement).dataset})) : null});
      await page.emulateMedia({reducedMotion:'reduce'});
      // Restore the exact camera through the existing shared URL state for the next view.
      if(kind==='webgl') {
        await page.goto('/?view=2d&basemap=openfreemap&mapPerf=1&time=all&center=0,20&zoom=1.5');
        await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');
      }
    }
    writeFileSync(resolve(directory, `${count}-${width}.json`), JSON.stringify({ ...identity, measurements },null,2));
  });
}

// Performance and pixel comparisons use the same Chrome raster backend as
// their pre-change baseline. Do not silently compare it with SwiftShader.
test.use({ launchOptions: { args: [
  '--disable-partial-raster', '--use-angle=vulkan', '--enable-features=Vulkan',
] } });

test.beforeEach(async ({page}) => { await page.clock.setFixedTime(new Date(GENERATED_AT)); await installFixtures(page); });
test.afterEach(async ({page}) => {await page.unrouteAll({behavior:'ignoreErrors'});await page.goto('about:blank');});

test('basemap paints before delayed map fonts, then keeps the same renderer after fonts arrive', async ({page})=>{
  let release!:()=>void;const held=new Promise<void>(resolve=>{release=resolve;});let waiting=0;
  await page.route('**/*noto-sans*.woff2',async route=>{waiting++;await held;await route.fallback();});
  try {
    // Deliberately pending fonts keep the document load event pending too.
    await page.goto('/?view=2d&basemap=openfreemap&mapPerf=1', { waitUntil: 'domcontentloaded' });
    await page.locator('.wm-map-section').scrollIntoViewIfNeeded();
    const host=page.locator('[data-map-renderer-ready]');
    await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');
    await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');
    expect(waiting).toBeGreaterThan(0);
    const canvas=page.locator('.maplibregl-canvas');const original=await canvas.elementHandle();
    release();await page.evaluate(()=>document.fonts.ready);
    expect(await canvas.evaluate((node,old)=>node===old,original)).toBe(true);
    await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');
  } finally {release();}
});

test('aircraft motion does not keep submitting static map layers',async({page})=>{
  await page.goto('/?view=2d&basemap=openfreemap&mapPerf=1');
  await page.locator('.wm-map-section').scrollIntoViewIfNeeded();
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready','webgl');
  await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(8000);
  await page.evaluate(()=>window.__POLYMONITOR_MAP_PERF__!.reset());await page.waitForTimeout(4000);
  const perf=await page.evaluate(()=>window.__POLYMONITOR_MAP_PERF__!.snapshot());
  expect(perf.phases['dynamic-commit'].count).toBeGreaterThan(15);
  expect(perf.phases['deck-commit'].count).toBeLessThan(8);
  expect(perf.phases['label-layout'].count).toBeLessThan(5);
});

test('radar tile failure recovers within its first bounded retry while the map stays usable',async({page})=>{
  let fail=true,failed=0;
  await page.route('https://tilecache.rainviewer.com/v2/radar/**',async route=>{
    if(fail){failed++;return route.fulfill({status:503,body:'temporary tile failure'});}return route.fallback();
  });
  await page.goto('/?view=2d&basemap=openfreemap&mapPerf=1');
  await page.locator('.wm-map-section').scrollIntoViewIfNeeded();
  const host=page.locator('[data-map-renderer-ready]'),radar=page.locator('.wm-map-radar-status');
  await expect(radar).toHaveAttribute('data-radar-tiles','error');expect(failed).toBeGreaterThan(0);
  fail=false;await expect(radar).toHaveAttribute('data-radar-tiles','ready',{timeout:15000});
  await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');
  await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');
});

for (const width of [1440, 390]) test(`fixed map appearance ${width}`, async ({page})=>{
  await page.setViewportSize({width,height:width===390?844:900});
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.goto('/?view=2d&basemap=openfreemap&mapPerf=1&center=0,20&zoom=1.5&time=all');
  await page.locator('.wm-map-section').scrollIntoViewIfNeeded();
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-basemap-state','primary-ready');
  await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(6000);
  expect(await page.evaluate(() => [...document.fonts].some(font =>
    font.family.includes('Noto Sans SC') && font.status === 'loaded'))).toBe(true);
  await page.mouse.move(0,0);
  await expect(page.locator('.wm-map-stage')).toHaveScreenshot(`map-performance-${width}.png`,{maxDiffPixels:0});
});

test('visible renderer downloads before idle admission and explicit SVG does not download it', async({page})=>{
  let requested=0;
  page.on('request',request=>{if(/\/DeckMapRenderer(?:\.ts|-[\w-]+\.js)/.test(request.url()))requested++;});
  await page.addInitScript(()=>{
    // Hold CPU admission but leave module download free to overlap the shell.
    window.requestIdleCallback=callback=>{(window as any).__releaseMapIdle=()=>callback({didTimeout:false,timeRemaining:()=>50});return 123;};
    const original=window.setTimeout.bind(window);
    window.setTimeout=((callback:any,ms?:number,...args:any[])=>ms===2500?original(callback,30000,...args):original(callback,ms,...args)) as typeof window.setTimeout;
  });
  await page.goto('/?view=2d&basemap=openfreemap&mapPerf=1',{waitUntil:'domcontentloaded'});
  await page.locator('.wm-map-section').scrollIntoViewIfNeeded();
  await expect.poll(()=>requested).toBeGreaterThan(0);
  expect(await page.locator('.maplibregl-canvas').count()).toBe(0);
  await page.evaluate(()=>(window as any).__releaseMapIdle());
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-basemap-state','primary-ready');
  requested=0;
  await page.goto('/?view=2d&renderer=svg',{waitUntil:'domcontentloaded'});
  await page.locator('.wm-map-section').scrollIntoViewIfNeeded();
  await page.waitForFunction(()=>Boolean((window as any).__releaseMapIdle));
  await page.evaluate(()=>(window as any).__releaseMapIdle());
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready','svg');
  expect(requested).toBe(0);
});

test('primary PMTiles style downloads both same-origin sprite assets in dark and light themes', async ({page}) => {
  const assets = await installRealMapAssets(page);
  try {
    for (const theme of ['dark', 'positron']) {
      const name = theme === 'dark' ? 'dark' : 'light';
      // Primary-ready alone does not prove the style's sprites loaded:
      // MapLibre can paint vectors after rejecting an invalid sprite URL.
      const responses = ['json', 'png'].map(extension => page.waitForResponse(response =>
        new URL(response.url()).pathname === `/map-assets/protomaps-sprites-v4/${name}.${extension}`));
      await page.goto(`/?view=2d&basemap=pmtiles&mapPerf=1&theme=${theme}`, {waitUntil:'domcontentloaded'});
      await page.locator('.wm-map-section').scrollIntoViewIfNeeded();
      for (const response of await Promise.all(responses)) {
        expect(response.ok()).toBe(true);
        expect(new URL(response.url()).origin).toBe(new URL(page.url()).origin);
        expect((await response.body()).length).toBeGreaterThan(100);
      }
      await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-basemap-state', 'primary-ready');
    }
  } finally { await page.goto('about:blank'); await assets.dispose(); }
});
