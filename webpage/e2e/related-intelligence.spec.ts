import { expect, test } from '@playwright/test';
import { installDashboard, fixtureMarkets } from './fixtures/dashboard';
test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });

// Isolated fixtures: production acceptance uses the real URL and real feeds.
const item = (id: string) => ({ id, contentType: 'news', content_version: id, source: 'Global Voices', sourceId: 'global-voices', sourceKind: 'news_report', author: 'Fixture author', title: `Fixture ${id} could <script>appear</script>`, summary: 'Fixture feed excerpt', excerptFull: 'Fixture full feed excerpt, never published.', excerptOrigin: 'feed', url: 'https://globalvoices.org/fixture/', licenseUrl: 'https://creativecommons.org/licenses/by/3.0/', relation: 'context', relationReason: 'Fixture shared event; contract conditions unverified.', publishedAt: null });
const payload = (id: number | null, ids: string[] = []) => ({ scope: id == null ? 'global' : 'market', marketId: id, market_id: id, items: ids.map(item), count: ids.length, status: 'partial', window: { days: 7 }, sources: [{ source_id: 'fixture-unavailable', status: 'error', error: 'Fixture timeout' }] });
async function mount(page: import('@playwright/test').Page, id: number | null = 1) {
  await page.goto('/e2e/panels.html');
  await page.waitForFunction(() => window.panelHarness);
  await page.evaluate(data => window.panelHarness.mount('related-news', {}, data), { selectedMarketId: id, selectedMarket: id == null ? null : fixtureMarkets[id - 1] });
}

