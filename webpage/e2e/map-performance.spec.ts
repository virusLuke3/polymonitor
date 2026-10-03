import { test, expect } from '@playwright/test';
import { installFixtures, GENERATED_AT } from './fixtures/world-event-map';
import { installRealMapAssets } from './fixtures/real-map-assets';

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
