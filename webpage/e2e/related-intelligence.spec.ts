import { expect, test } from '@playwright/test';
import { installDashboard, fixtureMarkets } from './fixtures/dashboard';
test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });

// Isolated fixtures: production acceptance uses the real URL and real feeds.
const item = (id: string) => ({ id, contentType: 'news', content_version: id, source: 'Global Voices', sourceId: 'global-voices', sourceKind: 'news_report', author: 'Fixture author', title: `Fixture ${id} could <script>appear</script>`, summary: 'Fixture feed excerpt', excerptFull: 'Fixture full feed excerpt, never published.', excerptOrigin: 'feed', url: 'https://globalvoices.org/fixture/', licenseUrl: 'https://creativecommons.org/licenses/by/3.0/', relation: 'context', relationReason: 'Fixture shared event; contract conditions unverified.', publishedAt: null });
const payload = (id: number | null, ids: string[] = []) => ({ scope: id == null ? 'global' : 'market', marketId: id, market_id: id, items: ids.map(item), count: ids.length, status: 'partial', window: { days: 7 }, sources: [{ source_id: 'fixture-unavailable', status: 'error', error: 'Fixture timeout' }] });
async function mount(page: import('@playwright/test').Page, id = 1) {
  await page.goto('/e2e/panels.html');
  await page.waitForFunction(() => window.panelHarness);
  await page.evaluate(data => window.panelHarness.mount('related-news', {}, data), { selectedMarketId: id, selectedMarket: fixtureMarkets[id - 1] });
}

test('market empty stays empty; global is explicit; text, author, license and failure status are visible', async ({ page }) => {
  await installDashboard(page);
  const requests: string[] = [];
  await page.route('**/wm-api/content/**', route => {
    requests.push(route.request().url());
    return route.fulfill({ json: route.request().url().includes('/latest') ? payload(null, ['global']) : payload(1) });
  });
  await mount(page);
  await expect(page.getByText('No content meeting this market’s conditions', { exact: false })).toBeVisible();
  expect(requests.every(url => url.includes('/market/1'))).toBeTruthy();
  await page.getByRole('button', { name: 'Global', exact: true }).click();
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  await expect(page.getByText('By Fixture author')).toBeVisible();
  await expect(page.locator('.wm-free-intel-card script')).toHaveCount(0);
  await expect(page.getByText('CAUTION')).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'CC BY 3.0' })).toHaveAttribute('href', 'https://creativecommons.org/licenses/by/3.0/');
  await expect(page.getByRole('link', { name: 'Read source' })).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(page.getByText('Publication time unknown')).toBeVisible();
  await page.getByRole('button', { name: 'Show full card text' }).click();
  await expect(page.getByText('Fixture full feed excerpt, never published.', { exact: false })).toBeVisible();
  await page.locator('.wm-intel-sources summary').click();
  await expect(page.getByText('Fixture timeout', { exact: false })).toBeVisible();
  await page.getByLabel('Content time range').selectOption('30');
  await expect.poll(() => requests.at(-1)).toContain('days=30');
});

test('slow A response cannot populate B, and a mismatched market response is rejected', async ({ page }) => {
  await installDashboard(page);
  let releaseA!: () => void;
  const held = new Promise<void>(resolve => { releaseA = resolve; });
  let startedA = false;
  await page.route('**/wm-api/content/**', async route => {
    if (route.request().url().includes('/market/1')) { startedA = true; await held; }
    await route.fulfill({ json: payload(1, ['A']) }).catch(() => {});
  });
  await mount(page);
  await expect.poll(() => startedA).toBeTruthy();
  await page.evaluate(data => window.panelHarness.update('related-news', {}, data), { selectedMarketId: 2, selectedMarket: fixtureMarkets[1] });
  await expect(page.getByText('Content service unavailable.', { exact: false })).toBeVisible();
  releaseA();
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(0);
  await expect(page.getByText('Fixture market 2')).toBeVisible();
});

test('new content waits for the reader to accept it', async ({ page }) => {
  await installDashboard(page);
  await page.clock.install();
  let ids = ['first'];
  await page.route('**/wm-api/content/**', route => route.fulfill({ json: payload(1, ids) }));
  await mount(page);
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  ids = ['new', 'first'];
  await page.clock.runFor(30_100);
  await expect(page.getByRole('button', { name: 'New content available', exact: false })).toBeVisible();
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  await page.getByRole('button', { name: 'New content available', exact: false }).click();
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(2);
});

test('dossier uses the same content API and explicitly requests history with visible attribution', async ({ page }) => {
  await installDashboard(page);
  const requests: string[] = [];
  await page.route('**/wm-api/content/**', route => {
    requests.push(route.request().url());
    return route.fulfill({ json: route.request().url().includes('days=30') ? payload(1, ['history']) : payload(1) });
  });
  await page.goto('/markets/1');
  await expect(page.getByLabel('Dossier content time range')).toBeVisible();
  await page.getByLabel('Dossier content time range').selectOption('30');
  await expect(page.locator('.market-content-card').getByText('By Fixture author')).toBeVisible();
  await expect(page.locator('.market-content-card').getByRole('link', { name: 'CC BY 3.0' })).toBeVisible();
  expect(requests.some(url => url.includes('/market/1') && url.includes('days=30'))).toBeTruthy();
});