test('market empty stays empty; global is explicit; text, author, license and failure status are visible', async ({ page }) => {
  await installDashboard(page);
  const requests: string[] = [];
  await page.route('**/wm-api/content/**', route => {
    requests.push(route.request().url());
    const data = route.request().url().includes('/latest') ? payload(null, ['global']) : payload(1);
    data.window.days = Number(new URL(route.request().url()).searchParams.get('days') || 7);
    return route.fulfill({ json: data });
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

test('dossier distinguishes request failure and rejects a different market response', async ({ page }) => {
  await installDashboard(page);
  let wrongMarket = false;
  await page.route('**/wm-api/content/**', route => wrongMarket
    ? route.fulfill({ json: payload(2, ['wrong-market']) })
    : route.fulfill({ status: 503, json: { error: 'Fixture unavailable' } }));
  await page.goto('/markets/1');
  const card = page.locator('.market-content-card');
  await expect(card.getByText('Content service unavailable.', { exact: true })).toBeVisible();
  await expect(card.getByText('No linked reporting', { exact: true })).toHaveCount(0);
  wrongMarket = true;
  await page.getByLabel('Dossier content time range').selectOption('30');
  await expect(card.getByText('Content service unavailable.', { exact: true })).toBeVisible();
  await expect(card.getByText('Fixture wrong-market', { exact: false })).toHaveCount(0);
});

test('failed refresh preserves content and manual retry recovers', async ({ page }) => {
  await installDashboard(page);
  let fail = false;
  await page.route('**/wm-api/content/**', route => fail
    ? route.fulfill({ status: 503, json: { error: 'Fixture unavailable' } })
    : route.fulfill({ json: payload(1, ['first']) }));
  await mount(page);
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  fail = true;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByText('Content service unavailable.', { exact: false })).toBeVisible();
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  fail = false;
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.getByText('Content service unavailable.', { exact: false })).toHaveCount(0);
});

test('same-market window change rejects an old response and validates malformed cards', async ({ page }) => {
  await installDashboard(page);
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let started = false;
  let malformed = true;
  await page.route('**/wm-api/content/**', async route => {
    const days = Number(new URL(route.request().url()).searchParams.get('days') || 7);
    if (days === 7) { started = true; await held; }
    const data = { ...payload(1, [days === 7 ? 'old' : 'history']), window: { days } };
    await route.fulfill({ json: malformed && days === 30 ? { ...data, items: [{ title: {} }] } : data }).catch(() => {});
  });
  await mount(page);
  await expect.poll(() => started).toBeTruthy();
  await page.getByLabel('Content time range').selectOption('30');
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
  release();
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(0);
  malformed = false;
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  await expect(page.locator('.wm-free-intel-card')).toContainText('Fixture history');
});

test('expired card disappears while a new card still waits for acceptance', async ({ page }) => {
  await installDashboard(page);
  await page.clock.install();
  const expires = await page.evaluate(() => new Date(Date.now() + 31_000).toISOString());
  let ids = ['first'];
  await page.route('**/wm-api/content/**', route => route.fulfill({ json: {
    ...payload(1, ids), items: ids.map(id => ({ ...item(id), expires_at: id === 'first' ? expires : null })),
  } }));
  await mount(page);
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  ids = ['new', 'first'];
  await page.clock.runFor(30_100);
  await expect(page.getByRole('button', { name: 'New content available', exact: false })).toBeVisible();
  await page.clock.runFor(1_000);
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(0);
  await page.getByRole('button', { name: 'New content available', exact: false }).click();
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  await expect(page.locator('.wm-free-intel-card')).toContainText('Fixture new');
});

test('source disclosure remains clickable above workspace resize handles', async ({ page }) => {
  await installDashboard(page, 'en', ['related-news']);
  await page.route('**/wm-api/content/**', route => {
    const market = route.request().url().match(/\/market\/(\d+)/);
    return route.fulfill({ json: market ? payload(Number(market[1])) : payload(null, Array.from({ length: 20 }, (_, i) => `card-${i}`)) });
  });
  await page.goto('/');
  const panel = page.locator('[data-workspace-panel-id="related-news"]');
  await panel.scrollIntoViewIfNeeded();
  await panel.getByRole('button', { name: 'Global', exact: true }).click();
  await expect(panel.locator('.wm-free-intel-card')).toHaveCount(20);
  await panel.locator('.wm-intel-sources summary').click();
  await expect(panel.locator('.wm-intel-sources')).toHaveAttribute('open', '');
});

test('explicit global scope survives market updates and market scope uses the current identity', async ({ page }) => {
  await installDashboard(page);
  const requests: string[] = [];
  await page.route('**/wm-api/content/**', route => {
    requests.push(route.request().url());
    const market = route.request().url().match(/\/market\/(\d+)/);
    return route.fulfill({ json: market ? payload(Number(market[1])) : payload(null, ['global']) });
  });
  await mount(page);
  await page.getByRole('button', { name: 'Global', exact: true }).click();
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  await page.evaluate(data => window.panelHarness.update('related-news', {}, data), { selectedMarketId: 2, selectedMarket: fixtureMarkets[0] });
  await expect(page.getByRole('button', { name: 'Global', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  expect(requests.some(url => url.includes('/market/2'))).toBeFalsy();
  await page.getByRole('button', { name: 'Market', exact: true }).click();
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(0);
  await expect(page.getByText('Market 2', { exact: true })).toBeVisible();
  expect(requests.at(-1)).toContain('/market/2');
});

test('legacy empty outage retries automatically and check time advances even with an unchanged seed', async ({ page }) => {
  await installDashboard(page);
  await page.clock.install();
  const generatedAt = await page.evaluate(() => new Date().toISOString());
  let attempts = 0;
  await page.route('**/wm-api/content/**', route => route.fulfill({ json: ++attempts === 1
    ? { ...payload(1), status: 'unavailable' }
    : { ...payload(1, ['recovered']), generatedAt } }));
  await mount(page);
  await expect(page.getByText('Content service unavailable.', { exact: false })).toBeVisible();
  await page.clock.runFor(1_100);
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  const checked = await page.locator('[data-intel-checked-at]').getAttribute('datetime');
  await page.clock.runFor(30_100);
  await expect.poll(() => page.locator('[data-intel-checked-at]').getAttribute('datetime')).not.toBe(checked);
  await expect(page.locator('[data-intel-updated-at]')).toHaveAttribute('datetime', generatedAt);
  await expect(page.getByText('Content service unavailable.', { exact: false })).toHaveCount(0);
  expect(attempts).toBeGreaterThanOrEqual(3);
});

test('reopened panel shows a saved snapshot during an outage and stops showing it at its age limit', async ({ page }) => {
  await installDashboard(page);
  await page.clock.install();
  const generatedAt = await page.evaluate(() => new Date().toISOString());
  let fail = false;
  await page.route('**/wm-api/content/**', route => fail
    ? route.fulfill({ status: 503, json: { error: 'Fixture unavailable' } })
    : route.fulfill({ json: { ...payload(1, ['saved']), generatedAt } }));
  await mount(page);
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  fail = true;
  await mount(page);
  await expect(page.getByText('Showing a saved snapshot', { exact: false })).toBeVisible();
  await expect(page.getByText('Content service unavailable.', { exact: false })).toBeVisible();
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  await page.clock.fastForward(300_001);
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(0);
  await expect(page.getByText('Content service unavailable.', { exact: false })).toBeVisible();
  await expect(page.getByText('No content meeting this market', { exact: false })).toHaveCount(0);
});

test('page hiding pauses checks and returning resumes without losing readable content', async ({ page }) => {
  await installDashboard(page);
  await page.clock.install();
  let attempts = 0;
  await page.route('**/wm-api/content/**', route => {
    attempts++;
    return route.fulfill({ json: payload(1, ['visible']) });
  });
  await mount(page);
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  const before = attempts;
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(page.getByText('Auto refresh paused', { exact: false })).toBeVisible();
  await page.clock.runFor(31_100);
  expect(attempts).toBe(before);
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect.poll(() => attempts).toBeGreaterThan(before);
  await expect(page.getByText('Auto 30s', { exact: true })).toBeVisible();
});

test('scope controls stay usable during a slow cold market request', async ({ page }) => {
  await installDashboard(page);
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let started = false;
  await page.route('**/wm-api/content/**', async route => {
    if (route.request().url().includes('/market/1')) {
      started = true;
      await held;
      return route.fulfill({ json: payload(1, ['old-market']) }).catch(() => {});
    }
    return route.fulfill({ json: payload(null, ['fast-global']) });
  });
  await mount(page);
  await expect.poll(() => started).toBeTruthy();
  await expect(page.locator('.wm-panel-loading')).toBeVisible();
  await page.getByRole('button', { name: 'Global', exact: true }).click();
  await expect(page.locator('.wm-free-intel-card')).toContainText('Fixture fast-global');
  release();
  await expect(page.locator('.wm-free-intel-card')).toHaveCount(1);
  await expect(page.getByText('Fixture old-market', { exact: false })).toHaveCount(0);
});

test('compact desktop panel shows its first headline without scrolling through status messages', async ({ page }) => {
  await installDashboard(page);
  const generatedAt = await page.evaluate(() => new Date().toISOString());
  await page.route('**/wm-api/content/**', route => route.fulfill({ json: {
    ...payload(null, ['visible-headline']), generatedAt,
  } }));
  await mount(page, null);
  await page.locator('[data-workspace-panel-id="related-news"]').evaluate(element => {
    element.style.width = '355px'; element.style.height = '270px';
  });
  const headline = page.locator('.wm-free-intel-card .wm-news-title');
  await expect(headline).toBeVisible();
  const bounds = await headline.evaluate(element => {
    const body = element.closest('.wm-panel-body')!;
    const text = element.getBoundingClientRect();
    const viewport = body.getBoundingClientRect();
    const slot = element.closest('[data-workspace-panel-id]')!.getBoundingClientRect();
    return { top: text.top, bottom: Math.min(viewport.bottom, slot.bottom), scroll: body.scrollTop };
  });
  expect(bounds.scroll).toBe(0);
  expect(bounds.top).toBeLessThan(bounds.bottom - 10);
});
