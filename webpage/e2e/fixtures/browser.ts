import type { Page } from '@playwright/test';

/** Keep local test assets independent of host VPN/interface change notifications.
 * Bytes and headers still come from Vite; API fixtures keep their own routes. */
export async function installLocalAssets(page: Page) {
  await page.route(/^http:\/\/127\.0\.0\.1:\d+\//, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/wm-api/')) return route.fallback();
    url.port = process.env.POLYMONITOR_E2E_PORT || '4174';
    const response = await route.fetch({ url: url.href, maxRetries: 2 });
    await route.fulfill({ response });
  });
}
