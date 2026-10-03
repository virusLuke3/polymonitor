import { gotoMapScene, selectMapLayers } from './fixtures/browser';
import { expect, test, type Page } from '@playwright/test';
import { fixtureBundle, installDashboard } from './fixtures/dashboard';
import { installFixtures } from './fixtures/world-event-map';

test.afterEach(async ({ page }) => {
  // Assertions have finished. Detach routes before aborting the document so
  // pending image/module transfers cannot escape into the next test's teardown.
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  await page.goto('about:blank');
});

async function settled(page: Page) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(1200);
}

// Layout baselines reflect the reviewed map controls and composition.
// No masks: clock, API data, locale, renderer and motion are deterministic.
async function visual(page: Page, name: string) {
  await settled(page);
  await expect.soft(page).toHaveScreenshot(name, { animations: 'disabled', maxDiffPixels: 0, threshold: 0 });
}

for (const width of [1440, 390]) {
  for (const locale of ['en', 'zh']) {
    test(`dashboard ${width} ${locale}: map, focus, panels, settings and commands`, async ({ page }) => {
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await installDashboard(page, locale);
      await gotoMapScene(page, '/?view=2d&mapPerf=1&renderer=svg&time=all&layers=earthquakes-volcanoes,wildfires&center=-98,39&zoom=2.2');
      await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', /webgl|svg/, { timeout: 60_000 });
      await expect(page.locator('.wm-banner')).toHaveCount(0);
      await visual(page, `home-${width}-${locale}.png`);
      await page.locator('.wm-focused-market-row').scrollIntoViewIfNeeded();
      await visual(page, `focus-${width}-${locale}.png`);
      await page.locator('[data-workspace-panel-id="global-transport-shipping"]').scrollIntoViewIfNeeded();
      await visual(page, `panels-${width}-${locale}.png`);
      await page.locator('.wm-more-nav summary').click();
      await page.getByRole('menuitem', { name: /settings|设置/i }).click();
      await expect(page.locator('.wm-settings-modal')).toBeVisible();
      await visual(page, `settings-${width}-${locale}.png`);
      await page.keyboard.press('Escape');
      await page.keyboard.press('Control+k');
      await expect(page.locator('.wm-command-modal')).toBeVisible();
      await page.locator('.wm-command-input').fill('fixture');
      await visual(page, `commands-${width}-${locale}.png`);
      expect(errors).toEqual([]);
    });
  }
}

for (const path of ['/login', '/account', '/watchlist', '/briefings', '/developers', '/data-quality', '/markets/1']) {
  for (const width of [1440, 390]) {
    test(`route ${path} ${width}`, async ({ page }) => {
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await installDashboard(page);
      // The login entry is characterized independently of authenticated pages.
      if (path === '/login') await page.route('**/auth/session', (route) => route.fulfill({ json: { enabled: true, authenticated: false, user: null, csrfToken: null, allowedScopes: [] } }));
      await gotoMapScene(page, path);
      const readySelector: Record<string, string> = {
        '/login': '.auth-login-layout', '/account': '.auth-account',
        '/watchlist': '.watchlist-main', '/briefings': '.brief-manager-main',
        '/developers': '.developer-main', '/data-quality': '.quality-error-banner',
        '/markets/1': '.market-main',
      };
      await expect(page.locator(readySelector[path]!)).toBeVisible();
      await visual(page, `route-${path.replaceAll('/', '-')}-${width}.png`);
      expect(errors).toEqual([]);
      if (path !== '/login') expect(new URL(page.url()).pathname).toBe(path);
    });
  }
}

