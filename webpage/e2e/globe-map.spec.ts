import { hazard, mapResponse } from './fixtures/world-event-map';
import { expect, test } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';

test.describe('production globe asset delivery', () => {
  test.use({ serviceWorkers: 'allow' });
  test('the active service worker delivers a complete lazy globe module', async ({ page }) => {
    test.skip(process.env.POLYMONITOR_E2E_PREVIEW !== '1', 'Requires the built service worker.');
    await installDashboard(page);
    await page.clock.install({ time: new Date('2026-08-26T03:00:00Z') });
    const servedByWorker: boolean[] = [];
    page.on('response', response => {
      if (/\/assets\/GlobeMapRenderer-.*\.js/.test(response.url())) servedByWorker.push(response.fromServiceWorker());
    });
    // mapPerf disables registration at startup. Claim the real worker first,
    // then enable the renderer harness for CI's software WebGL if needed.
    const origin = `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || '4174'}`;
    await page.goto(`${origin}/?view=2d&time=all&basemap=openfreemap`);
    await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
    await page.evaluate(() => {
      const url = new URL(location.href); url.searchParams.set('mapPerf', '1');
      history.replaceState(null, '', url);
    });
    await page.getByRole('tab', { name: '3D Globe', exact: true }).click();
    await expect(page.locator('.wm-weather-deck-basemap')).toHaveAttribute('data-map-renderer-ready', 'globe', { timeout: 60000 });
    await expect(page.locator('.wm-globe-renderer')).toHaveAttribute('data-globe-records', '15');
    expect(servedByWorker).toContain(true);
  });
});

test('retry rechecks a temporary WebGL context creation failure', async ({ page }) => {
  await installDashboard(page);
  await page.clock.install({ time: new Date('2026-08-26T03:00:00Z') });
  await page.addInitScript(() => {
    (window as any).__blockMapContext = true;
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (kind: string, ...args: any[]) {
      if (kind === 'webgl2' && (window as any).__blockMapContext) return null;
      return (getContext as any).call(this, kind, ...args);
    } as typeof getContext;
  });
  await page.goto('/?view=3d&mapPerf=1&time=all');
  const host = page.locator('.wm-weather-deck-basemap');
  await expect(host).toHaveAttribute('data-map-renderer-ready', 'svg');
  await expect(host).toHaveAttribute('data-map-renderer-reason', 'WebGL2 context creation failed.');
  await page.evaluate(() => { (window as any).__blockMapContext = false; });
  await page.locator('.wm-map-renderer-retry').click();
  await expect(host).toHaveAttribute('data-map-renderer-ready', 'globe', { timeout: 60000 });
  await expect(page.locator('.wm-globe-renderer')).toHaveAttribute('data-globe-records', '15');
});

