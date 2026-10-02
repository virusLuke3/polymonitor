import { test, expect } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';
import { GENERATED_AT } from './fixtures/world-event-map';
test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });

for (const [id, routePath, kind] of [['whale-tracker', 'whales', 'whale-trades'], ['suspicious-flow', 'suspicious', 'flow-watch']] as const) {
  test(`${id} automatically updates, survives failures, resumes visibility and shows exact fill semantics`, async ({ page }) => {
    await installDashboard(page);
    await page.clock.install({ time: new Date(GENERATED_AT) });
    let version = 1, fail = false, stale = false, requests = 0;
    await page.route(`**/wm-api/runtime/trades/${routePath}?*`, route => {
      requests++;
      if (fail) return route.fulfill({ status: 503, json: { error: 'Fixture outage' } });
      return route.fulfill({ json: { schemaVersion: 'trade-watch-v1', kind, generatedAt: GENERATED_AT,
        status: stale ? 'stale' : 'ok', error: stale ? 'Producer timeout; previous snapshot' : null,
        sourceMode: 'large-trades', items: [{ id: `trade-${version}`, marketId: 7, tokenId: 'token-a', txHash: 'a'.repeat(64),
          timestamp: GENERATED_AT, marketTitle: `Canonical fill ${version}`, side: 'SELL', price: '.64', notional: '177200',
          maker: `0x${'b'.repeat(40)}`, taker: `0x${'c'.repeat(40)}`, outcome: 'YES', outcomeSemanticsValid: false,
          observationType: 'large-trade', severity: 'critical' }] } });
    });
    await page.goto('/e2e/panels.html');
    await page.waitForFunction(() => window.panelHarness);
    await page.evaluate(id => window.panelHarness.mount(id, {}, { setSelectedMarketId: value => { document.body.dataset.selectedMarket = String(value); } }), id);
    const panel = page.locator('.wm-trade-watch-panel');
    await expect(panel.getByRole('button', { name: 'Canonical fill 1' })).toBeVisible();
    await expect(panel).toContainText('64.0¢'); await expect(panel).not.toContainText('64.0%');
    await expect(panel).toContainText('labels pending'); await expect(panel).not.toContainText('SELL YES');
    await expect(panel.getByRole('link', { name: '0xbbbbbb…bbbbbb' })).toHaveAttribute('href', `https://polygonscan.com/address/0x${'b'.repeat(40)}`);
    await panel.getByRole('button', { name: 'Canonical fill 1' }).click();
    await expect(page.locator('body')).toHaveAttribute('data-selected-market', '7');
    const filter = kind === 'whale-trades' ? 'BUY 0' : 'Oracle-linked 0';
    await panel.getByRole('button', { name: filter, exact: true }).click();
    await expect(panel.locator('.wm-trade-watch-card')).toHaveCount(0);
    await panel.getByRole('button', { name: 'All 1', exact: true }).click();
    version = 2;
    await page.clock.runFor(31_000);
    await expect(panel.getByRole('button', { name: 'Canonical fill 2' })).toBeVisible();
    expect(requests).toBeGreaterThanOrEqual(2);
    fail = true;
    await page.clock.runFor(31_000);
    await expect(panel.getByRole('button', { name: 'Canonical fill 2' })).toBeVisible();
    await expect(panel).toContainText('Trade refresh unavailable.');
    fail = false; version = 3;
    await page.clock.runFor(31_000);
    await expect(panel.getByRole('button', { name: 'Canonical fill 3' })).toBeVisible();
    await page.evaluate(() => { Object.defineProperty(document, 'hidden', { value: true, configurable: true }); document.dispatchEvent(new Event('visibilitychange')); });
    await expect(panel).toContainText('Auto refresh paused');
    const beforeHidden = requests;
    await page.clock.runFor(31_000); expect(requests).toBe(beforeHidden);
    version = 4;
    await page.evaluate(() => { Object.defineProperty(document, 'hidden', { value: false, configurable: true }); document.dispatchEvent(new Event('visibilitychange')); });
    await page.clock.runFor(1000);
    await expect(panel.getByRole('button', { name: 'Canonical fill 4' })).toBeVisible();
    stale = true;
    await panel.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(panel).toContainText('Previous snapshot');
    const storageKey = `polymonitor:panel-resource:${id}:global:trade-watch-v1:${id === 'whale-tracker' ? 14 : 12}`;
    const cached = await page.evaluate(key => JSON.parse(localStorage.getItem(key) || '{}'), storageKey);
    expect(cached.value.status).toBe('ok');
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await panel.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  });
}

for (const width of [1440, 390]) test(`cold dashboard ${width} mounts deferred trade panels and displays their first fill`, async ({ page }) => {
  await page.setViewportSize({ width, height: 844 });
  await installDashboard(page, 'en', ['whale-tracker', 'suspicious-flow']);
  for (const [path, kind] of [['whales', 'whale-trades'], ['suspicious', 'flow-watch']]) {
    await page.route(`**/wm-api/runtime/trades/${path}?*`, route => route.fulfill({ json: {
      schemaVersion: 'trade-watch-v1', kind, generatedAt: GENERATED_AT, status: 'ok',
      items: [{ marketId: 7, tokenId: 'token-a', txHash: 'a'.repeat(64), timestamp: GENERATED_AT,
        marketTitle: 'Visible first fill', side: 'BUY', price: '.64', notional: '25000' }],
    } }));
  }
  await page.goto('/?view=2d&renderer=svg');
  for (const id of ['whale-tracker', 'suspicious-flow']) {
    const slot = page.locator(`[data-workspace-panel-id="${id}"]`);
    await expect(slot).toBeVisible();
    await slot.scrollIntoViewIfNeeded();
    await expect(slot.getByRole('button', { name: 'Visible first fill' })).toBeVisible();
    expect(await slot.evaluate(el => {
      const body = el.querySelector('.wm-panel-body')!.getBoundingClientRect();
      const first = el.querySelector('.wm-trade-watch-card-head')!.getBoundingClientRect();
      return first.top >= body.top && first.bottom <= body.bottom;
    })).toBe(true);
    await slot.locator('summary').click();
    await expect(slot.locator('details')).toHaveAttribute('open', '');
    await slot.locator('summary').click();
    await expect(slot.locator('details')).not.toHaveAttribute('open', '');
  }
});
