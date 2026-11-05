import { expect, test } from '@playwright/test';
import { fixtureBundle, fixtureMarkets, installDashboard } from './fixtures/dashboard';
import { GENERATED_AT } from './fixtures/world-event-map';

test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });

test('summary shares the selected snapshot with detail when Gamma price and volume are absent', async ({ page }) => {
  await installDashboard(page, 'en', ['active-markets', 'price-chart', 'lob-depth', 'market-summary']);
  await page.clock.install({ time: new Date(GENERATED_AT) });
  let bookReads = 0;
  let failBooks = false;
  let midpoint = .003;
  const blankMarket = (id: number) => ({ ...fixtureMarkets[id - 1], latestPrice: null, latestYesPrice: null,
    latestNoPrice: null, volume24h: null, tradeCount24h: null });
  await page.route('**/wm-api/markets*', route => {
    if (new URL(route.request().url()).pathname !== '/wm-api/markets') return route.fallback();
    return route.fulfill({ json: { items: [blankMarket(1), blankMarket(2)] } });
  });
  await page.route('**/wm-api/markets/*/focus-tile', route => {
    const id = Number(new URL(route.request().url()).pathname.split('/')[3]);
    return route.fulfill({ json: { ...fixtureBundle(id), market: blankMarket(id), lob: null,
      price: { marketId: id, latestPrice: null, latestYesPrice: null, latestNoPrice: null, volume24h: null, tradeCount24h: null } } });
  });
  await page.route('**/wm-api/runtime/lob/token/**', route => {
    bookReads++;
    if (failBooks) return route.fulfill({ status: 503, json: { error: 'fixture source unavailable' } });
    const id = Number(new URL(route.request().url()).searchParams.get('marketId'));
    const side = (tokenId: string, mid: number) => ({ tokenId, bookStatus: 'available', upstreamReady: true,
      observedAt: GENERATED_AT, eventAt: GENERATED_AT, bestBid: mid - .001, bestAsk: mid + .001,
      bids: [{ price: mid - .001, size: 10 }], asks: [{ price: mid + .001, size: 10 }] });
    return route.fulfill({ json: { marketId: id, bookStatus: 'available',
      yes: side(`yes-${id}`, midpoint), no: side(`no-${id}`, 1 - midpoint) } });
  });
  await page.goto('/');
  const summary = page.locator('[data-workspace-panel-id="market-summary"]');
  const detail = page.locator('[data-workspace-panel-id="price-chart"]');
  await summary.scrollIntoViewIfNeeded();
  await expect(summary.locator('.yes strong')).toHaveText('0.3%');
  await expect(summary.locator('.no strong')).toHaveText('99.7%');
  await expect(summary).toContainText('Book snapshot midpoint');
  await expect(summary).toContainText('Volume unavailable');
  await expect(summary).toContainText('Full-day count unavailable');
  await expect(detail).toContainText('0.3c');
  const before = bookReads;
  midpoint = .005;
  await page.clock.runFor(2500);
  await expect(summary.locator('.yes strong')).toHaveText('0.5%');
  await expect(detail).toContainText('0.5c');
  expect(bookReads - before).toBe(1);
  await page.getByText('Fixture market 2', { exact: true }).first().click();
  await expect(summary.locator('.wm-market-summary-hero strong')).toHaveText('Fixture market 2');
  await expect(summary.locator('.yes strong')).toHaveText('0.5%');
  failBooks = true;
  await page.clock.runFor(2500);
  await expect(summary).toContainText('Current quote unavailable');
  await expect(summary.locator('.yes strong')).toHaveCount(0);
  failBooks = false;
  await page.clock.runFor(6000);
  await expect(summary.locator('.yes strong')).toHaveText('0.5%');
});
