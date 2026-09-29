import { test, expect } from '@playwright/test';
import { GENERATED_AT, hazard, mapResponse, installFixtures } from './fixtures/world-event-map';
import { mkdirSync, writeFileSync } from 'node:fs';
import { MAP_OCCLUDERS } from '../src/features/world-event-map/renderer/mapOcclusion';

test.use({ trace: 'off' });

const url = '/?view=2d&basemap=openfreemap&mapPerf=1&center=0,20&zoom=1.5&time=all&layers=earthquakes-volcanoes,weather-alerts,wildfires,climate-anomalies';
test.afterEach(async ({ page }) => { await page.goto('about:blank'); await page.unrouteAll({ behavior: 'wait' }); });

test.beforeEach(async ({ page }) => {
  mkdirSync('artifacts/map-polish-round2', { recursive: true });
  await page.clock.setFixedTime(new Date(GENERATED_AT));
  await installFixtures(page);
});

test('new visitor controls stay compact without hiding event records', async ({ page }) => {
  await page.addInitScript(() => { if (location.protocol === 'http:') localStorage.removeItem('polydata:panel-library-open:v1'); });
  await page.goto(url);
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'webgl');
  await expect(page.locator('.wm-weather-deck-legend')).toBeHidden();
  await expect(page.getByRole('button', { name: 'Open layers panel' })).toBeVisible();
  const area = await page.locator('[data-map-renderer-ready]').evaluate((host, selectors) => {
    const rect = host.getBoundingClientRect();
    const controls = [...host.closest('.wm-map-stage')!.querySelectorAll(selectors)].map(el => el.getBoundingClientRect());
    const covered = controls.reduce((sum, box) => sum + Math.max(0, Math.min(rect.right, box.right) - Math.max(rect.left, box.left)) * Math.max(0, Math.min(rect.bottom, box.bottom) - Math.max(rect.top, box.top)), 0);
    return { mapArea: rect.width * rect.height, covered, ratio: covered / (rect.width * rect.height) };
  }, MAP_OCCLUDERS);
  expect(area.ratio).toBeLessThan(0.05);
  await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText('11');
  writeFileSync('artifacts/map-polish-round2/control-area.json', JSON.stringify(area, null, 2));
});

test('refresh keeps reading order and a filtered selection remains readable', async ({ page }) => {
  await page.clock.install({ time: new Date(GENERATED_AT) });
  const original = hazard({ id: 'polish:old', title: 'Old occurrence updated today', occurredAt: '2026-01-01T00:00:00Z' });
  const incoming = hazard({ id: 'polish:new', title: 'Incoming event without occurrence', occurredAt: null });
  let refreshed = false;
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**', route => {
    const source = new URL(route.request().url()).searchParams.get('source')!;
    return route.fulfill({ json: mapResponse(source, source === 'usgs' ? refreshed ? [incoming, original] : [original] : []) });
  });
  await page.route('**/wm-api/runtime/world/natural-hazards/events/**', route => route.fulfill({ json: { schemaVersion: 'natural-hazard-detail.v1', generatedAt: GENERATED_AT, event: original } }));
  await page.goto(url);
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'webgl');
  await page.locator('.wm-world-event-list-toggle').click();
  await expect(page.locator('.wm-world-event-list-scroll')).toContainText('Old occurrence updated today');
  refreshed = true; await page.clock.fastForward(600_100);
  await expect(page.getByRole('button', { name: '1 new · update list', exact: true })).toBeVisible();
  await expect(page.locator('.wm-world-event-list-scroll')).not.toContainText('Incoming event');
  await page.getByRole('button', { name: '1 new · update list', exact: true }).click();
  await expect(page.locator('.wm-world-event-list-scroll')).toContainText('Incoming event');
  await expect(page.locator('.wm-world-event-list-scroll')).toContainText('Occurrence unknown');
  await page.getByRole('button', { name: /Old occurrence updated today/ }).click();
  await expect(page.locator('.wm-event-inspector')).toContainText('Old occurrence updated today');
  await page.getByRole('button', { name: 'Warning', exact: true }).click();
  await expect(page.locator('.wm-map-selection-retained')).toContainText('outside the current filters');
  await expect(page.locator('.wm-event-inspector .wm-map-selection-retained')).toBeInViewport();
  await expect(page.locator('.wm-event-inspector')).toContainText('Old occurrence updated today');
});

