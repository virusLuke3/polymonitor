import { expect, test } from '@playwright/test';
import { installDashboard, knownPanelIds } from './fixtures/dashboard';

test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });
const retired = ['polybeats-feed', 'polysignal-feed'];
const survivors = ['crypto-watch', 'whale-tracker'];
const retainedLayout = { 'crypto-watch': { colSpan: 2, rowSpan: 2 }, 'whale-tracker': { colSpan: 1, rowSpan: 3 } };

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  await page.goto('about:blank');
});

for (const account of [false, true]) for (const hidden of [false, true]) {
  test(`retired panels stay removed from ${account ? 'account' : 'local'} layouts, hidden=${hidden}`, async ({ page }) => {
    const oldIds = hidden ? survivors : ['crypto-watch', ...retired, 'whale-tracker'];
    const known = [...await knownPanelIds(), ...retired];
    const layout = { ...retainedLayout, 'polybeats-feed': { colSpan: 3, rowSpan: 2 }, 'polysignal-feed': { colSpan: 2, rowSpan: 1 } };
    await installDashboard(page, 'en', oldIds);
    await page.addInitScript(({ ids, known, layout }) => {
      localStorage.setItem('polydata:workspace-panels:v4', JSON.stringify(ids));
      localStorage.setItem('polydata:workspace-known-default-panels:v1', JSON.stringify(known));
      localStorage.setItem('polydata:workspace-panel-layout:v4', JSON.stringify(layout));
      localStorage.setItem('polydata:workspace-panel-layout-promotions:v1', 'live-evidence-wide');
    }, { ids: account ? ['whale-tracker'] : oldIds, known, layout });
    await page.route('**/wm-api/auth/session', r => r.fulfill({ json: {
      enabled: true, authenticated: account, user: account ? { id: 7 } : null, csrfToken: 'fixture-only',
    } }));
    let server: any = { exists: true, revision: 1, activePanelIds: oldIds, panelLayout: layout,
      preferences: { knownDefaultPanelIds: known }, clientUpdatedAt: '2099-01-01', updatedAt: '2099-01-01' };
    const writes: any[] = [];
    await page.route('**/wm-api/product/workspace-layout', r => {
      if (r.request().method() !== 'GET') {
        const body = r.request().postDataJSON();
        writes.push(body);
        server = { ...server, ...body, revision: body.revision + 1 };
      }
      return r.fulfill({ json: server });
    });
    const retiredRequests: string[] = [];
    page.on('request', r => {
      if (/\/wm-api\//.test(r.url()) && retired.some(id => r.url().includes(id))) retiredRequests.push(r.url());
    });
    await page.goto('/');
    await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('polydata:workspace-panels:v4') || '[]'))).toEqual(survivors);
    await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('polydata:workspace-panel-layout:v4') || '{}'))).toEqual(retainedLayout);
    for (const id of retired) await expect(page.locator(`[data-workspace-panel-id="${id}"]`)).toHaveCount(0);
    // Already-known panels hidden by the user must not be re-enabled by retirement.
    await expect(page.locator('[data-workspace-panel-id="commodities-watch"]')).toHaveCount(0);
    if (account) {
      await expect.poll(() => writes.length).toBeGreaterThan(0);
      expect(writes.at(-1).activePanelIds).toEqual(survivors);
      expect(writes.at(-1).panelLayout).toEqual(retainedLayout);
      for (const id of retired) expect(writes.at(-1).preferences.knownDefaultPanelIds).not.toContain(id);
    }
    expect(retiredRequests).toEqual([]);
  });
}