for (const width of [1440, 390]) {
  test(`Chinese map filters keep their captions with warm fonts ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await installDashboard(page, 'zh');
    // Force the cold CJK face to arrive after the controls first render.
    await page.route(/noto-sans-sc.*\.woff2/, async route => {
      await new Promise(resolve => setTimeout(resolve, 1000));
      await route.fallback();
    });
    await gotoMapScene(page, '/?view=2d&mapPerf=1&renderer=svg&time=all&layers=earthquakes-volcanoes');
    if (width === 390) await page.locator('.wm-map-filter-details > summary').click();
    const controls = page.locator('.wm-world-event-basemap-control');
    await expect(controls).toHaveCount(2);
    await settled(page);
    const cold = await Promise.all([0, 1].map(i => controls.nth(i).screenshot({ animations: 'disabled' })));
    await page.unroute(/noto-sans-sc.*\.woff2/);
    await page.reload();
    await selectMapLayers(page, ['earthquakes-volcanoes']);
    if (width === 390) await page.locator('.wm-map-filter-details > summary').click();
    await expect(controls).toHaveCount(2);
    await settled(page);
    for (let i = 0; i < 2; i++) {
      expect(await controls.nth(i).screenshot({ animations: 'disabled' })).toEqual(cold[i]);
    }
    const theme = controls.nth(1).locator('select');
    await theme.focus();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await expect(theme).toHaveValue('positron');
    await expect(theme).toBeFocused();
    await page.goto('about:blank');
    await page.unrouteAll({ behavior: 'wait' });
  });

  test(`Chinese market sort keeps its caption with warm fonts ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await installDashboard(page, 'zh');
    await gotoMapScene(page, '/?view=2d&mapPerf=1&renderer=svg&time=all&layers=earthquakes-volcanoes,wildfires&center=-98,39&zoom=2.2');
    await expect(page.locator('.wm-market-sort')).toBeVisible();
    await settled(page);
    const caption = page.locator('.wm-market-sort-caption');
    await caption.evaluate(el => el.scrollIntoView({ block: 'center' }));
    const coldCaption = await caption.screenshot({ animations: 'disabled' });
    // Reload after the locale font is cached: the native select used to choose
    // a different anonymous line box here than when the font arrived late.
    await page.reload();
    await selectMapLayers(page, ['earthquakes-volcanoes', 'wildfires']);
    await expect(caption).toBeVisible();
    await caption.evaluate(el => el.scrollIntoView({ block: 'center' }));
    await settled(page);
    expect(await caption.screenshot({ animations: 'disabled' })).toEqual(coldCaption);
    const sort = page.getByRole('combobox', { name: '市场排序', exact: true });
    await expect(caption).toHaveText('活跃度与成交量');
    await expect(caption).toHaveCSS('line-height', '14px');
    await sort.focus();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await expect(sort).toHaveValue('volume');
    await expect(caption).toHaveText('成交量');
    await expect(sort).toBeFocused();
    await expect(page.locator('.wm-market-sort-explainer')).toContainText('24 小时成交量');
  });
}

