import { expect, test } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';
import { CRYPTO_STRATEGY_PANEL_IDS } from '../src/features/workspace/panelCollections';

test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });

const oldPanels = ['crypto-watch', 'commodities-watch', 'crypto-funding-watch'];
const expectedPanels = [...CRYPTO_STRATEGY_PANEL_IDS, 'commodities-watch'];
const gridIds = (page: import('@playwright/test').Page) => page.locator('.wm-panels-grid > .wm-panel-slot')
  .evaluateAll(els => els.map(el => el.getAttribute('data-workspace-panel-id')));

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  await page.goto('about:blank');
});

for (const width of [2518, 1440, 1280, 1200, 1024, 390]) {
  test(`saved workspace can discover the crypto panels at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await installDashboard(page, 'zh', oldPanels);
    await page.route('**/wm-api/auth/session', route => route.fulfill({ json: { authenticated: false } }));
    // Initialize once: a reload must exercise the actual saved preferences.
    await page.addInitScript(() => {
      const key = 'discovery-fixture:saved';
      const saved = sessionStorage.getItem(key);
      if (saved) localStorage.setItem('polydata:workspace-panels:v4', saved);
      else sessionStorage.setItem(key, localStorage.getItem('polydata:workspace-panels:v4')!);
    });
    await page.goto('/?view=2d&renderer=svg');
    await expect.poll(() => gridIds(page)).toEqual(oldPanels);
    const entry = page.getByRole('link', { name: '加密策略', exact: true });
    await expect(entry).toBeVisible();
    await entry.click();
    await expect.poll(() => gridIds(page)).toEqual(expectedPanels);
    await expect.poll(() => page.evaluate(() => new URL(location.href).searchParams.has('panels'))).toBe(false);
    const columns = width >= 1280 ? 5 : width > 1100 ? 4 : width > 760 ? 2 : 1;
    expect(await page.locator('.wm-panels-grid').evaluate(el => getComputedStyle(el).gridTemplateColumns.split(' ').length)).toBe(columns);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await expect(page.locator('[data-workspace-panel-id="crypto-watch"]')).toBeInViewport();
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('polydata:workspace-panels:v4')!))).toEqual(expectedPanels);
    await page.evaluate(() => sessionStorage.setItem('discovery-fixture:saved', localStorage.getItem('polydata:workspace-panels:v4')!));
    await page.reload();
    await expect.poll(() => gridIds(page)).toEqual(expectedPanels);
  });
}

test('crypto shortcut waits for the saved account layout and persists without resetting other preferences', async ({ page }) => {
  await installDashboard(page, 'zh', ['crypto-watch']);
  const layout = { 'commodities-watch': { rowSpan: 3, colSpan: 2 } };
  let releaseAccount: (() => Promise<void>) | undefined;
  const writes: any[] = [];
  await page.route('**/wm-api/product/workspace-layout', async route => {
    const server = { exists: true, revision: 7, activePanelIds: oldPanels, panelLayout: layout,
      preferences: {}, clientUpdatedAt: '2099-01-01T00:00:00Z', updatedAt: '2099-01-01T00:00:00Z' };
    if (route.request().method() === 'GET') {
      releaseAccount = () => route.fulfill({ json: server });
      return;
    }
    const body = route.request().postDataJSON();
    writes.push(body);
    await route.fulfill({ json: { ...server, ...body, revision: body.revision + 1 } });
  });
  await page.goto('/?panels=crypto&view=2d&renderer=svg#workspace-panels');
  await expect.poll(() => Boolean(releaseAccount)).toBe(true);
  await expect.poll(() => gridIds(page)).toEqual(['crypto-watch']);
  expect(writes).toHaveLength(0);
  await releaseAccount!();
  await expect.poll(() => gridIds(page)).toEqual(expectedPanels);
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ revision: 7, activePanelIds: expectedPanels, panelLayout: layout });
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('polydata:workspace-panel-layout:v4')!))).toEqual(layout);
});

test('new panels are searchable by their Chinese titles from an empty saved workspace', async ({ page }) => {
  await installDashboard(page, 'zh', []);
  await page.route('**/wm-api/auth/session', route => route.fulfill({ json: { authenticated: false } }));
  await page.goto('/?view=2d&renderer=svg');
  await expect.poll(() => gridIds(page)).toEqual([]);
  await page.keyboard.press('Control+k');
  await page.getByRole('button', { name: /^面板 / }).click();
  for (const title of ['交易所订单流', '合约指定价格源', '期权隐含概率', '交易所链上流入']) {
    await page.locator('.wm-command-input').fill(title);
    await expect(page.locator('.wm-command-panel-result')).toHaveCount(1);
    await expect(page.locator('.wm-command-panel-result')).toContainText(title);
  }
  await page.locator('.wm-command-input').fill('加密策略');
  await expect(page.locator('.wm-command-panel-result')).toHaveCount(8);
  await page.locator('.wm-command-input').fill('交易所订单流');
  await page.locator('.wm-command-panel-result').click();
  await expect.poll(() => gridIds(page)).toEqual(['crypto-order-flow']);
});
