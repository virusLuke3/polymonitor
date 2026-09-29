import { createHash } from 'node:crypto';
import { mkdirSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { request, type Page } from '@playwright/test';
const cache = resolve('artifacts/map-alignment/input-assets');
export async function installRealMapAssets(page: Page) {
  mkdirSync(cache, { recursive: true });
    const network = await request.newContext({
      ...(process.env.HTTPS_PROXY ? { proxy: { server: process.env.HTTPS_PROXY } } : {}),
    });
    await page.route(/(?:\/map-tiles\/|https:\/\/protomaps\.github\.io\/basemaps-assets\/)/, async route => {
      const url = new URL(route.request().url());
      if (url.pathname.startsWith('/map-tiles/')) {
        url.protocol = 'https:'; url.host = 'polymonitor.club'; url.port = '';
      }
      const range = route.request().headers().range;
      const key = createHash('sha256').update(url.href + (range || '')).digest('hex');
      const bodyPath = resolve(cache, key);
      const metaPath = `${bodyPath}.json`;
      if (existsSync(metaPath)) {
        await route.fulfill({ ...JSON.parse(readFileSync(metaPath, 'utf8')), body: readFileSync(bodyPath) });
        return;
      }
      const response = await network.get(url.href, { headers: range ? { Range: range } : {}, timeout: 30_000 });
      const body = await response.body();
      const headers = response.headers();
      delete headers['content-encoding']; delete headers['content-length'];
      const metadata = { status: response.status(), headers };
      if (response.ok()) { writeFileSync(bodyPath, body); writeFileSync(metaPath, JSON.stringify(metadata)); }
      await route.fulfill({ ...metadata, body });
    });
  return network;
}