test('legend, safe focus mode and proportional fonts keep one renderer', async ({ page }) => {
  await page.goto(url);
  const host = page.locator('[data-map-renderer-ready]');
  await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl');
  await page.evaluate(() => document.fonts.ready);
  await host.evaluate(el => (el as any).__identity = 'same-map');
  const legend = page.locator('.wm-weather-deck-legend');
  await expect(legend).toBeHidden();
  const toggle = page.locator('.wm-map-legend-toggle');
  await toggle.click(); await expect(legend).toBeVisible();
  const previous = new URL(page.url()).searchParams.get('zoom');
  await legend.hover(); await page.mouse.wheel(0, 400); await page.waitForTimeout(250);
  expect(new URL(page.url()).searchParams.get('zoom')).toBe(previous);
  await page.keyboard.press('Escape'); await expect(legend).toBeHidden(); await expect(toggle).toBeFocused();
  const focus = page.locator('.wm-map-focus-toggle');
  const before = (await host.boundingBox())!;
  await focus.click(); await expect(page.locator('.wm-map-stage')).toHaveClass(/is-map-focused/);
  await expect.poll(async () => (await host.boundingBox())!.height).toBeGreaterThan(before.height);
  expect(await host.evaluate(el => (el as any).__identity)).toBe('same-map');
  await page.keyboard.press('Escape'); await expect(focus).toBeFocused();
  await expect(page.locator('.wm-map-stage')).not.toHaveClass(/is-map-focused/);
  for (const selector of ['.wm-map-legend-toggle', '.wm-world-event-list-toggle', '.wm-map-radar-status']) {
    expect(await page.locator(selector).evaluate(el => getComputedStyle(el).fontFamily)).toContain('Noto Sans SC Variable');
  }
  const font = await page.evaluate(() => {
    const ctx = document.createElement('canvas').getContext('2d')!;
    ctx.font = '12px "Noto Sans SC Variable"';
    return { loaded: document.fonts.check(ctx.font, 'Tokyo São Paulo Montréal 北京 新加坡'), i: ctx.measureText('iiii').width, w: ctx.measureText('WWWW').width };
  });
  expect(font.loaded).toBe(true); expect(font.w).toBeGreaterThan(font.i * 2);
});

test('list scopes, time meaning and detail return preserve filters', async ({ page }) => {
  await page.goto(url);
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready', 'webgl');
  await page.locator('.wm-world-event-list-toggle').click();
  await expect(page.locator('.wm-world-event-list')).toContainText('Time windows use source updates');
  await page.getByLabel('Event scope', { exact: true }).selectOption('view');
  await page.getByLabel('Event sort', { exact: true }).selectOption('occurred');
  await page.locator('#wm-event-list-search').fill('Test Ridge');
  await page.getByRole('button', { name: /M6.4 Test Ridge Earthquake/ }).click({ timeout: 15_000 });
  await expect(page.locator('.wm-event-inspector')).toBeVisible();
  await expect(page.locator('#wm-world-event-list-panel')).toBeHidden();
  await page.keyboard.press('Escape');
  await expect(page.locator('.wm-event-inspector')).toBeHidden();
  await expect(page.locator('#wm-event-list-search')).toHaveValue('Test Ridge');
  await expect(page.getByLabel('Event sort', { exact: true })).toHaveValue('occurred');
  await page.locator('.wm-world-event-list-close').click();
  await page.locator('.wm-map-radar-status summary').click();
  await page.getByRole('button', { name: 'Enable weather view', exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('layers')).toContain('weather-radar');
  await page.keyboard.press('Escape');
  await expect(page.locator('.wm-map-radar-status')).not.toHaveAttribute('open');
  await expect(page.locator('.wm-map-radar-status summary')).toBeFocused();
});
