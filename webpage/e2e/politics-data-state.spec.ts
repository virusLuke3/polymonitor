import { test, expect } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';
import { GENERATED_AT } from './fixtures/world-event-map';
test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });

const records: Record<string, { body: object; visible: string; empty: string }> = {
  nomination: { body: { items: [{ id: 'race', title: 'Fixture primary', electionDate: '2026-03-03',
    choices: [{ name: 'Fixture candidate', party: 'D', votes: 1234 }] }] }, visible: 'Fixture candidate', empty: 'Primary statistics unavailable.' },
  executive: { body: { items: [{ id: 'document', title: 'Fixture presidential document', publishedAt: '2026-08-25', url: 'https://example.org/document' }] },
    visible: 'Fixture presidential document', empty: 'Presidential documents unavailable.' },
  appointments: { body: { items: [{ id: 'nomination', title: 'Fixture appointment', text: 'Fixture submission', url: 'https://example.org/nomination', publishedAt: '2026-08-25' }], confirmations: [], hearings: [] },
    visible: 'Fixture appointment', empty: 'No acquired official nomination announcements.' },
  funding: { body: { items: [], law: { id: 'law', fiscalYear: 2027, expirationDate: '2026-12-11', coverage: [{ id: '1', text: 'Fixture law clause' }] } },
    visible: '2026-12-11', empty: 'Verified funding provisions unavailable.' },
};

for (const [domain, fixture] of Object.entries(records)) {
  test(`${domain}: failed request is not an empty result; recovery and later failures retain facts`, async ({ page }) => {
    const id = `politics-${domain}`;
    await installDashboard(page, 'en', [id]);
    let fail = true, empty = false;
    await page.route(`**/wm-api/runtime/politics/${domain}`, route => fail
      ? route.fulfill({ status: 503, json: { error: 'Fixture API failure' } })
      : route.fulfill({ json: { ...fixture.body, ...(empty ? { items: [] } : {}), panelId: id, schemaVersion: 1, generatedAt: GENERATED_AT,
        sources: [{ id: 'fixture', url: 'https://example.org/source', lastSuccessAt: GENERATED_AT, lastAttemptAt: GENERATED_AT, stale: false }] } }));
    await page.goto('/');
    const slot = page.locator(`[data-workspace-panel-id="${id}"]`);
    await slot.scrollIntoViewIfNeeded();
    await expect(slot).toContainText('Request failed; no snapshot is available');
    await expect(slot).not.toContainText(fixture.empty);
    fail = false;
    await slot.getByRole('button', { name: 'Retry', exact: true }).click();
    await expect(slot).toContainText(fixture.visible);
    fail = true;
    await slot.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(slot.locator('.wm-panel-runtime-notice')).toBeVisible();
    await expect(slot).toContainText(fixture.visible);
    await expect(slot).not.toContainText('Request failed; no snapshot is available');
    await expect(slot).not.toContainText(fixture.empty);
    // A successful empty result must replace old rows, unlike a failed request.
    if (domain === 'executive') {
      fail = false; empty = true;
      await slot.getByRole('button', { name: 'Retry', exact: true }).click();
      await expect(slot).toContainText(fixture.empty);
      await expect(slot).not.toContainText(fixture.visible);
    }
  });
}

for (const [domain, ageHours] of [['campaign-finance', 5], ['nomination', 23]] as const) {
  test(`${domain}: waiting for scheduled collection stays fresh and survives reload`, async ({ page }) => {
    const id = `politics-${domain}`, success = new Date(Date.parse(GENERATED_AT) - ageHours * 3600000).toISOString();
    await installDashboard(page, 'en', [id]);
    let fail = false;
    const body = domain === 'nomination' ? records.nomination.body : { items: [{ id: 'candidate', name: 'Fixture candidate', party: 'DEM', state: 'NC', url: 'https://example.org/candidate', receipts: 1234, spending: 100, cash: null, debt: null, transfersIn: null, transfersOut: null }] };
    await page.route(`**/wm-api/runtime/politics/${domain}`, route => fail
      ? route.fulfill({ status: 503, json: { error: 'Fixture API failure' } })
      : route.fulfill({ json: { ...body, panelId: id, schemaVersion: 1, generatedAt: GENERATED_AT,
        sources: [{ id: 'fixture', url: 'https://example.org/source', stale: false, lastSuccessAt: success, lastAttemptAt: GENERATED_AT }] } }));
    await page.goto('/');
    const slot = page.locator(`[data-workspace-panel-id="${id}"]`);
    await slot.scrollIntoViewIfNeeded();
    await expect(slot).toContainText('Fixture candidate');
    await expect(slot.locator('.wm-panel-runtime-notice')).toHaveCount(0);
    await expect.poll(() => page.evaluate(key => localStorage.getItem(key), `polymonitor:panel-resource:politics:${id}:v1`)).not.toBeNull();
    fail = true;
    await page.reload();
    await slot.scrollIntoViewIfNeeded();
    await expect(slot).toContainText('Fixture candidate');
    await expect(slot.locator('.wm-panel-runtime-notice')).toBeVisible();
    await expect(slot).not.toContainText('Request failed; no snapshot is available');
  });
}
