import { test, expect } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';
import { GENERATED_AT } from './fixtures/world-event-map';
test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });

test('Alpha uses its resource to apply scheduled updates, retain failures and separate pending labels', async ({ page }) => {
  await installDashboard(page);
  await page.clock.install({ time: new Date(GENERATED_AT) });
  let version = 1, fail = false, requests = 0;
  await page.route('**/wm-api/runtime/signals/alpha?*', route => {
    requests++;
    if (fail) return route.fulfill({ status: 503, json: { error: 'Fixture outage' } });
    const item = { id: `alpha-${version}`, marketId: 1, tokenId: 'token-a', marketTitle: `Verified flow ${version}`, side: 'BUY', logicalOutcome: 'YES', sourceOutcomeLabel: 'Yes', price: '.62', outcomeSemanticsValid: true, outcomeSemanticsCapabilities: { supportsYesNoWording: true }, metrics: { totalNotional: 15000, netFlowNotional: 14000, netDirectionStrength: .875, marketShare: .3, uniqueTraderCount: 6, tradeCount: 12, score: 88 } };
    return route.fulfill({ json: { policyVersion: 'token-flow-v1', scope: 'global', status: 'partial', generatedAt: GENERATED_AT, windowMinutes: 15, baselineMinutes: 60, items: [item], candidates: [{ ...item, id: 'pending', marketTitle: 'Pending flow', qualification: 'labels-unavailable', marketIdentityVerified: true, outcomeSemanticsValid: false }], coverage: { candidateCount: 2, verifiedCount: 1, rejectedCount: 1, rejectionReasons: { projection_missing: 1 } } } });
  });
  await page.goto('/e2e/panels.html');
  await page.waitForFunction(() => window.panelHarness);
  await page.evaluate(() => window.panelHarness.mount('alpha-signal', {}, {}));
  await expect(page.locator('.wm-alpha-card')).toHaveCount(2);
  await expect(page.getByRole('button', { name: 'Verified flow 1' })).toBeVisible();
  await expect(page.locator('.wm-alpha-card.is-pending')).not.toContainText('88/100');
  await expect(page.locator('.wm-alpha-card.is-pending')).not.toContainText('Buy Yes');
  await expect(page.locator('.wm-alpha-card').first()).toContainText('Unique takers6');
  version = 2;
  await page.clock.runFor(31_000);
  await expect(page.getByRole('button', { name: 'Verified flow 2' })).toBeVisible();
  expect(requests).toBeGreaterThanOrEqual(2);
  fail = true;
  await page.clock.runFor(31_000);
  await expect(page.getByRole('button', { name: 'Verified flow 2' })).toBeVisible();
  await expect(page.getByText('Alpha data cannot currently be verified.', { exact: false })).toBeVisible();
  expect(await page.evaluate(() => Boolean(localStorage.getItem('polymonitor:panel-resource:alpha-signal:global:token-flow-v1:8')))).toBe(true);
});
