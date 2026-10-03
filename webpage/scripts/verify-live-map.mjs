import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { PMTiles } from 'pmtiles';
import { VectorTile } from '@mapbox/vector-tile';
import { PbfReader as Pbf } from 'pbf';
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
async function check(name, action, { continueOnFailure = false } = {}) {
  try { await action(); receipt.checks.push({ name, status: 'passed' }); }
  catch (error) {
    receipt.checks.push({ name, status: 'failed', error: error.message });
    if (!continueOnFailure) throw error;
    // Source availability must fail acceptance without hiding independent UI,
    // published-asset and service-worker checks later in the same run.
    receipt.failure ||= error.message;
    process.exitCode = 1;
  }
}
async function capture(page, name) {
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: resolve(output, `${name}.png`) });
}
async function verifyDateline(page, host, width, record) {
  if (width === 1536) await page.setViewportSize({width:2537,height:1286});
  // A complete snapshot prevents earlier theme/layer interactions from
  // silently removing the hazard and country overlays this regression needs.
  const layers='weather-alerts,earthquakes-volcanoes,wildfires,extreme-temperature,climate-anomalies,ucdp,sanctions-country-risk';
  await page.goto(`${base}/?view=2d&center=180,20&zoom=0.93&time=7d&layers=${layers}&theme=dark&basemap=auto&presentation=overview&severity=info,watch,warning,critical`,{waitUntil:'domcontentloaded',timeout:60_000});
  await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready',{timeout:60_000});
  // A single-world map clamps the endpoint camera inside the actual viewport;
  // forcing -180 would expose half a blank world again.
  await expect.poll(() => Number(new URL(page.url()).searchParams.get('center')?.split(',')[0])).toBeGreaterThan(-180);
  const restoredCenter=new URL(page.url()).searchParams.get('center');
  const restoredZoom=new URL(page.url()).searchParams.get('zoom');
  await expect(page.locator('.wm-map-source-status').filter({has:page.locator('b',{hasText:/^COUNTRY RISK$/})})).toHaveClass(/is-ok/,{timeout:45_000});
  await expect(page.locator('.wm-world-event-list-toggle strong')).toContainText(/[1-9]/);
  assert.equal(new URL(page.url()).searchParams.get('theme'),'dark');
  assert.equal(new URL(page.url()).searchParams.get('layers'),layers);
  await page.waitForTimeout(1500);
  const actualWidth=width===1536?2537:width;
  await capture(page,`dateline-${actualWidth}`);
  await host.screenshot({path:resolve(output,`dateline-map-${actualWidth}.png`)});
  record.states.push({name:'dateline',url:page.url(),rect:await host.boundingBox()});
  await page.reload({waitUntil:'domcontentloaded'});
  await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready',{timeout:60_000});
  assert.equal(new URL(page.url()).searchParams.get('center'),restoredCenter);
  assert.equal(new URL(page.url()).searchParams.get('zoom'),restoredZoom);
  await capture(page,`dateline-reload-${actualWidth}`);
  assert.deepEqual(record.errors,[]);
}
async function verifyArchive(page) {
  const ranges=[];
  const source={getKey:()=>`${base}/map-tiles/planet.pmtiles`,getBytes:async(offset,length,_signal,etag)=>{
    assert(length<=2_000_000,'Bounded range verification must not download an archive');
    const result=await page.evaluate(async({url,offset,length,etag})=>{
      const controller=new AbortController(),deadline=setTimeout(()=>controller.abort(),20_000);
      try {
        const response=await fetch(url,{headers:{Range:`bytes=${offset}-${offset+length-1}`,...(etag?{'If-Range':etag}:{})},signal:controller.signal,cache:'no-cache'});
        if(response.status!==206){controller.abort();throw new Error(`Range returned ${response.status}; body deliberately not downloaded`);}
        const data=new Uint8Array(await response.arrayBuffer());let encoded='';for(let i=0;i<data.length;i+=16384)encoded+=String.fromCharCode(...data.subarray(i,i+16384));
        return {headers:Object.fromEntries(response.headers.entries()),bytes:btoa(encoded),status:response.status};
      }finally{clearTimeout(deadline);}
    },{url:`${base}/map-tiles/planet.pmtiles`,offset,length,etag});
    const data=Buffer.from(result.bytes,'base64'),range=result.headers['content-range'];
    assert.equal(data.length,length);assert.match(range,new RegExp(`^bytes ${offset}-${offset+length-1}/[0-9]+$`));
    if(etag)assert.equal(result.headers.etag,etag);
    ranges.push({offset,length,status:result.status,headers:result.headers,sha256:createHash('sha256').update(data).digest('hex')});
    return {data:data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength),etag:result.headers.etag};
  }};
  await source.getBytes(0,16384);await source.getBytes(65536,4096);
  assert(ranges[0].headers.etag);assert.equal(ranges[0].headers.etag,ranges[1].headers.etag);
  const repeated=await source.getBytes(65536,4096,undefined,ranges[1].headers.etag);assert(repeated.data.byteLength===4096);assert.equal(ranges[1].sha256,ranges[2].sha256);
  const archive=new PMTiles(source),header=await archive.getHeader();assert.equal(header.specVersion,3);
  const decoded=[];for(const [z,x,y] of [[3,2,3],[3,6,2]]){
    const tile=await archive.getZxy(z,x,y);assert(tile?.data);const vector=new VectorTile(new Pbf(new Uint8Array(tile.data)));
    const layers=Object.entries(vector.layers).map(([name,layer])=>({name,features:layer.length}));assert(layers.some(l=>l.features>0));decoded.push({z,x,y,layers});
  }
  receipt.archive={ranges,decoded,header};
}

