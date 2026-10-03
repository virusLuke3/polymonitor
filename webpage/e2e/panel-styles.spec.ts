import { expect, test } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';
import { panelData, populatedPanelIds } from './fixtures/panel-data';

// Use registered production bodies and shared shell in a fixed grid cell.
// Actual dashboard spans are covered by frontend-architecture.spec.ts.
for (const width of [1440, 390]) {
  test(`registered panel styles ${width}`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width, height: 900 });
    await installDashboard(page);
    await page.goto('/e2e/panels.html');
    await page.waitForFunction(() => window.panelHarness);
    const focus = process.env.POLYMONITOR_STYLE_PANEL_IDS?.split(',');
    const ids = (await page.evaluate(() => window.panelHarness.ids)).filter(id => !focus || focus.includes(id));
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    for (const id of ids) {
      await page.evaluate(id => window.panelHarness.mount(id), id);
      const panel = page.locator('.wm-panel-slot');
      await expect(panel.locator('.wm-panel')).toBeVisible();
      if (id === 'commodities-watch') await expect(panel.locator('.wm-commodity-notice')).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      await expect.soft(panel).toHaveScreenshot(`${id}-${width}.png`, { animations: 'disabled', threshold: 0, maxDiffPixels: 0 });
    }
    for (const id of populatedPanelIds.filter(id => !focus || focus.includes(id))) {
      await page.evaluate(({ id, data }) => window.panelHarness.mount(id, data), { id, data: panelData });
      const panel = page.locator('.wm-panel-slot');
      await expect(panel.locator('.wm-panel')).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      await expect.soft(panel).toHaveScreenshot(`${id}-populated-${width}.png`, { animations: 'disabled', threshold: 0, maxDiffPixels: 0 });
    }
    expect(errors).toEqual([]);
  });
}

