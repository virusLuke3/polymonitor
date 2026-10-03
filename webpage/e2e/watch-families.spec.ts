import { test, expect } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';
import { GENERATED_AT } from './fixtures/world-event-map';
test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });

test('finance and tech share batched validation, check every 5m and publish source partial changes', async ({ page }) => {
  const ids = ['global-index-monitor', 'big-tech-market-cap'];
  await installDashboard(page, 'en', ids);
  await page.clock.install({ time: new Date(GENERATED_AT) });
  let version = 1, batches = 0, fail = false;
  const payload = async (panelId: string) => ({ panelId, status: 'ok', generatedAt: await page.evaluate(() => new Date().toISOString()),
    sources: { yahoo: panelId === ids[1] && version > 1 ? 'partial' : 'ok' },
    items: [{ id: 'row', label: `VERSION ${version}`, metric: 100 + version, metricLabel: `$${100 + version}`, rank: 1 }], summary: {} });
  await page.route('**/wm-api/v1/runtime/panels?**', async route => {
    batches++;
    if (fail) return route.fulfill({ status: 503, json: { error: 'Batch unavailable' } });
    const requested = (new URL(route.request().url()).searchParams.get('ids') || '').split(',');
    const panels = Object.fromEntries(await Promise.all(requested.map(async id => [id, await payload(id)])));
    return route.fulfill({ json: { apiVersion: 'v1', data: { panels }, meta: { panels: {} }, errors: [] } });
  });
  await page.route('**/wm-api/runtime/finance/global-index-monitor?*', async route => route.fulfill({ json: await payload('global-index-monitor') }));
  await page.route('**/wm-api/runtime/tech/*', async route => route.fulfill({ json: await payload('big-tech-market-cap') }));
  await page.goto('/');
  const finance = page.locator('.wm-panel-slot[data-workspace-panel-id="global-index-monitor"]');
  const tech = page.locator('.wm-panel-slot[data-workspace-panel-id="big-tech-market-cap"]');
  await finance.scrollIntoViewIfNeeded();
  await expect(finance).toContainText('VERSION 1');
  await tech.scrollIntoViewIfNeeded();
  await expect(tech).toContainText('VERSION 1');
  version = 2;
  await page.clock.runFor(301_000);
  await expect(finance).toContainText('VERSION 2');
  await expect(tech).toContainText('VERSION 2');
  expect(batches).toBeGreaterThan(0);
  await expect(tech).toContainText('DEGRADED');
  fail = true; version = 3;
  await finance.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(finance).toContainText('VERSION 3'); // single fetch uses the same contract
  expect(await page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith('polymonitor:panel-resource:finance:') || key.startsWith('polymonitor:panel-resource:tech:')).length)).toBe(2);
});