// Shared-renderer release gate. Keep APIs, tiles, clock and service worker real;
// record unavailable providers separately from renderer/asset failures.
async function verifySharedRenderers() {
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 900 }, locale: 'en-US' });
    const page = await context.newPage();
    const record = { width, errors: [], assets: [], sources: [], states: [] };
    receipt.browsers.push(record);
    page.on('pageerror', error => record.errors.push(error.message));
    page.on('response', response => {
      if (/\/assets\//.test(response.url())) record.assets.push({ url: response.url(), status: response.status() });
    });
    await context.tracing.start({ screenshots: true, snapshots: true });
    try {
      await check(`${width}: exact published release`, async () => {
        const response = await context.request.get(`${base}/release-sha?verify=${Date.now()}`);
        assert.equal((await response.text()).trim(), expectedSha);
      });
      await page.goto(`${base}/?view=2d`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
      const host = page.locator('[data-map-renderer-ready]');
      await check(`${width}: real 2D primary map and lazy 3D assets`, async () => {
        await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl', { timeout: 60_000 });
        await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready', { timeout: 60_000 });
        await expect(page.locator('.wm-world-event-list-toggle strong')).toContainText(/[1-9]/, { timeout: 60_000 });
        assert(!record.assets.some(asset => /GlobeMapRenderer/.test(asset.url)));
        record.gpu = await host.locator('.maplibregl-canvas').evaluate(canvas => {
          const gl = canvas.getContext('webgl2'), debug = gl.getExtension('WEBGL_debug_renderer_info');
          return gl.getParameter(debug.UNMASKED_RENDERER_WEBGL);
        });
        assert(record.gpu && !/swiftshader|llvmpipe|softpipe|software/i.test(record.gpu));
        await capture(page, `shared-2d-${width}`);
      });
      if (width === 1440) await check('shared map: real PMTiles ranges and vector content', () => verifyArchive(page));
      await check(`${width}: real 3D sources, controls, details and pause`, async () => {
        await page.getByRole('tab', { name: '3D Globe', exact: true }).click();
        await page.locator('.wm-map-stage').scrollIntoViewIfNeeded();
        await expect(host).toHaveAttribute('data-map-renderer-ready', 'globe', { timeout: 90_000 });
        const globe = page.locator('.wm-globe-renderer');
        await expect.poll(async () => Number(await globe.getAttribute('data-globe-records'))).toBeGreaterThan(0);
        await expect(page.locator('.wm-map-radar-status')).toContainText('2D WebGL only');
        const zoom = Number(new URL(page.url()).searchParams.get('zoom'));
        await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
        await expect.poll(() => Number(new URL(page.url()).searchParams.get('zoom'))).toBeGreaterThan(zoom);
        await globe.locator('select').selectOption('performance');
        await capture(page, `shared-3d-${width}`);
        record.states.push({ mode: '3d', url: page.url(), records: await globe.getAttribute('data-globe-records'), rect: await globe.boundingBox() });
        await page.locator('.wm-world-event-list-toggle').click();
        await page.locator('.wm-world-event-list-scroll li button').first().click();
        await expect(page.locator('#wm-event-inspector-title')).toBeVisible();
        await capture(page, `shared-3d-detail-${width}`);
        await page.locator('.wm-event-inspector-close').click();
        const closeList = page.locator('.wm-world-event-list-close');
        if (await closeList.isVisible()) await closeList.click();
        await page.locator('.wm-focused-market-row').scrollIntoViewIfNeeded();
        // Scroll further into the actual dashboard; no synthetic spacer on live UI.
        await page.locator('.wm-main-content').evaluate(el => {
          el.scrollTop = el.scrollHeight;
          window.scrollTo(0, document.documentElement.scrollHeight);
        });
        await expect(globe).toHaveAttribute('data-render-paused', 'true');
        await page.locator('.wm-map-stage').scrollIntoViewIfNeeded();
        await expect(globe).toHaveAttribute('data-render-paused', 'false');
        await expect.poll(async () => Number(await globe.getAttribute('data-globe-records'))).toBeGreaterThan(0);
        await capture(page, `shared-3d-resumed-${width}`);
      });
      await check(`${width}: 2D return and service worker release`, async () => {
        await page.getByRole('tab', { name: '2D Map', exact: true }).click();
        await page.locator('.wm-map-stage').scrollIntoViewIfNeeded();
        await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl', { timeout: 60_000 });
        await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready', { timeout: 60_000 });
        await expect(page.locator('.wm-globe-renderer')).toHaveCount(0);
        await page.reload({ waitUntil: 'domcontentloaded' });
        await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready', { timeout: 60_000 });
        await expect.poll(() => page.evaluate(() => navigator.serviceWorker.controller?.scriptURL || ''), { timeout: 30_000 }).toContain(expectedSha);
        record.worker = await page.evaluate(() => navigator.serviceWorker.controller.scriptURL);
        record.sources = await page.locator('.wm-map-source-status').allTextContents();
        await capture(page, `shared-reloaded-${width}`);
      });
      await check(`${width}: no renderer or published asset errors`, async () => {
        assert.deepEqual(record.errors, []);
        assert.deepEqual(record.assets.filter(asset => asset.status >= 400), []);
      });
    } catch (error) {
      receipt.failure ||= error.message; record.failure = error.message; process.exitCode = 1;
      await capture(page, `shared-failure-${width}`).catch(() => {});
    } finally {
      await context.tracing.stop({ path: resolve(output, `shared-${width}.zip`) });
      await context.close();
    }
  }
}