// The normal dashboard fixture has no raw fills or event outcome curves.
// Exercise the production bodies here before changing their cascade.
for (const width of [1440, 390]) for (const locale of ['en', 'zh']) {
  test(`populated focus styles ${width} ${locale}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await installDashboard(page, locale);
    await page.goto('/e2e/panels.html');
    await page.waitForFunction(() => window.panelHarness);
    const { fixtureBundle, fixtureMarkets } = await import('./fixtures/dashboard');
    const bundle = fixtureBundle(1);
    const outcomes = fixtureMarkets.map((m, i) => ({ ...m, marketId: m.id, outcomeKey: `outcome-${m.id}`, label: `Outcome ${m.id}`, yesPrice: m.latestPrice, change24h: i ? '-0.03' : '0.03' }));
    const group = { groupId: 'fixture-event', title: 'Fixture event', category: 'Politics', outcomes, topOutcomes: outcomes, outcomeCount: 2 };
    await page.evaluate(data => window.panelHarness.mountFocus(data), {
      markets: fixtureMarkets, selectedMarket: fixtureMarkets[0], selectedMarketId: 1,
      selectedMarketGroupDetail: group, selectedMarketGroupOutcomeKey: outcomes[0].outcomeKey,
      selectedMarketGroupChart: { range: '1d', historyStatus: 'ready', priceSource: 'clob-history', series: outcomes.map((o, i) => ({
        outcomeKey: o.outcomeKey, marketId: o.marketId, label: o.label, color: i ? '#f5b800' : '#7cb6ff',
        points: bundle.chart.points.map(p => ({ timestamp: p.timestamp, price: String(Number(p.yesPrice) - i * 0.2) })),
      })) },
      bundle: { ...bundle, chart: { ...bundle.chart, points: [] },
        trades: ['BUY', 'SELL'].map((side, i) => ({ marketId: 1, side, outcome: i ? 'NO' : 'YES', price: '0.62', size: '120', timestamp: bundle.generatedAt, txHash: `0x${String(i + 1).repeat(64)}`, logIndex: i })),
        oracle: { ...bundle.oracle, timeline: [{ marketId: 1, eventStatus: 'proposed', eventTime: bundle.generatedAt, proposedPrice: '1', questionId: 'fixture-question', txHash: `0x${'3'.repeat(64)}` }] },
      },
    });
    await page.evaluate(() => document.fonts.ready);
    await expect(page.locator('.wm-focus-event-legend-item')).toHaveCount(2);
    await expect(page.locator('.wm-focus-outcome-card')).toHaveCount(2);
    await expect(page.locator('.wm-focused-market-right')).toHaveCSS('display', 'contents');
    // display:contents supplies no size-query box; the 180px global header note
    // is the actual baseline at both viewport widths.
    await expect(page.locator('.wm-focus-header-note')).toHaveCSS('max-width', '180px');
    await page.getByRole('button', { name: '7d', exact: true }).click();
    await expect(page.getByRole('button', { name: '7d', exact: true })).toHaveClass('active');
    const snapshot = async (selector: string, name: string) => {
      const el = page.locator(selector); await el.scrollIntoViewIfNeeded();
      await expect(el).toHaveScreenshot(`focus-${name}-${width}-${locale}.png`, { animations: 'disabled', threshold: 0, maxDiffPixels: 0 });
    };
    await snapshot('.wm-focus-detail-panel', 'event');
    await page.getByRole('button', { name: 'NO', exact: true }).click();
    await expect(page.getByRole('button', { name: 'NO', exact: true })).toHaveClass('active');
    await page.locator('.wm-focus-book-row.ask').first().hover();
    await expect(page.locator('.wm-focus-book-row.ask').first()).toHaveCSS('box-shadow', 'none');
    await snapshot('.wm-focus-book-panel', 'no-book-hover');
    await page.locator('.wm-orderfilled-row').first().hover();
    await snapshot('.wm-focus-trades-panel', 'fills-hover');
    await snapshot('.wm-focused-oracle-feed', 'oracle-proposed');
  });
}

test('live quote direction and book animation keep their established colors and hover behavior', async ({ page }) => {
  await installDashboard(page);
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.clock.install({ time: new Date('2026-08-26T03:00:00Z') });
  const { fixtureBundle, fixtureMarkets } = await import('./fixtures/dashboard');
  let raised = false;
  let requests = 0;
  await page.route('**/wm-api/runtime/lob/token/**', route => {
    const lob = fixtureBundle(1).lob;
    if (raised) {
      lob.yes.bestBid = '0.65'; lob.yes.bestAsk = '0.67';
      lob.yes.bids[0].price = '0.65'; lob.yes.asks[0].price = '0.67';
    }
    requests += 1;
    return route.fulfill({ json: lob });
  });
  await page.goto('/e2e/panels.html');
  await page.waitForFunction(() => window.panelHarness);
  await page.evaluate(data => window.panelHarness.mountFocus(data), {
    markets: fixtureMarkets, selectedMarketId: 1, selectedMarket: fixtureMarkets[0], bundle: fixtureBundle(1),
  });
  await expect.poll(() => requests).toBeGreaterThan(0);
  await expect(page.locator('.wm-focus-book')).toHaveClass(/tick-flat/);
  raised = true;
  await page.clock.runFor(2100);
  await expect(page.locator('.wm-focus-book')).toHaveClass(/tick-up/);
  await expect(page.locator('.wm-focus-price-hero strong')).toHaveCSS('color', 'rgb(243, 244, 246)');
  await expect(page.locator('.wm-focus-book-quote-strip strong.bid')).toHaveCSS('color', 'rgb(34, 197, 94)');
  await expect(page.locator('.wm-focus-book-quote-strip strong.ask')).toHaveCSS('color', 'rgb(244, 63, 94)');
  await expect(page.locator('.wm-focus-book-quote-strip strong').nth(1)).toHaveCSS('color', 'rgb(125, 255, 173)');
  const row = page.locator('.wm-focus-book-row.bid');
  await expect(row).toHaveClass(/live-updated/);
  await expect(row).toHaveCSS('animation-name', 'wm-book-row-live-flash');
  await row.hover();
  await expect(row).toHaveCSS('box-shadow', 'none');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  expect(await row.evaluate(el => parseFloat(getComputedStyle(el).animationDuration))).toBeLessThan(0.001);
});
