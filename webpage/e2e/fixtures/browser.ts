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

/** Layer-specific regression scenes now select their layers through the same
 * controls as a user, after the real all-on entry. Never bypass entry policy. */
export async function selectMapLayers(page: Page, layerIds: string[]) {
  const panel = page.locator('#wm-layer-sidebar');
  await panel.waitFor({ state: 'visible' });
  const toggle = panel.locator('.wm-toggle-collapse');
  const collapsed = await toggle.getAttribute('aria-expanded') === 'false';
  if (collapsed) await toggle.click();
  const inputs = panel.locator('input[type="checkbox"]');
  for (const input of await inputs.all()) {
    if (await input.isDisabled()) continue; // renderer/source capability still applies
    await input.setChecked(layerIds.includes(await input.inputValue()));
  }
  if (collapsed) await toggle.click();
}

export async function gotoMapScene(page: Page, url: string, options?: Parameters<Page['goto']>[1]) {
  const result = await page.goto(url, options);
  const params = new URL(url, 'http://127.0.0.1').searchParams;
  if (['2d','3d'].includes(params.get('view') || '') && params.has('layers')) {
    await selectMapLayers(page, params.get('layers')!.split(',').filter(Boolean));
  }
  return result;
}
