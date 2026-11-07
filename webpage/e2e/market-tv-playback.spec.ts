import { test, expect } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';
import { GENERATED_AT } from './fixtures/world-event-map';

for (const mode of ['mse-and-native', 'native-only', 'unsupported'] as const) {
  test(`TV selects the supported HLS engine: ${mode}`, async ({ page }) => {
    await installDashboard(page, 'en', ['market-tv-wire']);
    await page.addInitScript((mode) => {
      const canPlay = HTMLMediaElement.prototype.canPlayType;
      HTMLMediaElement.prototype.canPlayType = function (type) {
        return type === 'application/vnd.apple.mpegurl'
          ? (mode === 'unsupported' ? '' : 'maybe') : canPlay.call(this, type);
      };
      if (mode !== 'mse-and-native') {
        for (const name of ['MediaSource', 'ManagedMediaSource', 'WebKitMediaSource']) {
          Object.defineProperty(window, name, { configurable: true, value: undefined });
        }
      }
      // These cases isolate engine ownership, not source decoding or autoplay.
      HTMLMediaElement.prototype.play = async () => {};
      const revoke = URL.revokeObjectURL;
      (window as any).revokedMediaUrls = [];
      URL.revokeObjectURL = (url) => {
        (window as any).revokedMediaUrls.push(url);
        revoke.call(URL, url);
      };
    }, mode);
    const mediaUrl = 'https://tv-fixture.invalid/live.m3u8';
    const payload = { generatedAt: GENERATED_AT, status: 'ok', items: [{
      id: 'engine-test', displayName: 'Engine test', category: 'news', sourceType: 'hls', status: 'ready',
      playbackSources: [{ kind: 'hls', url: mediaUrl }, { kind: 'youtube', videoId: 'liveABC1234' }],
    }] };
    await page.route('**/wm-api/v1/runtime/panels?**', (route) => route.fulfill({ json: {
      apiVersion: 'v1', requestId: 'tv-engine-test', generatedAt: GENERATED_AT, status: 'ok',
      data: { panels: { 'market-tv-wire': payload } }, meta: { panels: {} }, errors: [],
    } }));
    await page.route('**/wm-api/runtime/content/market-tv-wire?**', (route) => route.fulfill({ json: payload }));
    // Keep the manifest pending so both engines can be inspected before any
    // codec/network failure. All fixture media requests stay inside this test.
    await page.route('https://tv-fixture.invalid/**', () => {});
    await page.route('**/wm-api/runtime/content/youtube-embed?**', (route) => route.fulfill({ contentType: 'text/html', body: '<p>Fallback</p>' }));
    await page.goto('/?view=2d&renderer=svg', { waitUntil: 'domcontentloaded' });
    await page.getByText('MARKET TV WIRE', { exact: true }).first().scrollIntoViewIfNeeded();
    const host = page.locator('[data-channel-id="engine-test"]');
    await host.scrollIntoViewIfNeeded();
    if (mode === 'unsupported') {
      await expect(host).toHaveAttribute('data-playback-attempt', '1');
      await expect(host.locator('iframe')).toBeAttached();
    } else {
      const video = host.locator('video');
      await expect(video).toHaveAttribute('src', mode === 'mse-and-native' ? /^blob:/ : mediaUrl);
      const src = await video.getAttribute('src');
      const oldVideo = await video.elementHandle();
      await video.dispatchEvent('error');
      await expect(host).toHaveAttribute('data-playback-attempt', '1');
      await expect(host.locator('iframe')).toBeAttached();
      await expect.poll(() => oldVideo!.getAttribute('src')).toBeNull();
      if (mode === 'mse-and-native') {
        await expect.poll(() => page.evaluate((url) => (window as any).revokedMediaUrls.includes(url), src)).toBe(true);
      }
    }
    await page.unrouteAll({ behavior: 'ignoreErrors' });
  });
}

test('TV keeps the channel through failed source, buffering and verified playback', async ({ page }) => {
  await page.clock.install();
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
  await page.clock.fastForward(61000);
  await expect(host).toHaveAttribute('data-playback-attempt', '1');
  await expect(host).toHaveAttribute('data-channel-id', 'dw-test');
  await page.unrouteAll({ behavior: 'ignoreErrors' });
});
