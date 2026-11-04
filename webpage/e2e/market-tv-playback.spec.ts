import { test, expect } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';
import { GENERATED_AT } from './fixtures/world-event-map';

test('TV keeps the channel through failed source, buffering and verified playback', async ({ page }) => {
  await installDashboard(page, 'en', ['market-tv-wire']);
  const payload = { generatedAt: GENERATED_AT, status: 'ok', items: [{
    id: 'dw-test', displayName: 'DW test', category: 'news', sourceType: 'hls', status: 'ready',
    playbackSources: [{ kind: 'youtube', videoId: 'failed12345' }, { kind: 'youtube', videoId: 'liveABC1234' }],
  }] };
  await page.route('**/wm-api/v1/runtime/panels?**', (route) => route.fulfill({ json: {
    apiVersion: 'v1', requestId: 'tv-test', generatedAt: GENERATED_AT, status: 'ok',
    data: { panels: { 'market-tv-wire': payload } }, meta: { panels: {} }, errors: [],
  } }));
  await page.route('**/wm-api/runtime/content/market-tv-wire?**', (route) => route.fulfill({ json: payload }));
  await page.route('**/wm-api/runtime/content/youtube-embed?**', (route) => {
    const videoId = new URL(route.request().url()).searchParams.get('videoId');
    return route.fulfill({ contentType: 'text/html', body: videoId === 'failed12345'
      ? '<script>setTimeout(()=>parent.postMessage({type:"yt-error"},location.origin),100)</script>'
      : '<script>window.progress=(data)=>parent.postMessage({type:"yt-progress",...data},location.origin)</script>' });
  });
  await page.goto('/?view=2d&renderer=svg');
  await page.getByText('MARKET TV WIRE', { exact: true }).first().scrollIntoViewIfNeeded();
  const host = page.locator('[data-channel-id="dw-test"]');
  await host.scrollIntoViewIfNeeded();
  await expect(host).toHaveAttribute('data-playback-attempt', '1');
  const iframe = host.locator('iframe');
  await expect(iframe).toHaveAttribute('src', /liveABC1234/);
  const frame = await (await iframe.elementHandle())!.contentFrame();
  await frame!.evaluate(() => (window as any).progress({ state: 3, isLive: true, time: 0 }));
  await expect(host).not.toHaveAttribute('data-playback-state', 'playing');
  await frame!.evaluate(() => (window as any).progress({ state: 1, isLive: true, time: 10 }));
  await page.waitForTimeout(1200);
  await frame!.evaluate(() => (window as any).progress({ state: 1, isLive: true, time: 11.2 }));
  await expect(host).toHaveAttribute('data-playback-state', 'playing');
  await frame!.evaluate(() => (window as any).progress({ state: 1, isLive: false, time: 12 }));
  await expect(host).toHaveAttribute('data-playback-state', 'blocked');
  await expect(host).toHaveAttribute('data-channel-id', 'dw-test');
  await page.unrouteAll({ behavior: 'ignoreErrors' });
});
