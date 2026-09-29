import { expect, test } from '@playwright/test';
import { installLocalAssets } from './fixtures/browser';
const pairs = [['price-implications', 'overview'], ['sample-chain-trades', 'special'], ['oracle-timeline', 'trend']] as const;
const snapshot = (lens: string) => ({ lens, status: 'gateway-error', generationMode: 'rules', model: 'deterministic-fallback',
  brief: 'Rules-based observations from the market sample.', focus: [], specialMarkets: [], themes: [], watchlist: [], evidence: [],
  snapshotGeneratedAt: new Date().toISOString(), snapshotExpiresAt: new Date(Date.now() + 3600_000).toISOString(),
});
for (const width of [1440, 390]) {
  test(`analysis panels preserve empty results and honest status at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await installLocalAssets(page);
    await page.goto('/e2e/panels.html');
    await page.waitForFunction(() => window.panelHarness);
    for (const [id, lens] of pairs) {
      await page.evaluate(({ id, value }) => window.panelHarness.mount(id, { [id]: value }), { id, value: snapshot(lens) });
      await expect(page.locator('.wm-panel-badge')).toHaveText('RULES SUMMARY');
      await expect(page.locator('.wm-panel-count')).toHaveText('0');
      await expect(page.locator('.wm-ai-insight-card, .wm-ai-insight-market-card')).toHaveCount(0);
      await expect(page.locator('.wm-ai-insight-timestamp time')).toBeVisible();
      await expect(page.locator('.wm-ai-insights')).toContainText('AI generation is unavailable');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.evaluate(({ id, value }) => window.panelHarness.mount(id, { [id]: value }), { id, value: { ...snapshot(lens), status: 'live', generationMode: 'ai', model: 'test-model', snapshotExpiresAt: '2020-01-01T00:00:00Z' } });
      await expect(page.locator('.wm-panel-badge')).toHaveText('STALE');
      await expect(page.locator('.wm-ai-insights')).toContainText('snapshot has expired');
    }
  });
  test(`market rules stay bound to the selected market at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await installLocalAssets(page);
    await page.goto('/e2e/panels.html');
    await page.waitForFunction(() => window.panelHarness);
    await page.evaluate(() => window.panelHarness.mount('featured-market', {}, {
      selectedMarketId: 2, selectedMarket: { id: 2, title: 'Selected contract', slug: 'selected', description: 'Selected resolution rules', category: 'sports', tags: ['SPORTS', 'soccer', 'Soccer'] },
    }));
    await expect(page.locator('.wm-feature-hero')).toContainText('Selected contract');
    await expect(page.locator('.wm-feature-hero')).toContainText('Selected resolution rules');
    await expect(page.locator('.wm-feature-tags span')).toHaveCount(2);
    await page.evaluate(() => window.panelHarness.mount('featured-market', {}, {
      selectedMarketId: 3, selectedMarket: { id: 2, title: 'Old market', slug: 'old', description: 'Wrong rules' },
    }));
    await expect(page.locator('.wm-feature-hero')).not.toContainText('Wrong rules');
    await expect(page.locator('.wm-panel-badge')).toHaveText('MISSING');
  });
}