for (const width of [1440, 390]) {
  test(`map details and source failure ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await installDashboard(page);
    await gotoMapScene(page, '/?view=2d&mapPerf=1&renderer=svg&time=all&layers=earthquakes-volcanoes,wildfires&center=-98,39&zoom=2.2');
    await expect(page.getByRole('button', { name: /^All events/i })).toContainText('9');
    await page.getByRole('button', { name: /^All events/i }).click();
    await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click();
    await expect(page.locator('.wm-event-inspector')).toBeVisible();
    // Focus must settle without scrolling the page or the clipped map canvas.
    await expect(page.locator('#wm-event-inspector-title')).toBeFocused();
    // The clicked list row disappears; park the pointer so the revealed layer
    // checkbox does not acquire an incidental hover in this report scene.
    await page.mouse.move(0, 0);
    await visual(page, `map-selected-${width}.png`);
    await page.getByRole('button', { name: 'Close event details' }).click();
    // Returning from a report now restores the retained reading list. Close
    // it explicitly before characterizing the map toggle's keyboard focus.
    await page.getByRole('button', { name: 'Close all events drawer', exact: true }).click();
    await page.getByRole('button', { name: /^All events/i }).focus();
    await visual(page, `map-focus-${width}.png`);
    await page.unrouteAll({ behavior: 'wait' });
    // This scene exercises a cold unavailable source. All-on entry populated
    // the last-good cache above; do not confuse retained stale data with empty.
    await page.evaluate(async () => {
      for (const key of Object.keys(localStorage)) if (key.startsWith('polymonitor:hazard-map:last-good:')) localStorage.removeItem(key);
      await new Promise<void>((resolve, reject) => {
        const request = indexedDB.open('polymonitor-world-event-map');
        request.onerror = () => reject(request.error);
        request.onsuccess = () => { const db = request.result;
          if (!db.objectStoreNames.contains('hazard-source-snapshots')) { db.close(); resolve(); return; }
          const tx = db.transaction('hazard-source-snapshots', 'readwrite');
          tx.objectStore('hazard-source-snapshots').clear();
          tx.oncomplete = () => { db.close(); resolve(); }; tx.onerror = () => { db.close(); reject(tx.error); };
        };
      });
    });
    await installFixtures(page, true);
    await gotoMapScene(page, '/?view=2d&mapPerf=1&renderer=svg&time=all&layers=weather-alerts,earthquakes-volcanoes,climate-anomalies');
    await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', /webgl|svg/, { timeout: 60_000 });
    const layersButton = page.getByRole('button', { name: 'Open layers panel' });
    if (await layersButton.isVisible()) await layersButton.click();
    await expect(page.locator('.wm-layer-row.is-unavailable')).not.toHaveCount(0);
    await visual(page, `map-degraded-${width}.png`);
  });
  test(`3d globe ${width}`, async ({ page }) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await installDashboard(page);
    await page.clock.install({ time: new Date('2026-08-26T03:00:00Z') });
    await page.goto('/?view=3d&mapPerf=1&basemap=openfreemap&time=all');
    const host=page.locator('[data-map-renderer-ready]');
    await expect(host).toHaveAttribute('data-map-renderer-ready','globe',{timeout:60000});
    const globe=page.locator('.wm-globe-renderer'), canvas=globe.locator('canvas').first();
    // Wait for the complete fixed source inventory, including late shared feeds.
    await expect(globe).toHaveAttribute('data-globe-records','15');
    await page.evaluate(() => document.fonts.ready);
    const records=await globe.getAttribute('data-globe-records');
    await globe.locator('select').selectOption('performance');
    await expect(globe).toHaveAttribute('data-globe-records',records!);
    await globe.locator('select').selectOption('high');
    await expect(globe).toHaveClass(/is-render-idle/);
    await expect.poll(()=>canvas.evaluate(c=>Math.abs(c.getBoundingClientRect().height-c.closest('.wm-globe-renderer')!.clientHeight))).toBeLessThan(1);
    const qualityOverlaps = () => page.evaluate(() => {
      const quality = document.querySelector('.wm-globe-quality-select')!.getBoundingClientRect();
      const aviation = document.querySelector('.wm-aviation-lens')!.getBoundingClientRect();
      return Math.min(quality.right, aviation.right) > Math.max(quality.left, aviation.left)
        && Math.min(quality.bottom, aviation.bottom) > Math.max(quality.top, aviation.top);
    });
    expect(await qualityOverlaps()).toBe(false);
    if (width === 1440) {
      await page.getByRole('button', { name: 'Expand aviation details' }).click();
      expect(await qualityOverlaps()).toBe(false);
      await page.getByRole('button', { name: 'Expand aviation details' }).click();
    }
    await expect(globe).toHaveScreenshot(`globe-shared-${width}.png`,{animations:'disabled',maxDiffPixels:0,threshold:0});
    const before=await canvas.screenshot();
    await page.getByRole('button',{name:'Zoom in',exact:true}).click();
    await expect(globe).toHaveClass(/is-render-idle/);
    expect((await canvas.screenshot()).equals(before)).toBe(false);
    const camera=new URL(page.url()).searchParams.get('zoom');
    if(width===390)await page.locator('.wm-map-filter-details > summary').click();
    await page.getByRole('button',{name:'Critical',exact:true}).click();
    await expect.poll(async()=>Number(await globe.getAttribute('data-globe-records'))).toBeLessThan(Number(records));
    const filtered=await globe.getAttribute('data-globe-records');
    await page.getByRole('button',{name:'Records',exact:true}).click();
    await expect(globe).toHaveAttribute('data-globe-records',filtered!);
    // The short fixture dashboard needs a scroll target below the map to
    // exercise a real IntersectionObserver transition on desktop as well.
    await page.locator('.wm-main-content').evaluate(el=>{
      const spacer=document.createElement('div');spacer.dataset.globeScrollTarget='true';spacer.style.cssText='height:2000px;flex-shrink:0';el.append(spacer);
    });
    await page.locator('[data-globe-scroll-target]').scrollIntoViewIfNeeded();
    await expect(globe).toHaveAttribute('data-render-paused','true');
    await page.getByRole('tab',{name:'3D Globe',exact:true}).scrollIntoViewIfNeeded();
    await expect(globe).toHaveAttribute('data-render-paused','false');
    await page.locator('[data-globe-scroll-target]').evaluate(el=>el.remove());
    await expect(globe).toHaveAttribute('data-globe-records',filtered!);
    await page.setViewportSize({width:width-30,height:width===390?800:850});
    await expect.poll(()=>canvas.evaluate(c=>Math.abs(c.getBoundingClientRect().width-c.closest('.wm-globe-renderer')!.clientWidth))).toBeLessThan(1);
    await page.getByRole('tab',{name:'2D Map',exact:true}).click();
    await page.locator('.wm-map-stage').scrollIntoViewIfNeeded();
    await expect(globe).toHaveCount(0);
    await expect(host).toHaveAttribute('data-map-renderer-ready',/webgl|svg/,{timeout:60000});
    expect(new URL(page.url()).searchParams.get('zoom')).toBe(camera);
    await expect(page.getByRole('button',{name:'Critical',exact:true})).toHaveAttribute('aria-pressed','false');
    await page.getByRole('tab',{name:'3D Globe',exact:true}).click();
    await page.locator('.wm-map-stage').scrollIntoViewIfNeeded();
    await expect(host).toHaveAttribute('data-map-renderer-ready','globe',{timeout:60000});
    await expect(globe).toHaveAttribute('data-globe-records',filtered!);
    expect(errors).toEqual([]);
  });
}


test('effective panel sizes at every breakpoint', async ({ page }) => {
  const ids = ['market-tv-wire', 'market-youtube-channels', 'breaking-event-radar', 'global-transport-shipping', 'global-temperature-monitor', 'market-summary'];
  await installDashboard(page, 'en', ids);
  await gotoMapScene(page, '/?view=2d&layers=earthquakes-volcanoes');
  await expect(page.locator('[data-workspace-panel-id="market-tv-wire"]')).toBeAttached();
  const layouts = [];
  for (const width of [1600, 1501, 1500, 1101, 1100, 761, 760, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(500);
    layouts.push({ width, panels: await page.locator('.wm-panels-grid > .wm-panel-slot').evaluateAll((elements) => elements.map((el) => {
      const css = getComputedStyle(el);
      return { id: el.getAttribute('data-workspace-panel-id'), column: css.gridColumn, row: css.gridRow, width: el.getBoundingClientRect().width };
    })) });
  }
  expect(JSON.stringify(layouts, null, 2)).toMatchSnapshot('effective-panel-sizes.json');
});

// These component baselines are recorded before the focus CSS consolidation.
for (const state of ['loading', 'empty', 'error', 'stale', 'closed'] as const) {
  for (const width of [1440, 390]) {
    test(`focus status ${state} ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await installDashboard(page);
      if (state === 'loading') {
        await page.route('**/wm-api/bootstrap', () => {});
        // Bootstrap no longer blocks independent sources indefinitely. Freeze
        // the initial loading phase, then exercise its release in startup tests.
        await page.clock.install({ time: new Date('2026-08-26T03:00:00Z') });
        await page.clock.pauseAt(new Date('2026-08-26T03:00:00Z'));
      }
      if (state === 'empty' || state === 'error') await page.route('**/wm-api/**', async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (!/\/(bootstrap|markets|market-groups)$/.test(path)) return route.fallback();
        await route.fulfill({ status: state === 'error' ? 503 : 200, json: state === 'error'
          ? { error: 'Fixture source unavailable' }
          : { generatedAt: '2026-08-26T03:00:00Z', items: [], featuredMarket: null, activeMarketsPreview: [], activeMarketGroupsPreview: [] } });
      });
      if (state === 'stale' || state === 'closed') await page.route('**/wm-api/**', async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (!/\/markets\/1\/(focus-tile|workspace)$/.test(path) && !path.includes('/runtime/lob/token/')) return route.fallback();
        const bundle = fixtureBundle(1);
        bundle.lob.yes.bookStatus = bundle.lob.no.bookStatus = 'stale';
        bundle.lob.yes.continuity = bundle.lob.no.continuity = false;
        if (state === 'closed') bundle.market = { ...bundle.market, status: 'closed' };
        await route.fulfill({ json: path.includes('/runtime/lob/token/') ? bundle.lob : bundle });
      });
      await gotoMapScene(page, '/?view=2d&mapPerf=1&renderer=svg&time=all&layers=earthquakes-volcanoes&center=-98,39&zoom=2.2');
      if (state === 'loading') {
        for (let frame = 0; frame < 10; frame++) {
          await page.clock.runFor(50);
          if (await page.locator('[data-map-renderer-ready]').count()) break;
        }
        await expect(page.locator('[data-map-renderer-ready]')).toBeAttached();
        await page.clock.runFor(200);
      }
      await expect(page.locator('.wm-focused-market-row')).toBeVisible({ timeout: 60_000 });
      if (state === 'stale' || state === 'closed') await expect(page.locator('.wm-focus-book-panel .wm-panel-badge')).toHaveText(state === 'stale' ? 'Stale' : 'Closed');
      if (state === 'error') await expect(page.locator('.wm-banner.error')).toBeVisible();
      if (state === 'loading') await expect(page.locator('.wm-banner').first()).toContainText('Bootstrapping');
      await page.locator('.wm-focused-market-row').scrollIntoViewIfNeeded();
      if (state === 'loading') await page.clock.runFor(200);
      await visual(page, `focus-status-${state}-${width}.png`);
    });
  }
}

