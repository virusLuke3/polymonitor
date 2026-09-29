import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium, expect } from '@playwright/test';

// Production acceptance: no routes, fixtures, clock overrides or renderer
// overrides. Use the normal service worker and real API/tile responses.
const base = process.env.POLYMONITOR_LIVE_URL || 'https://polymonitor.club';
const expectedSha = process.env.POLYMONITOR_RELEASE_SHA;
assert(expectedSha && /^[a-f0-9]{40}$/.test(expectedSha), 'Set POLYMONITOR_RELEASE_SHA to the pushed commit.');
const output = resolve(process.env.POLYMONITOR_LIVE_OUTPUT || 'artifacts/live-map');
mkdirSync(output, { recursive: true });
const receipt = { startedAt: new Date().toISOString(), base, expectedSha, checks: [], browsers: [] };
const browser = await chromium.launch({
  channel: 'chrome', headless: true,
  ...(process.env.HTTPS_PROXY ? { proxy: { server: process.env.HTTPS_PROXY } } : {}),
  args: ['--disable-partial-raster', ...(process.env.POLYMONITOR_E2E_HARDWARE_WEBGL === '1'
    ? ['--use-angle=vulkan', '--enable-features=Vulkan'] : [])],
});
async function check(name, action) {
  try { await action(); receipt.checks.push({ name, status: 'passed' }); }
  catch (error) { receipt.checks.push({ name, status: 'failed', error: error.message }); throw error; }
}
async function capture(page, name) {
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: resolve(output, `${name}.png`) });
}
try {
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 1000 }, locale: 'en-US' });
    const page = await context.newPage();
    const record = { width, errors: [], responses: [], failedRequests: [], protocols: [], states: [], screenshots: [] };
    receipt.browsers.push(record);
    const network = await context.newCDPSession(page);
    await network.send('Network.enable');
    network.on('Network.responseReceived', ({ response, type }) => {
      if (type === 'Document' || /\/assets\/.*\.js|planet\.pmtiles/.test(response.url)) {
        record.protocols.push({ url: response.url, protocol: response.protocol, status: response.status });
      }
    });
    page.on('pageerror', error => record.errors.push(error.message));
    page.on('requestfailed', request => record.failedRequests.push({ url: request.url(), error: request.failure()?.errorText }));
    page.on('response', response => {
      if (/\/wm-api\/|planet\.pmtiles|\/assets\/.*\.(js|css)|\/release-sha/.test(response.url())) {
        record.responses.push({ url: response.url(), status: response.status(), range: response.headers()['content-range'] });
      }
    });
    const screenshot = async name => { await capture(page, name); record.screenshots.push(`${name}.png`); };
    try {
      await check(`${width}: release identity`, async () => {
        const response = await context.request.get(`${base}/release-sha?verify=${Date.now()}`);
        assert.equal(response.status(), 200);
        assert.equal((await response.text()).trim(), expectedSha);
      });
      await page.goto(`${base}/?view=2d`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
      const host = page.locator('[data-map-renderer-ready]');
      await check(`${width}: real renderer and events`, async () => {
        await expect(host).toHaveAttribute('data-map-renderer-ready', width === 390 ? 'svg' : 'webgl', { timeout: 60_000 });
        await expect(page.getByRole('button', { name: /ALL EVENTS/ })).toContainText(/[1-9]/, { timeout: 60_000 });
        if (width !== 390) {
          await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready', { timeout: 45_000 });
          record.gpu = await page.evaluate(() => {
            const gl = document.createElement('canvas').getContext('webgl2');
            const debug = gl?.getExtension('WEBGL_debug_renderer_info');
            const name = debug ? String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)) : '';
            gl?.getExtension('WEBGL_lose_context')?.loseContext();
            return name;
          });
          assert(record.gpu && !/swiftshader|llvmpipe|softpipe|software/i.test(record.gpu));
          assert(record.responses.some(r => r.url.includes('planet.pmtiles') && r.status === 206 && r.range));
        }
      });
      // Allow real labels and event sources to finish their first paint.
      await page.waitForTimeout(2000);
      await screenshot(`${width === 390 ? 'mobile' : 'desktop'}-${width}-en`);
      record.states.push({ name: 'initial', url: page.url(), text: (await page.locator('body').innerText()).slice(0,4500) });
      await page.locator('.wm-language-switch select').selectOption('zh');
      await page.waitForTimeout(1500);
      await screenshot(`${width === 390 ? 'mobile' : 'desktop'}-${width}-zh`);
      await check(`${width}: live event details`, async () => {
        await page.getByRole('button', { name: /ALL EVENTS/ }).click();
        await page.locator('.wm-world-event-list-scroll li button').first().click();
        await expect(page.locator('#wm-event-inspector-title')).toBeVisible();
        await screenshot(`event-${width}`);
        await page.getByRole('button', { name: 'Close event details', exact: true }).click();
      });
      if (width !== 390) {
        await check('desktop: theme replacement remains primary after its deadline', async () => {
          await page.getByRole('combobox', { name: 'Basemap theme', exact: true }).selectOption('positron');
          await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready', { timeout: 45_000 });
          await page.waitForTimeout(11_000);
          await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready');
          await screenshot('desktop-light');
          await page.getByRole('combobox', { name: 'Basemap theme', exact: true }).selectOption('dark');
        });
      }
      await check(`${width}: service worker reload uses published assets`, async () => {
        await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller)), { timeout: 30_000 }).toBe(true);
        await page.reload({ waitUntil: 'domcontentloaded', timeout: 60_000 });
        await expect(host).toHaveAttribute('data-map-renderer-ready', width === 390 ? 'svg' : 'webgl', { timeout: 60_000 });
        if (width !== 390) await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready', { timeout: 45_000 });
        record.states.push(await page.evaluate(() => ({ name: 'reload', url: location.href,
          scripts: [...document.scripts].map(s => s.src).filter(Boolean),
          worker: navigator.serviceWorker.controller?.scriptURL,
          status: document.querySelector('.wm-weather-deck-status')?.textContent,
        })));
        assert(record.states.at(-1).worker?.includes(expectedSha));
        await screenshot(`reload-${width}`);
      });
      await check(`${width}: browser and asset errors`, async () => {
        assert.deepEqual(record.errors, []);
        assert.deepEqual(record.responses.filter(r => /\/assets\//.test(r.url) && r.status >= 400), []);
      });
    } catch (error) {
      await screenshot(`failure-${width}`).catch(() => {});
      throw error;
    } finally { await context.close(); }
  }
} catch (error) {
  receipt.failure = error.message;
  process.exitCode = 1;
} finally {
  receipt.finishedAt = new Date().toISOString();
  writeFileSync(resolve(output, 'receipt.json'), `${JSON.stringify(receipt, null, 2)}\n`);
  await browser.close();
  console.log(JSON.stringify({ output, checks: receipt.checks, failure: receipt.failure }, null, 2));
}
