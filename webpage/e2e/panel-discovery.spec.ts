import { expect, test, type Page } from '@playwright/test';
import { installDashboard, knownPanelIds } from './fixtures/dashboard';

test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });
const oldPanels = ['crypto-watch', 'commodities-watch', 'crypto-funding-watch'];
const newPanels = ['crypto-order-flow', 'crypto-oracle-reference', 'options-implied-probability', 'crypto-exchange-inflow',
  'price-implications', 'sample-chain-trades', 'oracle-timeline'];
const focusedStripIds = new Set(['active-markets', 'price-chart', 'lob-depth', 'global-orderfilled', 'oracle-feed']);
const inGrid = (ids: string[]) => ids.filter(id => !focusedStripIds.has(id));
const storageKey = 'polydata:workspace-panels:v4';
const catalogKey = 'polydata:workspace-known-default-panels:v1';
const gridIds = (page: Page) => page.locator('.wm-panels-grid > .wm-panel-slot')
  .evaluateAll(els => els.map(el => el.getAttribute('data-workspace-panel-id')));

// installDashboard seeds a chosen layout on each document; preserve actual app
// writes on reload and remove its catalog only for the initial legacy visit.
async function legacyWorkspace(page: Page) {
  await installDashboard(page, 'zh', oldPanels);
  await page.addInitScript(({ storageKey, catalogKey }) => {
    const saved = sessionStorage.getItem('discovery:reload');
    if (saved) {
      const value = JSON.parse(saved);
      localStorage.setItem(storageKey, value.panels);
      localStorage.setItem(catalogKey, value.catalog);
    } else localStorage.removeItem(catalogKey);
  }, { storageKey, catalogKey });
}
async function rememberForReload(page: Page) {
  await page.evaluate(({ storageKey, catalogKey }) => sessionStorage.setItem('discovery:reload', JSON.stringify({
    panels: localStorage.getItem(storageKey), catalog: localStorage.getItem(catalogKey),
  })), { storageKey, catalogKey });
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  await page.goto('about:blank');
});