for (const width of [1440, 390]) {
  test(`market hover, keyboard, selected and disabled controls ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await installDashboard(page);
    await gotoMapScene(page, '/?view=2d&mapPerf=1&renderer=svg&time=all&layers=earthquakes-volcanoes');
    const market = page.locator('.wm-poly-market-card').filter({ hasText: 'Fixture market 2' });
    await expect(market).toBeVisible({ timeout: 60_000 });
    await market.scrollIntoViewIfNeeded();
    await market.hover(); await market.focus();
    await page.keyboard.press('Shift+Tab');
    await page.keyboard.press('Tab');
    await expect(market).toBeFocused();
    await expect(page.locator('.wm-focused-market-list')).toHaveScreenshot(`catalog-hover-focus-${width}.png`, { animations: 'disabled', maxDiffPixels: 0, threshold: 0 });
    await page.keyboard.press('Enter');
    await expect(market).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.wm-focus-detail-panel')).toContainText('Fixture market 2');
    await page.locator('.wm-focused-market-row').scrollIntoViewIfNeeded();
    await visual(page, `market-selected-${width}.png`);
    let release!: () => Promise<void>;
    await page.route('**/wm-api/market-groups?**', route => { release = () => route.fulfill({ json: { items: [] } }); });
    const refresh = page.locator('.wm-market-refresh');
    await refresh.click();
    await expect(refresh).toBeDisabled();
    await settled(page);
    await expect(page.locator('.wm-focused-market-list')).toHaveScreenshot(`catalog-refresh-disabled-${width}.png`, { animations: 'disabled', maxDiffPixels: 0, threshold: 0 });
    await release();
    await expect(refresh).toBeEnabled();
  });
}

test('panel drag, constrained resize, enable and remote layout restore', async ({ page }) => {
  await installDashboard(page);
  let saved: any = { exists: true, revision: 1, activePanelIds: ['active-markets','price-chart','lob-depth','global-orderfilled','oracle-feed','global-transport-shipping','breaking-event-radar'], panelLayout: {}, preferences: {}, updatedAt: '2026-08-26T03:00:00Z' };
  await page.route('**/wm-api/product/workspace-layout', async route => {
    if (route.request().method() === 'PUT') saved = { ...saved, ...route.request().postDataJSON(), revision: saved.revision + 1 };
    await route.fulfill({ json: saved });
  });
  await gotoMapScene(page, '/?view=2d&layers=earthquakes-volcanoes');
  const source = page.locator('[data-workspace-panel-id="breaking-event-radar"]');
  const target = page.locator('[data-workspace-panel-id="global-transport-shipping"]');
  await source.scrollIntoViewIfNeeded();
  await expect(source.locator('.wm-panel-header')).toBeVisible();
  const start = await source.locator('.wm-panel-title').boundingBox();
  const end = await target.boundingBox();
  await page.mouse.move(start!.x + 8, start!.y + 8); await page.mouse.down();
  await page.mouse.move(end!.x + 30, end!.y + 30, { steps: 12 }); await page.mouse.up();
  await expect.poll(() => page.locator('.wm-panels-grid > .wm-panel-slot').evaluateAll(els => els.map(el => el.getAttribute('data-workspace-panel-id')))).toEqual(['breaking-event-radar', 'global-transport-shipping']);
  await expect(page.locator('.wm-panel-drag-ghost')).toHaveCount(0);
  await expect.poll(() => source.evaluate(el => getComputedStyle(el).transform)).toBe('none');
  const before = await source.boundingBox();
  const handle = source.locator('.wm-panel-col-resize-handle');
  await handle.hover(); const box = await handle.boundingBox();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2); await page.mouse.down();
  await page.mouse.move(box!.x + box!.width / 2 + 270, box!.y + box!.height / 2); await page.mouse.up();
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('polydata:workspace-panel-layout:v4') || '{}')['breaking-event-radar']?.colSpan)).toBe(3);
  expect((await source.boundingBox())!.width).toBe(before!.width);
  await handle.dblclick();
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('polydata:workspace-panel-layout:v4') || '{}')['breaking-event-radar'])).toBeUndefined();
  await page.keyboard.press('Control+k');
  await page.locator('.wm-command-tabs button').filter({ hasText: /^Panels/ }).click();
  await page.locator('.wm-command-input').fill('weather-market-browser');
  await page.locator('.wm-command-panel-result').filter({ hasText: 'weather-market-browser' }).click();
  await expect(page.locator('[data-workspace-panel-id="weather-market-browser"]')).toBeAttached();
  await expect.poll(() => saved.activePanelIds.includes('weather-market-browser')).toBe(true);
  await page.reload();
  await expect(page.locator('[data-workspace-panel-id="weather-market-browser"]')).toBeAttached({ timeout: 60_000 });
  await expect.poll(() => page.locator('.wm-panels-grid > .wm-panel-slot').evaluateAll(els => els.map(el => el.getAttribute('data-workspace-panel-id')))).toEqual(['breaking-event-radar', 'global-transport-shipping', 'weather-market-browser']);
});

for (const width of [1440, 390]) for (const kind of ['detail', 'book']) {
  test(`${kind === 'detail' ? 'focus' : 'book'} drag preview preserves detached panel styles ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await installDashboard(page);
    await gotoMapScene(page, '/?view=2d&layers=earthquakes-volcanoes');
    const panel = page.locator(`.wm-focus-${kind}-panel`);
    await expect(panel).toContainText('Fixture market 1');
    if (kind === 'book') await expect(panel.locator('.wm-focus-book-row')).toHaveCount(2);
    await panel.scrollIntoViewIfNeeded();
    await settled(page);
    const header = await panel.locator('.wm-panel-title').boundingBox();
    await page.mouse.move(header!.x + 8, header!.y + 8);
    await page.mouse.down();
    await page.mouse.move(header!.x + 36, header!.y + 36, { steps: 5 });
    const ghost = page.locator('body > .wm-panel-drag-ghost');
    await expect(ghost).toBeVisible();
    await expect(ghost).toHaveScreenshot(`${kind === 'detail' ? 'focus' : 'book'}-drag-preview-${width}.png`, { animations: 'disabled', maxDiffPixels: 0, threshold: 0 });
    await page.mouse.up();
    await expect(ghost).toHaveCount(0);
  });
}

test('anonymous homepage renders a saved empty panel list without restoring defaults', async ({ page }) => {
  await installDashboard(page, 'en', []);
  await page.route('**/wm-api/auth/session', route => route.fulfill({ json: { enabled: true, authenticated: false, user: null } }));
  for (let visit = 0; visit < 2; visit += 1) {
    await gotoMapScene(page, '/?view=2d&mapPerf=1&renderer=svg&time=all&layers=earthquakes-volcanoes,wildfires&center=-98,39&zoom=2.2');
    await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', /webgl|svg/, { timeout: 60_000 });
    await expect(page.locator('.wm-focused-market-list .wm-poly-market-card')).toHaveCount(2);
    await expect(page.locator('.wm-panels-grid [data-workspace-panel-id]')).toHaveCount(0);
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('polydata:workspace-panels:v4')!))).toEqual([]);
    // Fixed focus panels retain their existing product behavior.
    await expect(page.locator('.wm-focus-book-panel')).toBeVisible();
    await page.locator('.wm-more-nav summary').click();
      await page.getByRole('menuitem', { name: /settings|设置/i }).click();
    await expect(page.locator('.wm-settings-modal a[href="/login?next=/"]')).toBeVisible();
  }
});