test('failed 3D module download can recover after the connection returns', async ({ page }) => {
  await installDashboard(page);
  await page.clock.install({ time: new Date('2026-08-26T03:00:00Z') });
  const module = /\/(?:assets\/GlobeMapRenderer-[^/]+\.js|src\/features\/world-event-map\/renderer\/GlobeMapRenderer\.ts)(?:\?.*)?$/;
  let attempts = 0;
  await page.route(module, route => { attempts++; return route.abort('connectionreset'); });
  await page.goto('/?view=2d&mapPerf=1&time=all&basemap=openfreemap');
  const host = page.locator('.wm-weather-deck-basemap');
  await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl', { timeout: 60000 });
  await page.getByRole('tab', { name: '3D Globe', exact: true }).click();
  await expect(host).toHaveAttribute('data-map-renderer-ready', 'svg');
  await expect(host).toHaveAttribute('data-map-renderer-reason', /import|module/i);
  await page.unroute(module);
  await page.locator('.wm-map-renderer-retry').click();
  await expect(host).toHaveAttribute('data-map-renderer-ready', 'globe', { timeout: 45000 });
  await expect(page.getByRole('tab', { name: '3D Globe', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.wm-globe-renderer')).toHaveAttribute('data-globe-records', '15');
  expect(attempts).toBe(1);
});

test('both globe and SVG module downloads failing still expose working recovery', async ({ page }) => {
  await installDashboard(page);
  await page.clock.install({ time: new Date('2026-08-26T03:00:00Z') });
  const modules = /\/(?:assets\/(?:Globe|Svg)MapRenderer-[^/]+\.js|src\/features\/world-event-map\/renderer\/(?:Globe|Svg)MapRenderer\.ts)(?:\?.*)?$/;
  await page.route(modules, route => route.abort('connectionreset'));
  await page.goto('/?view=3d&mapPerf=1&time=all');
  await expect(page.locator('.wm-weather-deck-basemap')).toHaveAttribute('data-map-basemap-state', 'failed');
  await expect(page.getByRole('button', { name: 'Reload map', exact: true })).toBeVisible();
  await page.unroute(modules);
  await page.getByRole('button', { name: 'Reload map', exact: true }).click();
  await expect(page.locator('.wm-weather-deck-basemap')).toHaveAttribute('data-map-renderer-ready', 'globe', { timeout: 60000 });
  await expect(page.locator('.wm-globe-renderer')).toHaveAttribute('data-globe-records', '15');
});

test('failed earth texture reports its cause and retries without losing records', async ({ page }) => {
  await installDashboard(page);
  await page.clock.install({ time: new Date('2026-08-26T03:00:00Z') });
  let attempts = 0;
  await page.route('**/textures/earth-topo-bathy.jpg', route => { attempts++; return route.abort('connectionreset'); });
  await page.goto('/?view=3d&mapPerf=1&time=all');
  const host = page.locator('.wm-weather-deck-basemap');
  await expect(host).toHaveAttribute('data-map-renderer-ready', 'svg', { timeout: 45000 });
  await expect(host).toHaveAttribute('data-map-renderer-reason', /3D Earth texture/i);
  expect(attempts).toBe(2);
  await page.unroute('**/textures/earth-topo-bathy.jpg');
  await page.locator('.wm-map-renderer-retry').click();
  await expect(host).toHaveAttribute('data-map-renderer-ready', 'globe', { timeout: 45000 });
  await expect(page.locator('.wm-globe-renderer')).toHaveAttribute('data-globe-records', '15');
});

test('leaving 3D cancels a pending texture and cannot install a late globe', async ({ page }) => {
  await installDashboard(page);
  await page.clock.install({ time: new Date('2026-08-26T03:00:00Z') });
  let release: (() => void) | undefined;
  let requested = false;
  let cancelled = false;
  page.on('requestfailed', request => {
    if (request.url().endsWith('/textures/earth-topo-bathy.jpg')) cancelled = true;
  });
  await page.route('**/textures/earth-topo-bathy.jpg', async route => {
    requested = true;
    await new Promise<void>(resolve => { release = resolve; });
    await route.continue().catch(() => {});
  });
  await page.goto('/?view=3d&mapPerf=1&time=all&basemap=openfreemap');
  await expect.poll(() => requested).toBe(true);
  await page.getByRole('tab', { name: '2D Map', exact: true }).click();
  await expect.poll(() => cancelled).toBe(true);
  release?.();
  await page.unroute('**/textures/earth-topo-bathy.jpg');
  const host = page.locator('.wm-weather-deck-basemap');
  await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl', { timeout: 60000 });
  await expect(page.locator('.wm-globe-renderer')).toHaveCount(0);
  await page.getByRole('tab', { name: '3D Globe', exact: true }).click();
  await expect(host).toHaveAttribute('data-map-renderer-ready', 'globe', { timeout: 60000 });
  await expect(page.locator('.wm-globe-renderer')).toHaveCount(1);
});

test('returning to 3D repeatedly paints a globe and releases the previous context', async ({ page }) => {
  test.setTimeout(180000);
  await installDashboard(page);
  await page.clock.install({ time: new Date('2026-08-26T03:00:00Z') });
  await page.goto('/?view=3d&mapPerf=1&time=all&basemap=openfreemap');
  const host = page.locator('.wm-weather-deck-basemap');
  for (let cycle = 0; cycle < 4; cycle++) {
    await expect(host).toHaveAttribute('data-map-renderer-ready', 'globe', { timeout: 60000 });
    await expect(page.locator('.wm-globe-renderer')).toHaveAttribute('data-globe-records', '15');
    const canvas = await page.locator('.wm-globe-renderer canvas').first().elementHandle();
    await canvas!.evaluate((element: HTMLCanvasElement) => {
      (window as any).__retiredGlobeContext = element.getContext('webgl2');
    });
    await page.getByRole('tab', { name: '2D Map', exact: true }).click();
    await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl', { timeout: 60000 });
    await expect.poll(() => page.evaluate(() => (window as any).__retiredGlobeContext.isContextLost())).toBe(true);
    await page.getByRole('tab', { name: '3D Globe', exact: true }).click();
  }
  await expect(host).toHaveAttribute('data-map-renderer-ready', 'globe', { timeout: 60000 });
  await expect(page.locator('.wm-globe-renderer')).toHaveCount(1);
  await expect(page.locator('.wm-globe-renderer')).toHaveAttribute('data-globe-records', '15');
});

test('2D does not download the globe engine or texture',async({page})=>{
  const downloads:string[]=[];
  page.on('request',request=>{if(/GlobeMapRenderer|earth-topo-bathy|globe_gl|three\.module/.test(request.url()))downloads.push(request.url());});
  await installDashboard(page);
  await page.goto('/?view=2d&mapPerf=1&basemap=openfreemap');
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready',/webgl|svg/,{timeout:60000});
  expect(downloads).toEqual([]);
});

test('3D quality scales high density pixels without dropping records', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  try {
    const page = await context.newPage();
    await installDashboard(page);
    await page.clock.install({ time: new Date('2026-08-26T03:00:00Z') });
    await page.goto('http://127.0.0.1:4174/?view=3d&mapPerf=1&time=all');
    const globe = page.locator('.wm-globe-renderer');
    await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'globe', { timeout: 60000 });
    await expect(globe).toHaveAttribute('data-globe-records', '15');
    const backingScale = () => globe.locator('canvas').first().evaluate(canvas =>
      (canvas as HTMLCanvasElement).width / canvas.clientWidth);
    for (const [quality, scale] of [['high', 2], ['performance', 1], ['high', 2]] as const) {
      await globe.locator('select').selectOption(quality);
      await expect.poll(backingScale).toBe(scale);
      await expect(globe).toHaveAttribute('data-globe-records', '15');
    }
  } finally { await context.close(); }
});

test('3D context failure falls back and recovers the same filtered records',async({page})=>{
  test.setTimeout(180000);
  await installDashboard(page);
  await page.clock.install({time:new Date('2026-08-26T03:00:00Z')});
  await page.goto('/?view=3d&mapPerf=1&time=all&center=-70,43&zoom=3');
  const host=page.locator('[data-map-renderer-ready]');
  await expect(host).toHaveAttribute('data-map-renderer-ready','globe',{timeout:60000});
  const globe=page.locator('.wm-globe-renderer');
  await expect.poll(async()=>Number(await globe.getAttribute('data-globe-records'))).toBeGreaterThan(0);
  await expect(globe).toHaveAttribute('data-globe-aircraft','1');
  const records=await globe.getAttribute('data-globe-records');
  for (let episode=0;episode<2;episode++) {
  await globe.locator('canvas').first().evaluate(canvas=>{
    const gl=(canvas as HTMLCanvasElement).getContext('webgl2')!;
    const extension=gl.getExtension('WEBGL_lose_context');
    if(!extension)throw new Error('Context loss extension unavailable');
    extension.loseContext();
  });
  await expect(host).toHaveAttribute('data-map-renderer-ready','svg',{timeout:30000});
  await page.getByRole('button',{name:'Retry detailed map'}).click();
  await expect(host).toHaveAttribute('data-map-renderer-ready','globe',{timeout:60000});
  await expect(globe).toHaveAttribute('data-globe-records',records!);
  await expect(page.locator('.wm-map-renderer-retry')).toHaveCount(0);
  }
  await page.screenshot({path:'artifacts/map-unified-renderer-20261003/candidate/globe-recovered.png'});
});


test('static batching keeps exact globe pixels and native event picking', async ({ page }) => {
  await installDashboard(page);
  await page.clock.install({ time: new Date('2026-08-26T03:00:00Z') });
  const areas = Array.from({ length: 12 }, (_, i) => {
    const x = -20 + (i % 4) * 10, y = 10 + Math.floor(i / 4) * 10;
    return hazard({ id: `batch-fixture:${i}`, title: `Batch fixture ${i}`, hazardKind: 'flood',
      metrics: { kind: 'weather-alert' }, geometry: { type: 'Polygon', coordinates: [[[x,y],[x+12,y],[x+12,y+12],[x,y+12],[x,y]]] } });
  });
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**', route => {
    if (new URL(route.request().url()).searchParams.get('source') === 'nws') return route.fulfill({ json: mapResponse('nws', areas) });
    return route.fallback();
  });
  await page.goto('/?view=3d&mapPerf=1&time=all&center=0,25&zoom=1.5');
  const globe = page.locator('.wm-globe-renderer');
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'globe', { timeout: 60000 });
  await expect.poll(async () => Number(await globe.getAttribute('data-globe-records'))).toBeGreaterThan(20);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(500);
  const toggle = (enabled: boolean) => globe.evaluate((element, enabled) => (element as any).__polymonitorGlobeBatch(enabled), enabled);
  await toggle(false); await page.waitForTimeout(100);
  const native = await globe.screenshot({ path: "artifacts/map-performance-optimization-20261004/batch-native.png" });
  await toggle(true); await page.waitForTimeout(100);
  expect((await globe.screenshot({ path: "artifacts/map-performance-optimization-20261004/batch-candidate.png" })).equals(native)).toBe(true);
  await expect.poll(async () => Number(await globe.getAttribute('data-globe-occluded-objects'))).toBeGreaterThan(0);
  const before = Number(await globe.getAttribute('data-globe-frames'));
  await page.waitForTimeout(500);
  expect(Number(await globe.getAttribute('data-globe-frames')) - before).toBeLessThanOrEqual(1);
  const canvas = globe.locator('canvas').first(), box = await canvas.boundingBox();
  await page.mouse.click(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await expect(page.locator('.wm-event-inspector-titleline')).toBeVisible();
  await page.locator('.wm-event-inspector-close').click();
  const beforeDrag = new URL(page.url()).searchParams.get('center');
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.down();
  for (let i = 1; i <= 5; i++) {
    await page.mouse.move(box!.x + box!.width / 2 + i * 12, box!.y + box!.height / 2);
    await page.waitForTimeout(160); // slower than debounce: a held gesture still stays local
    expect(new URL(page.url()).searchParams.get('center')).toBe(beforeDrag);
  }
  await page.mouse.up();
  await expect.poll(() => new URL(page.url()).searchParams.get('center')).not.toBe(beforeDrag);
  // Occlusion is conservative at a moved camera and at two globe distances.
  for (const action of ['Zoom in', 'Zoom out']) {
    await page.getByRole('button', { name: action, exact: true }).click();
    await page.mouse.move(0, 0);
    await page.waitForTimeout(500);
    await toggle(false); await page.waitForTimeout(100);
    const allGeometry = await globe.screenshot({ path: `artifacts/map-performance-optimization-20261004/${action}-native.png` });
    await toggle(true); await page.waitForTimeout(100);
    expect((await globe.screenshot({ path: `artifacts/map-performance-optimization-20261004/${action}-culled.png` })).equals(allGeometry)).toBe(true);
  }
  const beforeExit = new URL(page.url()).searchParams.get('center');
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width / 2 + 50, box!.y + box!.height / 2);
  await page.mouse.up();
  // Switch before the 120ms settle timer: the retiring renderer must preserve
  // its final camera, while still invalidating all later asynchronous results.
  await page.getByRole('tab', { name: '2D Map', exact: true }).evaluate(button => (button as HTMLElement).click());
  await expect.poll(() => new URL(page.url()).searchParams.get('center')).not.toBe(beforeExit);
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'webgl');
});
