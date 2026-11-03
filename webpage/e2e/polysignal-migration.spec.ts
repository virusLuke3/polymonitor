import { expect, test } from '@playwright/test';
import { installDashboard, knownPanelIds } from './fixtures/dashboard';
test.use({baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}`});

for (const account of [false, true]) for (const hidden of [false, true]) {
  test(`PolySignal preserves ${account ? 'account' : 'local'} layout, hidden=${hidden}`, async ({page}) => {
    const oldIds = hidden ? ['crypto-watch', 'whale-tracker'] : ['crypto-watch', 'polybeats-feed', 'whale-tracker'];
    const known = (await knownPanelIds()).map(id => id === 'polysignal-feed' ? 'polybeats-feed' : id);
    await installDashboard(page, 'en', oldIds);
    await page.addInitScript(({ids, known}) => {
      localStorage.setItem('polydata:workspace-panels:v4', JSON.stringify(ids));
      localStorage.setItem('polydata:workspace-known-default-panels:v1', JSON.stringify(known));
      localStorage.setItem('polydata:workspace-panel-layout:v4', JSON.stringify({'polybeats-feed': {colSpan: 3, rowSpan: 2}}));
    }, {ids: account ? ['whale-tracker'] : oldIds, known});
    await page.route('**/wm-api/auth/session', r => r.fulfill({json: {authenticated: account, user: account ? {id: 7} : null, csrfToken: 'fixture-only'}}));
    const writes: any[] = [];
    await page.route('**/wm-api/product/workspace-layout', r => {
      const body = r.request().method() === 'GET' ? null : r.request().postDataJSON();
      if (body) writes.push(body);
      return r.fulfill({json: {exists: true, revision: body ? body.revision + 1 : 1,
        activePanelIds: oldIds, panelLayout: {'polybeats-feed': {colSpan: 3, rowSpan: 2}},
        preferences: {knownDefaultPanelIds: known}, clientUpdatedAt: '2099-01-01', updatedAt: '2099-01-01', ...body}});
    });
    const requests: string[] = [];
    page.on('request', r => { if (r.url().includes('/runtime/panels/')) requests.push(r.url()); });
    await page.goto('/');
    const expected = oldIds.map(id => id === 'polybeats-feed' ? 'polysignal-feed' : id);
    await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('polydata:workspace-panels:v4') || '[]'))).toEqual(expected);
    await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('polydata:workspace-panel-layout:v4') || '{}')['polysignal-feed'])).toEqual({colSpan: 3, rowSpan: 2});
    expect(await page.locator('[data-workspace-panel-id="polybeats-feed"]').count()).toBe(0);
    await expect(page.locator('[data-workspace-panel-id="polysignal-feed"]')).toHaveCount(hidden ? 0 : 1);
    if (!hidden) {
      await page.locator('[data-workspace-panel-id="polysignal-feed"]').scrollIntoViewIfNeeded();
      await expect.poll(() => requests.some(url => url.includes('/runtime/panels/polysignal-feed'))).toBe(true);
    }
    if (account) {
      await page.clock.runFor(1500);
      await expect.poll(() => writes.some(body => JSON.stringify(body.activePanelIds) === JSON.stringify(expected))).toBe(true);
      expect(writes.at(-1).panelLayout['polysignal-feed']).toEqual({colSpan: 3, rowSpan: 2});
    }
  });
}