for (const width of [1440, 390]) {
  test(`ordinary homepage automatically fills a legacy local layout at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await legacyWorkspace(page);
    await page.route('**/wm-api/auth/session', route => route.fulfill({ json: { authenticated: false } }));
    await page.goto('/');
    for (const id of newPanels) {
      const slot = page.locator(`[data-workspace-panel-id="${id}"]`);
      await expect(slot).toBeAttached();
      // Titles must exist before scrolling so browser Find and assistive
      // navigation can discover panels whose expensive bodies are deferred.
      await expect(slot).toHaveAttribute('data-content-ready', 'false');
      await expect(slot.locator('.wm-panel-title')).toHaveCount(1);
      await expect(slot.locator('.wm-panel-title')).not.toHaveText('');
    }
    const catalog: string[] = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), catalogKey);
    const expected = inGrid([...oldPanels, ...catalog.filter(id => !oldPanels.includes(id))]);
    await expect.poll(() => gridIds(page)).toEqual(expected);
    expect(expected).toEqual(expect.arrayContaining(newPanels));
    await expect(page.getByRole('link', { name: '加密策略', exact: true })).toHaveCount(0);
    expect(await page.locator('.wm-panels-grid').evaluate(el => getComputedStyle(el).gridTemplateColumns.split(' ').length)).toBe(width === 1440 ? 5 : 1);
    await rememberForReload(page);
    await page.reload();
    await expect.poll(() => gridIds(page)).toEqual(expected);
    const flow = page.locator('[data-workspace-panel-id="crypto-order-flow"]');
    await flow.locator('.wm-panel-title').scrollIntoViewIfNeeded();
    await expect(flow).toHaveAttribute('data-content-ready', 'true');
    await expect(flow.locator('.wm-panel-title')).toHaveCount(1);
    await expect(flow.locator('.wm-panel-slot-deferred')).toHaveCount(0);
    // Persist a subsequent explicit hide, then exercise normal hydration again.
    await page.evaluate(key => {
      const ids = JSON.parse(localStorage.getItem(key)!);
      localStorage.setItem(key, JSON.stringify(ids.filter((id: string) => id !== 'crypto-order-flow')));
    }, storageKey);
    await rememberForReload(page);
    await page.reload();
    await expect.poll(() => gridIds(page)).toEqual(expected.filter(id => id !== 'crypto-order-flow'));
  });
}

test('late legacy account layout is reconciled and saved once; another browser respects later hides', async ({ page, browser }) => {
  await installDashboard(page, 'zh', ['crypto-watch']);
  const layout = { 'commodities-watch': { rowSpan: 3, colSpan: 2 } };
  let server: any = { exists: true, revision: 7, activePanelIds: oldPanels, panelLayout: layout,
    preferences: {}, clientUpdatedAt: '2099-01-01T00:00:00Z', updatedAt: '2099-01-01T00:00:00Z' };
  let releaseAccount: (() => Promise<void>) | undefined;
  const writes: any[] = [];
  await page.route('**/wm-api/product/workspace-layout', async route => {
    if (route.request().method() === 'GET') { releaseAccount = () => route.fulfill({ json: server }); return; }
    const body = route.request().postDataJSON();
    writes.push(body);
    server = { ...server, ...body, revision: body.revision + 1 };
    await route.fulfill({ json: server });
  });
  await page.goto('/');
  await expect.poll(() => Boolean(releaseAccount)).toBe(true);
  await expect.poll(() => gridIds(page)).toEqual(['crypto-watch']);
  expect(writes).toHaveLength(0);
  await releaseAccount!();
  for (const id of newPanels) await expect(page.locator(`[data-workspace-panel-id="${id}"]`)).toBeAttached();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ revision: 7, panelLayout: layout });
  expect(writes[0].activePanelIds.slice(0, oldPanels.length)).toEqual(oldPanels);
  expect(writes[0].preferences.knownDefaultPanelIds).toEqual(expect.arrayContaining(newPanels));
  // A later account preference has hidden this already discovered panel.
  // Hook-level lifecycle tests exercise user edits and serialized PUTs.
  server = { ...server, revision: server.revision + 1,
    activePanelIds: server.activePanelIds.filter((id: string) => id !== 'crypto-order-flow') };
  const second = await browser.newPage();
  try {
    await installDashboard(second, 'zh', ['oracle-feed']);
    await second.route('**/wm-api/product/workspace-layout', route => {
      expect(route.request().method()).toBe('GET');
      return route.fulfill({ json: server });
    });
    await second.goto(`http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}/`);
    await expect.poll(() => gridIds(second)).toEqual(inGrid(server.activePanelIds));
    expect(await second.evaluate(() => JSON.parse(localStorage.getItem('polydata:workspace-panel-layout:v4')!))).toEqual(layout);
  } finally { await second.close(); }
});

test('a future default panel is added to a customized layout without reviving known hidden panels', async ({ page }) => {
  await installDashboard(page, 'zh', ['commodities-watch']);
  await page.addInitScript(({ known, key }) => localStorage.setItem(key, JSON.stringify(known)),
    { known: (await knownPanelIds()).filter(id => id !== 'crypto-order-flow'), key: catalogKey });
  await page.route('**/wm-api/auth/session', route => route.fulfill({ json: { authenticated: false } }));
  await page.goto('/');
  await expect.poll(() => gridIds(page)).toEqual(['commodities-watch', 'crypto-order-flow']);
});

test('searchable offscreen titles do not start panel data requests before scrolling', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installDashboard(page, 'en', ['world-clock', 'crypto-order-flow']);
  await page.route('**/wm-api/auth/session', route => route.fulfill({ json: { authenticated: false } }));
  let requests = 0;
  await page.route('**/wm-api/runtime/crypto/order-flow', route => {
    requests++;
    return route.fulfill({ status: 503, json: { error: 'test source unavailable' } });
  });
  await page.goto('/');
  const slot = page.locator('[data-workspace-panel-id="crypto-order-flow"]');
  await expect(slot).toHaveAttribute('data-content-ready', 'false');
  await expect(slot.getByRole('heading', { name: /^Crypto order flow$/i })).toBeAttached();
  expect(requests).toBe(0);
  await slot.locator('.wm-panel-title').scrollIntoViewIfNeeded();
  await expect(slot).toHaveAttribute('data-content-ready', 'true');
  await expect.poll(() => requests).toBeGreaterThan(0);
  await expect(slot.locator('.wm-panel-title')).toHaveCount(1);
});