try {
  if (process.env.POLYMONITOR_VERIFY_SHARED_RENDERERS === '1') await verifySharedRenderers();
  if(process.env.POLYMONITOR_WAIT_RELEASE==='1'){
    const context=await browser.newContext({viewport:{width:1536,height:1000}}),page=await context.newPage();
    await context.tracing.start({screenshots:true,snapshots:true});
    const oldAssets=[];let published=false;page.on('response',response=>{if(/\/assets\/.*\.(js|css)/.test(response.url()))oldAssets.push({url:response.url(),status:response.status(),phase:published?'after publish':'old page'});});
    await page.goto(`${base}/?view=3d`,{waitUntil:'domcontentloaded'});
    const old=await context.request.get(`${base}/release-sha?verify=${Date.now()}`);receipt.previousRelease=(await old.text()).trim();
    writeFileSync(resolve(output,'old-session-ready.json'),JSON.stringify({previous:receipt.previousRelease,expectedSha}));
    const deadline=Date.now()+20*60_000;
    while(Date.now()<deadline){const live=await context.request.get(`${base}/release-sha?verify=${Date.now()}`);if((await live.text()).trim()===expectedSha)break;await new Promise(resolve=>setTimeout(resolve,5000));}
    const released=await context.request.get(`${base}/release-sha?verify=${Date.now()}`);assert.equal((await released.text()).trim(),expectedSha);published=true;
    await page.getByRole('tab',{name:'2D Map',exact:true}).click();
    await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-basemap-state','primary-ready',{timeout:60_000});
    receipt.oldSession={previous:receipt.previousRelease,current:expectedSha,scripts:await page.evaluate(()=>[...document.scripts].map(s=>s.src).filter(Boolean)),state:page.url(),lateImport:'painted primary 2D',assets:oldAssets,worker:await page.evaluate(()=>navigator.serviceWorker.controller?.scriptURL)};
    assert.deepEqual(oldAssets.filter(asset=>asset.status>=400),[]);
    await capture(page,'old-session-late-2d');await context.tracing.stop({path:resolve(output,'old-session.zip')});await context.close();
  }
  if(process.env.POLYMONITOR_VERIFY_RANGE_ONLY==='1'){
    const context=await browser.newContext(),page=await context.newPage();await page.goto(base,{waitUntil:'domcontentloaded'});await check('real PMTiles byte ranges and decoded distant vector tiles',()=>verifyArchive(page));await context.close();
  }
  for (const width of process.env.POLYMONITOR_VERIFY_RANGE_ONLY==='1' || process.env.POLYMONITOR_VERIFY_SHARED_RENDERERS==='1'?[]:[1536, 390]) {
    const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 1000 }, locale: 'en-US' });
    const page = await context.newPage();
    await context.tracing.start({ screenshots: true, snapshots: true, sources: false });
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
      if (/rainviewer\.com|\/wm-api\/|planet\.pmtiles|\/assets\/.*\.(js|css)|\/release-sha/.test(response.url())) {
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
      if (process.env.POLYMONITOR_VERIFY_DATELINE_ONLY==='1') {
        await check(`${width}: native dark hazard and risk overlays at the dateline and after reload`,()=>verifyDateline(page,page.locator('[data-map-renderer-ready]'),width,record));
        await check(`${width}: browser and published asset errors`,async()=>{
          assert.deepEqual(record.errors,[]);
          assert.deepEqual(record.responses.filter(r=>/\/assets\//.test(r.url)&&r.status>=400),[]);
        });
        continue;
      }
      await page.goto(`${base}/?view=2d`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
      const host = page.locator('[data-map-renderer-ready]');
      if(width!==390)await check('real PMTiles byte ranges and decoded distant vector tiles',()=>verifyArchive(page));
      await check(`${width}: real renderer and events`, async () => {
        await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl', { timeout: 60_000 });
        await expect(page.locator('.wm-world-event-list-toggle strong')).toContainText(/[1-9]/, { timeout: 60_000 });
        {
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
      await check(`${width}: default overview and measured responsive layout`,async()=>{
        record.layout={rect:await host.boundingBox(),viewport:await page.evaluate(()=>({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})),presentation:new URL(page.url()).searchParams.get('presentation'),canvases:await host.locator('canvas').count()};
        assert.equal(record.layout.presentation,'overview');assert(record.layout.rect.width<=width+1);
        if(width===1536)assert(record.layout.rect.height>=680,JSON.stringify(record.layout));
      });
      if (width !== 390) await check('desktop: healthy core sources and explicit optional NWS boundaries', async () => {
        for (const label of ['NHC', 'FIRMS', 'COUNTRY RISK']) {
          const badge = page.locator('.wm-map-source-status').filter({ has: page.locator('b', { hasText: new RegExp(`^${label}$`) }) });
          await expect(badge).toHaveClass(/is-ok/, { timeout: 120_000 });
        }
        const nwsBadge = page.locator('.wm-map-source-status').filter({ has: page.locator('b', { hasText: /^NWS$/ }) });
        const nwsResponse = await context.request.get(`${base}/wm-api/runtime/world/natural-hazards/map?source=nws&limit=1200&zoom=2`);
        assert.equal(nwsResponse.status(), 200);
        const nws = await nwsResponse.json(), core = nws.sources.find(source => source.key === 'nws');
        assert(core && core.status === 'ok' && !core.errorCode, JSON.stringify(core));
        assert.deepEqual(nws.errors, []);
        assert(Date.now() - Date.parse(core.lastSuccessAt) < 300_000);
        assert(Date.parse(core.staleAfter) > Date.now());
        const geometryIncomplete = nws.events.some(event => !event.geometry || Number(event.properties?.unresolvedZoneCount || 0) > 0);
        // The independent API probe can observe a newer CAP revision than the
        // page. Check the page's own boundary explanation and record both.
        await expect(nwsBadge).toHaveClass(/is-(ok|partial)/, { timeout: 30_000 });
        const displayedGeometryIncomplete = /optional official boundaries/.test(await nwsBadge.getAttribute('title') || '');
        if (displayedGeometryIncomplete) {
          await expect(nwsBadge).toHaveClass(/is-partial/);
          await expect(nwsBadge).toHaveAttribute('title', /Fresh catalog; optional official boundaries/);
        } else await expect(nwsBadge).toHaveClass(/is-ok/);
        record.nws = { core, count: nws.events.length, geometryIncomplete, displayedGeometryIncomplete, badge: await nwsBadge.innerText(), explanation: await nwsBadge.getAttribute('title') };
        record.sourceHealth = await page.locator('.wm-map-source-statuses').innerText();
      }, { continueOnFailure: true });
      await check(`${width}: map typography uses proportional map roles`, async () => {
        const fonts = await page.evaluate(() => {
          const family = selector => getComputedStyle(document.querySelector(selector)).fontFamily;
          return { body: family('.wm-shell'), toolbar: family('.wm-world-event-map-toolbar'), legend: family('.wm-weather-deck-legend') };
        });
        record.fonts = fonts;
        assert.match(fonts.toolbar, /Noto Sans SC Variable/);
        assert.match(fonts.legend, /Noto Sans SC Variable/);
        record.fontReadiness = await page.evaluate(() => { const ctx = document.createElement('canvas').getContext('2d'); ctx.font = '12px \"Noto Sans SC Variable\"'; return { loaded: document.fonts.check(ctx.font, 'Tokyo São Paulo Montréal 北京 新加坡'), i: ctx.measureText('iiii').width, w: ctx.measureText('WWWW').width }; });
        assert(record.fontReadiness.loaded && record.fontReadiness.w > record.fontReadiness.i * 2);
      });
      if (width !== 390) await check('desktop: default real radar frame and tiles', async () => {
        await expect(page.locator('.wm-map-radar-status')).toContainText('ready / ready', { timeout: 60_000 });
        assert(record.responses.some(r => r.url.includes('/v2/radar/') && r.status === 200));
        record.radar = await page.locator('.wm-map-radar-status').innerText();
      });
      if (width > 900) await check('desktop: aviation card leaves map controls accessible', async () => {
        const lens = await page.locator('.wm-aviation-lens').boundingBox();
        const expand = await page.locator('.wm-map-focus-toggle').boundingBox();
        if (lens) assert(lens.x + lens.width <= expand.x);
      });
      if (width === 390) await check('mobile: aviation leaves navigation and event controls accessible', async () => {
        const lens = await page.locator('.wm-aviation-lens').boundingBox();
        if (!lens) return;
        for (const selector of ['.wm-map-controls', '.wm-map-focus-toggle', '.wm-world-event-list-toggle', '.wm-map-radar-status', '.wm-map-legend-toggle']) {
          const control = await page.locator(selector).boundingBox();
          assert(control, selector);
          assert(!(Math.min(lens.x + lens.width, control.x + control.width) > Math.max(lens.x, control.x)
            && Math.min(lens.y + lens.height, control.y + control.height) > Math.max(lens.y, control.y)), selector);
        }
      });
      // Allow real labels and event sources to finish their first paint.
      await page.waitForTimeout(2000);
      await screenshot(`${width === 390 ? 'mobile' : 'desktop'}-${width}-en`);
      if(width===390){await host.scrollIntoViewIfNeeded();await screenshot('mobile-map-visible-390-en');}
      record.states.push({ name: 'initial', url: page.url(), text: (await page.locator('body').innerText()).slice(0,4500) });
      await page.locator('.wm-language-switch select').selectOption('zh');
      await page.waitForTimeout(1500);
      await screenshot(`${width === 390 ? 'mobile' : 'desktop'}-${width}-zh`);
      await check(`${width}: live event details`, async () => {
        await page.locator('.wm-world-event-list-toggle').click();
        await page.locator('.wm-world-event-list-scroll li button').first().click();
        await expect(page.locator('#wm-event-inspector-title')).toBeVisible();
        await screenshot(`event-${width}`);
        await page.locator('.wm-event-inspector-close').click();
        const closeList = page.locator('.wm-world-event-list-close'); if (await closeList.isVisible()) await closeList.click();
      });
      if (width !== 390) {
        await check('desktop: theme replacement remains primary after its deadline', async () => {
          await page.locator('.wm-world-event-basemap-control select').nth(1).selectOption('positron');
          await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready', { timeout: 45_000 });
          await page.waitForTimeout(11_000);
          await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready');
          await screenshot('desktop-light');
          await page.locator('.wm-world-event-basemap-control select').nth(1).selectOption('dark');
        });
      }
      if (width !== 390) {
        await page.locator('.wm-language-switch select').selectOption('en');
        await check('desktop: live aircraft source, map and details', async () => {
          const observed = [];
          const responseListener = async response => {
            if (response.url().includes('/aviation-viewport?') && response.ok()) {
              const payload = await response.json().catch(() => null);
              if (payload) observed.push(payload);
            }
          };
          page.on('response', responseListener);
          await page.goto(`${base}/?view=2d&center=-98,39&zoom=3&layers=air-routes,weather-radar&air=all`, { waitUntil: 'domcontentloaded' });
          await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl', { timeout: 60_000 });
          await expect.poll(() => observed.some(payload => payload.aircraft?.length > 0), { timeout: 60_000 }).toBe(true);
          const snapshot = observed.find(payload => payload.aircraft?.length > 0);
          const expandAviation=page.getByRole('button',{name:'Expand aviation details'});
          if (await expandAviation.isVisible()) await expandAviation.click();
          record.aircraft = { source: snapshot.source, status: snapshot.status, generatedAt: snapshot.generatedAt, count: snapshot.aircraft.length, limitations: snapshot.limitations };
          const aircraft = snapshot.aircraft.find(item => item.callsign) || snapshot.aircraft[0];
          await expect(page.locator('.wm-aviation-lens-stats')).toContainText('observed aircraft');
          await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready', { timeout: 45_000 });
          await expect(page.locator('.wm-map-radar-status')).toContainText('ready / ready', { timeout: 60_000 });
          await page.waitForTimeout(2000);
          await screenshot('desktop-aircraft');
          await page.locator('.wm-world-event-list-toggle').click();
          await page.locator('.wm-world-event-list input[type="search"]').fill(aircraft.callsign || aircraft.icao24);
          await page.locator('.wm-world-event-list-scroll li button').first().click();
          await expect(page.locator('.wm-event-inspector')).toContainText('ICAO24');
          await screenshot('desktop-aircraft-detail');
          await page.locator('.wm-event-inspector-close').click();
        const closeList = page.locator('.wm-world-event-list-close'); if (await closeList.isVisible()) await closeList.click();
          const regional = await context.request.get(`${base}/wm-api/runtime/transport/aviation-viewport?bbox=-75,39,-72,42&zoom=5&limit=360`);
          assert.equal(regional.status(), 200);
          record.regionalAviation = await regional.json();
          assert.equal(record.regionalAviation.coverage?.complete, true, JSON.stringify(record.regionalAviation.errors));
          assert.deepEqual(record.regionalAviation.errors, []);
          assert(record.regionalAviation.aircraftCount > 0);
          // Query coverage does not assert worldwide receiver coverage or that
          // the OpenSky authorization path is reachable from this GCP host.
          page.off('response', responseListener);
        }, { continueOnFailure: true });
      }
      if(width===1536)await check('desktop: real offline and online recovery',async()=>{
        const resumed=[];const listener=response=>{if(response.url().includes('/wm-api/runtime/')&&response.ok())resumed.push({url:response.url(),status:response.status()});};page.on('response',listener);
        try {
          await context.setOffline(true);await page.waitForTimeout(1500);await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');await screenshot('desktop-offline');
          await context.setOffline(false);await expect.poll(()=>resumed.length,{timeout:45000}).toBeGreaterThan(0);await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');record.realConnectivityCycle={offlineRenderer:'webgl',resumed};await screenshot('desktop-online-recovered');
        } finally {
          // A failed offline assertion must not poison later, independent gates.
          await context.setOffline(false);page.off('response',listener);
        }
      },{continueOnFailure:true});
      await check(`${width}: service worker reload uses published assets`, async () => {
        await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller)), { timeout: 30_000 }).toBe(true);
        await page.reload({ waitUntil: 'domcontentloaded', timeout: 60_000 });
        await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl', { timeout: 60_000 });
        await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready', { timeout: 45_000 });
        record.states.push(await page.evaluate(() => ({ name: 'reload', url: location.href,
          scripts: [...document.scripts].map(s => s.src).filter(Boolean),
          worker: navigator.serviceWorker.controller?.scriptURL,
          status: document.querySelector('.wm-weather-deck-status')?.textContent,
        })));
        assert(record.states.at(-1).worker?.includes(expectedSha));
        await screenshot(`reload-${width}`);
      });
      await check(`${width}: anonymous public health and classified recent-trade availability`, async () => {
        const session = await context.request.get(`${base}/wm-api/auth/session`);
        assert.equal((await session.json()).authenticated, false);
        assert.deepEqual(record.responses.filter(r => r.url.includes('/wm-api/system/health')), []);
        const publicHealth = await context.request.get(`${base}/wm-api/health`);
        assert.equal(publicHealth.status(), 200);
        const privateHealth = await context.request.get(`${base}/wm-api/system/health`);
        assert.equal(privateHealth.status(), 401); // The admin contract stays protected.
        const trades = await context.request.get(`${base}/wm-api/trades/recent?limit=3`);
        const payload = await trades.json();
        assert([200, 503].includes(trades.status()), `Unexpected trade response: ${trades.status()}`);
        if (trades.status() === 503) assert.equal(payload.status, 'unavailable');
        else assert(Array.isArray(payload));
        record.dashboardSources = { publicHealth: await publicHealth.json(), protectedHealth: privateHealth.status(),
          trades: { http: trades.status(), payload, availability: trades.status() === 503 ? 'UNAVAILABLE' : payload.length ? 'RECORDS_RETURNED' : 'EMPTY' } };
      });
      await check(`${width}: browser and asset errors`, async () => {
        assert.deepEqual(record.errors, []);
        assert.deepEqual(record.responses.filter(r => /\/assets\//.test(r.url) && r.status >= 400), []);
      });
      await check(`${width}: positive dateline link, reload and single-world composition`, async () => {
        await verifyDateline(page,host,width,record);
      });
    } catch (error) {
      await screenshot(`failure-${width}`).catch(() => {});
      record.failure = error.message;
      receipt.failure = receipt.failure || error.message;
      process.exitCode = 1;
    } finally { await context.tracing.stop({ path: resolve(output, `production-${width}.zip`) }); await context.close(); }
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
