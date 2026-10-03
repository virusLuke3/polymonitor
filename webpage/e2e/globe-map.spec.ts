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
    await page.goto('/?view=2d&time=all&basemap=openfreemap');
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
