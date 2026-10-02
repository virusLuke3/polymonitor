import { gotoMapScene } from './fixtures/browser';
import { test, expect } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { installFixtures, GENERATED_AT } from './fixtures/world-event-map';
import { installRealMapAssets } from './fixtures/real-map-assets';

const phase = process.env.MAP_RECOVERY_PHASE;
const root = resolve('artifacts/map-visual-recovery-v3', phase || 'unrequested');
test.skip(!phase, 'Explicit V3 comparison captures.');
test.use({ trace: 'on', reducedMotion: 'reduce' });
test('an expired successful climate snapshot recovers without waiting six hours', async ({page}) => {
  test.skip(phase === 'before'); mkdirSync(root, {recursive:true});
  await page.clock.install({time:new Date(GENERATED_AT)}); await installFixtures(page);
  const {mapResponse,sourceEvents} = await import('./fixtures/world-event-map');
  const bodies:any[] = [];
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**', async route => {
    const key = new URL(route.request().url()).searchParams.get('source')!;
    const body = mapResponse(key, sourceEvents[key] || []);
    if (key === 'climate-anomaly') {
      const fresh = bodies.length >= 2;
      const now = await page.evaluate(() => Date.now());
      body.sources[0].fetchedAt = new Date(fresh ? now : Date.parse(GENERATED_AT)-21_601_000).toISOString();
      body.sources[0].lastSuccessAt = body.sources[0].fetchedAt;
      body.sources[0].staleAfter = new Date(fresh ? now+21_600_000 : Date.parse(GENERATED_AT)-1_000).toISOString();
      bodies.push(body);
    }
    await route.fulfill({json:body});
  });
  try {
    await gotoMapScene(page, '/?view=2d&renderer=svg&time=all&layers=climate-anomalies');
    const status=page.locator('.wm-map-source-status').filter({has:page.locator('b',{hasText:/^ANOMALY$/})});
    await expect(status).toHaveClass(/is-degraded/); expect(bodies).toHaveLength(1);
    const count=await page.getByRole('button',{name:/^All events/i}).textContent();
    await page.clock.fastForward(29_000); expect(bodies).toHaveLength(1);
    await page.clock.fastForward(5_000); await expect.poll(()=>bodies.length).toBe(2);
    await expect(status).toHaveClass(/is-degraded/);
    expect(await page.getByRole('button',{name:/^All events/i}).textContent()).toBe(count);
    await page.clock.fastForward(55_000); expect(bodies).toHaveLength(2);
    await page.clock.fastForward(10_000); await expect.poll(()=>bodies.length).toBe(3);
    await expect(status).toHaveClass(/is-ok/);
    expect(bodies[0].sources[0].lastSuccessAt).toBe(bodies[1].sources[0].lastSuccessAt);
    writeFileSync(resolve(root,'expired-snapshot-recovery.json'),JSON.stringify({bodies,count}));
  } finally {await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});}
});

for (const condition of ['throttled','blocked']) test(`retained source ${condition} respects the provider retry condition`, async ({page})=>{
  test.skip(phase==='before'); await page.clock.install({time:new Date(GENERATED_AT)});await installFixtures(page);
  const {mapResponse,sourceEvents}=await import('./fixtures/world-event-map');let attempts=0;
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**',async route=>{
    const key=new URL(route.request().url()).searchParams.get('source')!;
    const body=mapResponse(key,sourceEvents[key]||[]);
    if(key==='climate-anomaly') {attempts++;Object.assign(body.sources[0],{status:'degraded',condition,retryAfterSeconds:90});}
    await route.fulfill({json:body});
  });
  try {
    await gotoMapScene(page, '/?view=2d&renderer=svg&time=all&layers=climate-anomalies');
    await expect.poll(()=>attempts).toBe(1);
    await expect(page.locator('.wm-map-source-status').filter({has:page.locator('b',{hasText:/^ANOMALY$/})})).toHaveClass(/is-degraded/);
    await page.clock.fastForward(89_000);expect(attempts).toBe(1);
    await page.clock.fastForward(condition==='blocked'?300_000:5_000);
    await expect.poll(()=>attempts).toBe(condition==='blocked'?1:2);
  } finally {await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});}
});

test('a cached hazard response refreshes at its original server deadline', async ({page}) => {
  test.skip(phase === 'before'); mkdirSync(root, {recursive:true});
  await page.clock.install({time:new Date(GENERATED_AT)}); await installFixtures(page);
  const assets = await installRealMapAssets(page);
  const {mapResponse,sourceEvents} = await import('./fixtures/world-event-map');
  const bodies:any[] = [];
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**', async route => {
    const key = new URL(route.request().url()).searchParams.get('source')!;
    const body = mapResponse(key, sourceEvents[key] || []);
    if (key === 'usgs') {
      const now = await page.evaluate(() => Date.now());
      const first = bodies.length === 0;
      body.sources[0].fetchedAt = new Date(first ? Date.parse(GENERATED_AT)-55_000 : now).toISOString();
      body.sources[0].lastSuccessAt = body.sources[0].fetchedAt;
      body.sources[0].staleAfter = new Date(first ? Date.parse(GENERATED_AT)+5_000 : now+60_000).toISOString();
      bodies.push(body);
    }
    await route.fulfill({json:body});
  });
  try {
    await gotoMapScene(page, '/?view=2d&basemap=pmtiles&time=all&layers=earthquakes-volcanoes');
    await expect.poll(() => bodies.length).toBeGreaterThan(0);
    await expect(page.locator('.wm-map-source-status').filter({has:page.locator('b',{hasText:/^USGS$/})})).toHaveClass(/is-ok/);
    await page.clock.fastForward(10_000);
    await expect.poll(() => bodies.length).toBeGreaterThan(1);
    expect(bodies.length).toBeLessThanOrEqual(3);
    expect(bodies[0].sources[0].lastSuccessAt).toBe(new Date(Date.parse(GENERATED_AT)-55_000).toISOString());
    writeFileSync(resolve(root,'source-deadline-refresh.json'), JSON.stringify({bodies,originalTimestampPreserved:true}));
  } finally { await page.goto('about:blank'); await page.unrouteAll({behavior:'ignoreErrors'}); await assets.dispose(); }
});

test('optional country loading does not falsely demote a ready cached basemap', async ({page}) => {
  test.skip(phase === 'before'); mkdirSync(root, {recursive:true});
  await page.clock.setFixedTime(new Date(GENERATED_AT)); await installFixtures(page);
  const assets = await installRealMapAssets(page);
  let release!: () => void, requested = 0;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/map-data/world-countries.geojson', async route => {
    requested++; await held; await route.continue();
  });
  try {
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&center=-120,37&zoom=3&time=all&layers=earthquakes-volcanoes');
    const host = page.locator('[data-map-renderer-ready]');
    await expect.poll(() => requested).toBeGreaterThan(0);
    await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl', {timeout:10_000});
    await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready');
    release();
    const point = await host.evaluate(el => {
      const p = (el as any).__polymonitorProjectGeoPoint(-122.1,37.4), box = el.getBoundingClientRect();
      return {x:box.x+p.x,y:box.y+p.y};
    });
    await expect.poll(async () => {
      await page.mouse.click(point.x, point.y);
      return page.locator('.wm-world-event-list.is-open,.wm-event-inspector').isVisible();
    }).toBe(true);
    await host.screenshot({path:resolve(root,'optional-country-ready-picking.png')});
    writeFileSync(resolve(root,'optional-country-readiness.json'), JSON.stringify({requested,renderer:'webgl',
      sequence:['optional geometry held','primary frame and Deck ready','optional geometry released','real event picking']}));
  } finally { release(); await page.goto('about:blank'); await page.unrouteAll({behavior:'ignoreErrors'}); await assets.dispose(); }
});

test('initial world fit does not wait for optional geometry or override saved cameras', async ({page}) => {
  test.skip(phase === 'before'); mkdirSync(root, {recursive:true});
  await page.setViewportSize({width:1536,height:1000});
  await page.clock.setFixedTime(new Date(GENERATED_AT)); await installFixtures(page);
  const assets = await installRealMapAssets(page);
  let release!: () => void, requested = 0;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/map-data/world-countries.geojson', async route => {
    requested++; await held; await route.continue();
  });
  try {
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles');
    const host = page.locator('[data-map-renderer-ready]');
    await expect.poll(() => requested).toBeGreaterThan(0);
    await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl');
    const worldFitError = () => host.evaluate((el: any) => {
      const west = el.__polymonitorProjectGeoPoint(-180, 0);
      const east = el.__polymonitorProjectGeoPoint(180, 0);
      const mercator = (lat: number) => (1 - Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) / Math.PI) / 2;
      const expectedWidth = Math.max(el.clientWidth, el.clientHeight,
        Math.min(el.clientWidth - 48, (el.clientHeight - 48) / (mercator(-56) - mercator(72))));
      return Math.abs(east.x - west.x - expectedWidth);
    });
    await expect.poll(worldFitError).toBeLessThan(3);
    await host.screenshot({path:resolve(root,'world-fit-before-optional-load.png')});
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&center=12,35&zoom=3');
    await expect(host).toHaveAttribute('data-map-renderer-ready', 'webgl');
    release(); await page.waitForTimeout(2000);
    expect(new URL(page.url()).searchParams.get('center')).toBe('12.0000,35.0000');
    expect(new URL(page.url()).searchParams.get('zoom')).toBe('3.00');
    writeFileSync(resolve(root,'initial-camera-readiness.json'), JSON.stringify({requested,
      fitBeforeOptionalLoad:true,explicitCameraPreserved:true,url:page.url()}));
  } finally { release(); await page.goto('about:blank'); await page.unrouteAll({behavior:'ignoreErrors'}); await assets.dispose(); }
});

for (const viewport of [{width:1536,height:1000},{width:2048,height:567},{width:390,height:844}]) {
  test(`default composition ${viewport.width}x${viewport.height}`, async ({page}) => {
    test.setTimeout(120_000); mkdirSync(root,{recursive:true});
    await page.setViewportSize(viewport); await page.clock.setFixedTime(new Date(GENERATED_AT));
    await installFixtures(page); const assets = await installRealMapAssets(page);
    const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
    try {
      await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles');
      const host=page.locator('[data-map-renderer-ready]');
      await expect(host).toBeVisible();await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(2000);
      const rect=await host.boundingBox();
      const state=await host.evaluate(el=>({renderer:(el as HTMLElement).dataset.mapRendererReady,basemap:(el as HTMLElement).dataset.mapBasemapState,canvases:el.querySelectorAll('canvas').length,url:location.href}));
      await page.screenshot({path:resolve(root,`default-${viewport.width}.png`)});
      writeFileSync(resolve(root,`default-${viewport.width}.json`),JSON.stringify({rect,state,errors},null,2));
      if(phase!=='before') {
        if(viewport.width===1536) expect(rect!.height).toBeGreaterThanOrEqual(680);
        await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');
        const stage = (await page.locator('.wm-map-stage').boundingBox())!;
        if(viewport.width===390) expect(stage.height).toBeGreaterThanOrEqual(420);
        expect(Math.abs(rect!.height - stage.height), '2D renderer must fit its visible stage; a 3D minimum height must not crop its controls').toBeLessThanOrEqual(1);
      }
      expect(errors).toEqual([]);
    } finally {await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
  });
}

test('actual context loss restores frame and picking; persistent failure recovers from SVG', async({page})=>{
  test.skip(phase==='before');test.setTimeout(150_000);mkdirSync(root,{recursive:true});
  await page.setViewportSize({width:1536,height:1000});await page.clock.setFixedTime(new Date(GENERATED_AT));
  await installFixtures(page);const assets=await installRealMapAssets(page);
  try {
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&center=-120,37&zoom=3&time=all&layers=earthquakes-volcanoes');
    const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');
    await host.evaluate(el=>{
      const canvas=el.querySelector<HTMLCanvasElement>('canvas.maplibregl-canvas')!;
      const ext=canvas.getContext('webgl2')!.getExtension('WEBGL_lose_context')!;
      (window as any).__v3Restore=()=>ext.restoreContext();ext.loseContext();
    });
    await page.waitForTimeout(1000);await page.evaluate(()=>(window as any).__v3Restore());await page.waitForTimeout(2000);
    await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');
    await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');
    await host.screenshot({path:resolve(root,'context-restored.png')});
    await host.dispatchEvent('polymonitor:map-renderer-failure');await expect(host).toHaveAttribute('data-map-renderer-ready','svg');
    await expect(host.locator('canvas')).toHaveCount(0);await host.screenshot({path:resolve(root,'context-svg.png')});
    await expect(host).toHaveAttribute('data-map-renderer-ready','webgl',{timeout:50_000});
    await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');
    const point=await host.evaluate((el:any)=>{const p=el.__polymonitorProjectGeoPoint(-122.1,37.4),r=el.getBoundingClientRect();return {x:p.x+r.x,y:p.y+r.y};});
    await page.mouse.click(point.x,point.y);
    await expect(page.locator('.wm-world-event-list.is-open,.wm-event-inspector')).toBeVisible();
    await host.screenshot({path:resolve(root,'context-recovered-picking.png')});
    writeFileSync(resolve(root,'context-cycle.json'),JSON.stringify({originalContext:'restored',fallback:'svg',recovered:'webgl',picking:'visible selection',url:page.url()}));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

test('slow vector tiles keep their loaded index and paint before the bounded grace expires',async({page})=>{
  test.skip(phase==='before');test.setTimeout(90_000);mkdirSync(root,{recursive:true});
  await page.clock.setFixedTime(new Date(GENERATED_AT));await installFixtures(page);
  const assets=await installRealMapAssets(page);let release!:()=>void,heldRequests=0;
  const {bytesToHeader}=await import('pmtiles');
  const tileDataStart=page.waitForResponse(response=>response.url().includes('/map-tiles/')
    && (response.request().headers().range||'').startsWith('bytes=0-'))
    .then(async response=>bytesToHeader(Uint8Array.from(await response.body()).buffer).tileDataOffset);
  const held=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/map-tiles/**',async route=>{
    const range=route.request().headers().range||'';
    // PMTiles metadata is a separate nonzero range inside the archive header.
    // Let metadata/directories load; delay only the actual vector tile payloads.
    if(!range.startsWith('bytes=0-') && Number(range.match(/^bytes=(\d+)/)?.[1])>=await tileDataStart){
      heldRequests++;await held;
    }
    await route.fallback();
  });
  try {
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&center=0,20&zoom=2&layers=earthquakes-volcanoes');
    const host=page.locator('.wm-weather-deck-basemap');
    await expect.poll(()=>heldRequests).toBeGreaterThan(0);
    await page.waitForTimeout(12_000);
    await expect(host).toHaveAttribute('data-map-basemap-state','initializing');
    release();await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');
    await host.screenshot({path:resolve(root,'slow-tiles-kept-primary.png')});
    writeFileSync(resolve(root,'slow-tiles-grace.json'),JSON.stringify({heldRequests,heldMs:12000,painted:'primary-ready'}));
  }finally{release();await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

for (const scene of [
  {name:'world', camera:'center=0,20&zoom=1.5'},
  {name:'city', camera:'center=-0.1257,51.5085&zoom=12'},
]) test(`failed PMTiles recovers at ${scene.name} zoom without losing camera or events`,async({page})=>{
  test.skip(phase==='before');test.setTimeout(120_000);mkdirSync(root,{recursive:true});
  await page.setViewportSize({width:1536,height:1000});await page.clock.setFixedTime(new Date(GENERATED_AT));
  await installFixtures(page);const assets=await installRealMapAssets(page);let blocked=true;
  await page.route('**/map-tiles/**',async route=>{if(blocked)await route.fulfill({status:503,body:'Controlled PMTiles fault'});else await route.fallback();});
  try{
    await gotoMapScene(page, `/?view=2d&mapPerf=1&basemap=pmtiles&${scene.camera}&time=all&layers=earthquakes-volcanoes`);
    const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-basemap-state','local-fallback-ready',{timeout:30_000});
    const camera=new URL(page.url()).searchParams.get('center');const records=await page.locator('.wm-world-event-list-toggle strong').innerText();await host.screenshot({path:resolve(root,`range-local-fallback-${scene.name}.png`)});
    blocked=false;await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready',{timeout:50_000});
    expect(new URL(page.url()).searchParams.get('center')).toBe(camera);await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText(records);
    await host.screenshot({path:resolve(root,`range-recovered-${scene.name}.png`)});
    writeFileSync(resolve(root,`range-cycle-${scene.name}.json`),JSON.stringify({fault:'503',fallback:'local-fallback-ready',recovered:'primary-ready',camera,records}));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

test('aviation uses resized bounds and represents all valid returned records',async({page})=>{
  test.skip(phase==='before');test.setTimeout(90_000);mkdirSync(root,{recursive:true});
  await page.setViewportSize({width:500,height:1000});await page.clock.setFixedTime(new Date(GENERATED_AT));
  await installFixtures(page);const assets=await installRealMapAssets(page);const requests:any[]=[];
  await page.route('**/wm-api/runtime/transport/aviation-viewport?**',async route=>{
    const u=new URL(route.request().url()),bbox=u.searchParams.get('bbox')!.split(',').map(Number);
    const entry={bbox,at:Date.now(),aborted:false};requests.push(entry);
    const [w,s,e,n]=bbox;const aircraft=Array.from({length:180},(_,i)=>({id:`plane:${i}`,icao24:`p${i}`,callsign:`V3 ${i}`,lon:w+(e-w)*((i%18)+.5)/18,lat:s+(n-s)*(Math.floor(i/18)+.5)/10,updatedAt:GENERATED_AT,source:'Controlled ADSB fixture'}));
    try{await route.fulfill({json:{schemaVersion:'aviation-viewport.v1',generatedAt:GENERATED_AT,status:'ok',bbox,zoom:3,aircraft,aircraftCount:180,availableAircraftCount:180,source:'Controlled ADSB fixture',coverage:{complete:true}}});}catch{entry.aborted=true;}
  });
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&center=-98,39&zoom=3&time=all&layers=air-routes&air=all&presentation=records');
    const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');
    await expect(page.locator('[data-aviation-phase]')).toHaveAttribute('data-aviation-phase','READY');
    await expect(page.locator('.wm-aviation-lens-stats')).toContainText('180');
    const before=requests.at(-1).bbox;await page.setViewportSize({width:800,height:1000});
    await expect.poll(()=>requests.length).toBeGreaterThan(1);expect(requests.at(-1).bbox).not.toEqual(before);
    await page.locator('.wm-aviation-lens').screenshot({path:resolve(root,'aviation-all.png')});
    await page.getByRole('button',{name:'Hide aviation layer'}).click();const count=requests.length;await page.waitForTimeout(1500);expect(requests.length).toBe(count);
    writeFileSync(resolve(root,'aviation-bounds.json'),JSON.stringify({requests,returned:180,represented:180,offStopsRequests:true},null,2));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

// Evidence line A: exact frozen production payloads; no changed event fields.
for (const locale of ['en','zh']) test(`frozen real sources ${locale}: default composition and record access`,async({page,browser})=>{
  test.skip(!process.env.MAP_RECOVERY_INPUT_DIR, 'Requires a frozen real input receipt.');
  test.setTimeout(120_000);mkdirSync(root,{recursive:true});
  const {readFileSync}=await import('node:fs');const input=process.env.MAP_RECOVERY_INPUT_DIR!;
  const receipt=JSON.parse(readFileSync(resolve(input,'receipt.json'),'utf8'));
  await page.setViewportSize({width:1536,height:1000});await page.clock.setFixedTime(new Date(receipt.capturedAt));
  await installFixtures(page);const assets=await installRealMapAssets(page);
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**',async route=>{
    const key=new URL(route.request().url()).searchParams.get('source')!;
    await route.fulfill({contentType:'application/json',body:readFileSync(resolve(input,`${key}.json`))});
  });
  await page.route('**/wm-api/runtime/transport/global-shipping**',route=>route.fulfill({contentType:'application/json',body:readFileSync(resolve(input,'transport.json'))}));
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&center=0,20&zoom=1.25&time=7d&layers=earthquakes-volcanoes,weather-alerts,wildfires,extreme-temperature,climate-anomalies');
    await page.locator('.wm-language-switch select').selectOption(locale);
    const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');
    await expect.poll(async()=>Number(await page.locator('.wm-world-event-list-toggle strong').innerText())).toBeGreaterThan(300);
    await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(3000);
    const layout=await host.boundingBox();
    const presentation=await host.evaluate((el:any)=>el.__polymonitorMapPresentation?.(true));
    await page.screenshot({path:resolve(root,`real-${locale}-default.png`)});
    await page.locator('.wm-world-event-list-toggle').click();
    await expect(page.locator('.wm-world-event-list-scroll li button').first()).toBeVisible();
    await page.locator('.wm-world-event-list-scroll li button').first().click();
    await expect(page.locator('#wm-event-inspector-title')).toBeVisible();
    await page.screenshot({path:resolve(root,`real-${locale}-report.png`)});
    writeFileSync(resolve(root,`real-${locale}.json`),JSON.stringify({inputReceipt:receipt,layout,browser:browser.version(),presentation,sourceBadges:await page.locator('.wm-map-source-statuses').innerText(),url:page.url()},null,2));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

test('slow renderer download is temporary SVG, late same-generation module recovers and preserves selection',async({page})=>{
  test.skip(phase==='before');test.setTimeout(90_000);mkdirSync(root,{recursive:true});
  await page.setViewportSize({width:1536,height:1000});await page.clock.setFixedTime(new Date(GENERATED_AT));
  await installFixtures(page);const assets=await installRealMapAssets(page);
  await page.route(/(?:\/src\/features\/world-event-map\/renderer\/DeckMapRenderer\.ts|\/assets\/DeckMapRenderer-[^/]+\.js)(?:\?|$)/,async route=>{await new Promise(r=>setTimeout(r,9000));await route.continue();});
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&center=-120,37&zoom=3&time=all&layers=earthquakes-volcanoes');
    const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-renderer-ready','svg',{timeout:15_000});
    await host.screenshot({path:resolve(root,'slow-download-svg.png')});
    await expect(host).toHaveAttribute('data-map-renderer-ready','webgl',{timeout:30_000});
    await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');
    await expect(host.locator('canvas.maplibregl-canvas')).toHaveCount(1);
    await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText('8');
    await host.screenshot({path:resolve(root,'slow-download-recovered.png')});
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

test('a single isolated layer remains quarantined for the same data and recovers on a validated revision',async({page})=>{
  test.skip(phase==='before');test.setTimeout(90_000);mkdirSync(root,{recursive:true});
  const {sourceEvents,mapResponse}=await import('./fixtures/world-event-map');let revised=false;
  await page.setViewportSize({width:1536,height:1000});await page.clock.setFixedTime(new Date(GENERATED_AT));
  await installFixtures(page);const assets=await installRealMapAssets(page);
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**',route=>{
    const key=new URL(route.request().url()).searchParams.get('source')!;
    const events=sourceEvents[key]||[];
    return route.fulfill({json:mapResponse(key,revised&&key==='usgs'?events.map(e=>({...e,title:`Validated revision: ${e.title}`,revision:{...(e.revision as object),revisionAt:'2026-08-26T02:59:59Z'}})):events)});
  });
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&center=-120,37&zoom=3&time=all&layers=earthquakes-volcanoes');
    const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');
    await page.waitForTimeout(1000);
    const isolated=await host.evaluate((el:any)=>el.__polymonitorIsolateLayer());expect(isolated).toBeTruthy();
    await expect(page.locator('.wm-banner.notice')).toContainText('ISOLATED');
    await host.screenshot({path:resolve(root,'layer-isolated.png')});
    // A camera change produces different screen clusters, not a source revision.
    await page.locator('.wm-map-controls button').first().click();await page.waitForTimeout(600);
    expect(await host.evaluate((el:any)=>el.__polymonitorLayerFuses())).toContain(isolated);
    revised=true;
    const checkbox=page.locator('.wm-layer-row').filter({hasText:'Earthquakes'}).getByRole('checkbox');
    await checkbox.uncheck();await checkbox.check();
    await page.evaluate(() => window.dispatchEvent(new Event('online')));
    await expect.poll(()=>host.evaluate((el:any)=>el.__polymonitorLayerFuses())).toEqual([]);
    await expect(page.locator('.wm-banner.notice')).toHaveCount(0);await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');
    await host.screenshot({path:resolve(root,'layer-recovered.png')});
    writeFileSync(resolve(root,'layer-cycle.json'),JSON.stringify({isolated,sameVersionOnZoom:'quarantined',validatedRevision:'recovered',wholeRenderer:'webgl'}));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

test('date-line halves, corner aircraft, late responses and off/empty/partial/failure recovery',async({page})=>{
  test.skip(phase==='before');test.setTimeout(120_000);mkdirSync(root,{recursive:true});
  await page.setViewportSize({width:1536,height:1000});await page.clock.install({time:new Date(GENERATED_AT)});
  await installFixtures(page);const assets=await installRealMapAssets(page);
  const requests:any[]=[];let mode='ready',revision=0;
  await page.route('**/wm-api/runtime/transport/aviation-viewport?**',async route=>{
    const u=new URL(route.request().url()),bbox=u.searchParams.get('bbox')!.split(',').map(Number),seq=++revision;
    const [w,s,e,n]=bbox;requests.push({bbox,seq,mode});const slow=seq<=2;
    const unavailableHalf=mode==='hemisphere'&&w<0;const aircraft=mode==='empty'||unavailableHalf?[]:[[w+.02,s+.02],[e-.02,s+.02],[w+.02,n-.02],[e-.02,n-.02]].map(([lon,lat],i)=>({id:`${w<0?'west':'east'}:${i}`,icao24:`${w<0?'west':'east'}:${i}`,callsign:`${slow?'OLD':'CURRENT'} ${w<0?'west':'east'} ${i}`,lon,lat,source:'Controlled corner observation',observedAt:GENERATED_AT,updatedAt:GENERATED_AT}));
    if(slow)await new Promise(r=>setTimeout(r,2500));
    try {if(mode==='failure')await route.fulfill({status:503,body:'Controlled aviation outage'});else await route.fulfill({json:{schemaVersion:'aviation-viewport.v1',generatedAt:GENERATED_AT,status:unavailableHalf?'unavailable':mode==='partial'?'partial':aircraft.length?'ok':'empty',aircraft,aircraftCount:aircraft.length,availableAircraftCount:aircraft.length,coverage:{complete:mode!=='partial',mode:'bounded sector query'},source:'Controlled corner observation',bbox,zoom:3}});}catch{/* Superseded HTTP is explicitly cancelled. */}
  });
  const resume=()=>page.evaluate(()=>window.dispatchEvent(new Event('online')));
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&center=179,20&zoom=3&time=all&layers=air-routes&air=all&presentation=records');
    const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');
    await expect.poll(()=>requests.length).toBeGreaterThanOrEqual(2);
    await page.setViewportSize({width:1536,height:850});await expect.poll(()=>requests.length).toBeGreaterThan(2);
    await expect(page.locator('[data-aviation-phase]')).toHaveAttribute('data-aviation-phase','READY');
    await page.waitForTimeout(2800);
    expect(requests.every(r=>r.bbox[2]-r.bbox[0]<180)).toBe(true);expect(requests.some(r=>r.bbox[0]<0)).toBe(true);expect(requests.some(r=>r.bbox[0]>0)).toBe(true);
    await page.locator('.wm-world-event-list-toggle').click();await expect(page.locator('.wm-world-event-list-scroll')).toContainText('CURRENT');await expect(page.locator('.wm-world-event-list-scroll')).not.toContainText('OLD');
    // Every returned corner has record access even if icon placement needs a cluster.
    for(const side of ['east','west'])for(let i=0;i<4;i++){
      await page.locator('#wm-event-list-search').fill(`CURRENT ${side} ${i}`);
      await expect(page.locator('.wm-world-event-list-scroll')).toContainText(`CURRENT ${side} ${i}`);
    }
    await page.locator('#wm-event-list-search').fill('');
    await page.locator('.wm-world-event-list-close').click();await host.screenshot({path:resolve(root,'aviation-dateline-corners.png')});
    mode='partial';await resume();await expect(page.locator('[data-aviation-phase]')).toHaveAttribute('data-aviation-phase','PARTIAL');
    const beforeZoom=Number(new URL(page.url()).searchParams.get('zoom')),beforeRequests=requests.length;
    await page.getByRole('button',{name:'Zoom in to reduce query coverage gaps'}).click();
    await expect.poll(()=>Number(new URL(page.url()).searchParams.get('zoom'))).toBeGreaterThan(beforeZoom);
    await expect.poll(()=>requests.length).toBeGreaterThan(beforeRequests);

    mode='hemisphere';await resume();await expect(page.locator('[data-aviation-phase]')).toHaveAttribute('data-aviation-phase','PARTIAL');
    await expect(page.locator('.wm-aviation-lens')).toContainText('4 / 4');
    mode='failure';await resume();await expect(page.locator('[data-aviation-phase]')).toHaveAttribute('data-aviation-phase','STALE');await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');
    await page.clock.fastForward(121_000);await expect(page.locator('[data-aviation-phase]')).toHaveAttribute('data-aviation-phase','UNAVAILABLE');
    mode='empty';await resume();await expect(page.locator('[data-aviation-phase]')).toHaveAttribute('data-aviation-phase','EMPTY');
    mode='ready';await resume();await expect(page.locator('[data-aviation-phase]')).toHaveAttribute('data-aviation-phase','READY');
    await page.getByRole('button',{name:'Hide aviation layer'}).click();const count=requests.length;await page.waitForTimeout(1200);expect(requests.length).toBe(count);
    await page.goto('about:blank');await page.waitForTimeout(1000);expect(requests.length).toBe(count);
    writeFileSync(resolve(root,'aviation-state-cycle.json'),JSON.stringify({requests,lateResults:'discarded',cornerRecords:8,states:['READY','PARTIAL','PARTIAL (one failed date-line half)','STALE','UNAVAILABLE (retention expired)','EMPTY','READY','OFF'],unmountedRequests:0},null,2));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

test('overview and records conserve identities; invalid feature and source offline recover independently',async({page})=>{
  test.skip(phase==='before');test.setTimeout(90_000);mkdirSync(root,{recursive:true});
  const {hazard,mapResponse}=await import('./fixtures/world-event-map');let fault=false,bad=true;let requests=0;
  const ordinary=Array.from({length:100},(_,i)=>hazard({id:`ordinary:${i}`,title:`Ordinary ${i}`,hazardKind:'earthquake',metrics:{kind:'earthquake',magnitude:2},severity:'info',geometry:{type:'Point',coordinates:[-122.1,37.4]}}));
  const important=hazard({id:'critical:one',title:'Protected critical observation',hazardKind:'earthquake',metrics:{kind:'earthquake',magnitude:6.4},severity:'critical',geometry:{type:'Point',coordinates:[-122.1,37.4]}});
  await page.setViewportSize({width:1536,height:1000});await page.clock.setFixedTime(new Date(GENERATED_AT));await installFixtures(page);const assets=await installRealMapAssets(page);
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**',async route=>{
    const source=new URL(route.request().url()).searchParams.get('source')!;if(source==='usgs')requests++;
    if(fault&&source==='usgs')return route.fulfill({status:503,body:'Controlled source outage'});
    return route.fulfill({json:mapResponse(source,source==='usgs'?[...ordinary,important,hazard({id:'invalid:one',title:'Feature that becomes valid',hazardKind:'earthquake',metrics:{kind:'earthquake',magnitude:4},geometry:{type:'Point',coordinates:bad?[999,999]:[-123,38]}})]:[])});
  });
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&center=-122,37&zoom=3&time=all&layers=earthquakes-volcanoes');
    const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');
    await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText('101');
    const audit=await host.evaluate((el:any)=>el.__polymonitorMapPresentation(true));expect(Object.keys(audit.membership)).toHaveLength(101);expect(Object.values(audit.membership)).not.toContain('DUPLICATE');
    await host.screenshot({path:resolve(root,'protected-overview.png')});await page.getByRole('button',{name:'Records',exact:true}).click();
    await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText('101');await host.screenshot({path:resolve(root,'protected-records.png')});
    fault=true;await page.evaluate(()=>window.dispatchEvent(new Event('online')));await expect(page.locator('.wm-map-source-status').filter({hasText:'USGS'}).first()).toHaveClass(/is-degraded/);await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');
    await page.context().setOffline(true);const before=requests;await page.waitForTimeout(1500);expect(requests).toBe(before);
    fault=false;bad=false;await page.context().setOffline(false);await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText('102');
    await expect(page.locator('.wm-map-source-status').filter({hasText:'USGS'}).first()).toHaveClass(/is-ok/);
    await host.screenshot({path:resolve(root,'source-feature-recovered.png')});
    writeFileSync(resolve(root,'source-feature-cycle.json'),JSON.stringify({audit,normal:101,invalidFeature:'isolated',fault:'503 / stale',offlineRequests:0,recovered:102,renderer:'webgl',requests},null,2));
  }finally{await page.context().setOffline(false);await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

for(const viewport of [{width:1536,height:768},{width:2048,height:1004}])test(`focus and explicit lightweight ${viewport.width}`,async({page})=>{
  test.skip(phase==='before');test.setTimeout(90_000);mkdirSync(root,{recursive:true});
  await page.setViewportSize(viewport);await page.clock.setFixedTime(new Date(GENERATED_AT));await installFixtures(page);const assets=await installRealMapAssets(page);
  try{
    await gotoMapScene(page, '/?view=2d&renderer=svg&time=all&layers=earthquakes-volcanoes&mapPerf=1');const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-renderer-ready','svg');await expect(host.locator('canvas')).toHaveCount(0);
    await page.locator('.wm-map-focus-toggle').click();await expect(page.locator('.wm-map-stage')).toHaveClass(/is-map-focused/);await host.screenshot({path:resolve(root,`focus-svg-${viewport.width}.png`)});await page.keyboard.press('Escape');await expect(page.locator('.wm-map-stage')).not.toHaveClass(/is-map-focused/);
    await page.locator('.wm-world-event-list-toggle').click();await page.locator('.wm-world-event-list-scroll button').first().focus();await page.keyboard.press('Enter');await expect(page.locator('.wm-event-inspector')).toBeVisible();await page.keyboard.press('Escape');
    await page.waitForTimeout(1000);await expect(host).toHaveAttribute('data-map-renderer-ready','svg');
    writeFileSync(resolve(root,`focus-svg-${viewport.width}.json`),JSON.stringify({rect:await host.boundingBox(),explicitRenderer:'svg',keyboardDetails:true,automaticWebGLPromotion:false}));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

for(const dpr of [1,2])for(const zoom of [1,1.25])test(`full raster resolution DPR${dpr} equivalent zoom ${zoom*100}% with touch and keyboard`,async({browser})=>{
  test.skip(phase==='before');test.setTimeout(90_000);mkdirSync(root,{recursive:true});
  // Model the viewport/DPR combination; the following persistent-profile case
  // separately verifies Chromium native tab zoom.
  const context=await browser.newContext({viewport:{width:Math.round(1536/zoom),height:Math.round(1000/zoom)},deviceScaleFactor:dpr*zoom,hasTouch:true,reducedMotion:'reduce',serviceWorkers:'block'});
  const page=await context.newPage();await page.clock.setFixedTime(new Date(GENERATED_AT));await installFixtures(page);const assets=await installRealMapAssets(page);
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&time=all&layers=earthquakes-volcanoes');const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');
    const canvas=await host.locator('canvas.maplibregl-canvas').evaluate((c:HTMLCanvasElement)=>({width:c.width,height:c.height,cssWidth:c.clientWidth,cssHeight:c.clientHeight,dpr:devicePixelRatio}));
    expect(canvas.width).toBeGreaterThanOrEqual(Math.floor(canvas.cssWidth*canvas.dpr));expect(canvas.height).toBeGreaterThanOrEqual(Math.floor(canvas.cssHeight*canvas.dpr));
    await page.locator('.wm-world-event-list-toggle').tap();const first=page.locator('.wm-world-event-list-scroll li button').first();await first.focus();await page.keyboard.press('Enter');await expect(page.locator('.wm-event-inspector')).toBeVisible();
    await page.locator('.wm-language-switch select').selectOption('zh');await page.evaluate(()=>document.fonts.ready);
    const family=await page.locator('.wm-event-inspector').evaluate(el=>getComputedStyle(el).fontFamily);expect(family).toContain('Noto Sans SC Variable');
    await page.screenshot({path:resolve(root,`accessibility-dpr${dpr}-zoom${zoom}.png`)});
    writeFileSync(resolve(root,`accessibility-dpr${dpr}-zoom${zoom}.json`),JSON.stringify({canvas,family,keyboardSelection:true,touchDrawer:true,reducedMotion:true}));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();await context.close();}
});

test('separate stable recovery episodes reset the budget; consecutive faults stop automatic recreation',async({page})=>{
  test.skip(phase==='before');test.setTimeout(180_000);mkdirSync(root,{recursive:true});
  await page.setViewportSize({width:1536,height:1000});await page.clock.install({time:new Date(GENERATED_AT)});await installFixtures(page);const assets=await installRealMapAssets(page);
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&time=all&layers=earthquakes-volcanoes');const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');
    const cycles=[];
    for(let episode=0;episode<2;episode++){
      await host.dispatchEvent('polymonitor:map-renderer-failure');await expect(host).toHaveAttribute('data-map-renderer-ready','svg');
      await page.getByRole('button',{name:/Retry detailed map/i}).click();await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');
      await page.clock.fastForward(61_000);cycles.push({episode,stableMs:61000,recovered:'webgl'});
    }
    for(let fault=0;fault<2;fault++){
      await host.dispatchEvent('polymonitor:map-renderer-failure');await expect(host).toHaveAttribute('data-map-renderer-ready','svg');await page.getByRole('button',{name:/Retry detailed map/i}).click();await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');
    }
    await host.dispatchEvent('polymonitor:map-renderer-failure');await expect(host).toHaveAttribute('data-map-renderer-ready','svg');await page.getByRole('button',{name:/Retry detailed map/i}).click();await expect(page.locator('.wm-map-renderer-retry')).toHaveAttribute('title',/budget is exhausted/);
    await page.clock.fastForward(130_000);await expect(host).toHaveAttribute('data-map-renderer-ready','svg');
    writeFileSync(resolve(root,'recovery-episodes.json'),JSON.stringify({cycles,consecutiveFaults:'budget exhausted / stable SVG',clock:'controlled scheduler advancement; actual renderer mount and paint'}));await host.screenshot({path:resolve(root,'recovery-budget-cooldown.png')});
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

test('unavailable GPU stays lightweight with reports and no automatic GPU recreation',async({page})=>{
  test.skip(phase==='before');test.setTimeout(90_000);mkdirSync(root,{recursive:true});
  await page.addInitScript(()=>{const get=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(kind:any,...args:any[]){if(String(kind).startsWith('webgl'))return null;return (get as any).call(this,kind,...args);} as any;});
  await page.clock.install({time:new Date(GENERATED_AT)});await installFixtures(page);const assets=await installRealMapAssets(page);
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&time=all&layers=earthquakes-volcanoes');const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-renderer-ready','svg');
    await page.locator('.wm-world-event-list-toggle').click();await page.locator('.wm-world-event-list-scroll li button').first().click();await expect(page.locator('.wm-event-inspector')).toBeVisible();
    await page.clock.fastForward(180_000);await expect(host).toHaveAttribute('data-map-renderer-ready','svg');await expect(host.locator('canvas')).toHaveCount(0);await host.screenshot({path:resolve(root,'no-gpu-report.png')});
    writeFileSync(resolve(root,'no-gpu.json'),JSON.stringify({capability:'WebGL unavailable',renderer:'svg',recordAccess:true,automaticGPUCreation:false}));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

test('provider authorization and throttling are explicit, bounded and recover on the authorized next probe',async({page})=>{
  test.skip(phase==='before');test.setTimeout(120_000);mkdirSync(root,{recursive:true});
  const {sourceEvents,mapResponse}=await import('./fixtures/world-event-map');await page.clock.install({time:new Date(GENERATED_AT)});await installFixtures(page);const assets=await installRealMapAssets(page);
  let response: 'normal'|'auth'|'throttle'='normal';let requests=0;
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**',async route=>{const key=new URL(route.request().url()).searchParams.get('source')!;if(key!=='usgs'){await route.fallback();return;}requests++;
    if(response==='auth')await route.fulfill({status:403,body:'Controlled credentials fault'});else if(response==='throttle')await route.fulfill({status:429,headers:{'Retry-After':'120'},body:'Controlled throttle'});else await route.fulfill({json:mapResponse(key,sourceEvents[key])});});
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&time=all&layers=earthquakes-volcanoes');const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');await expect(page.locator('.wm-map-source-status').filter({hasText:'USGS'}).first()).toHaveClass(/is-ok/);
    response='auth';await page.evaluate(()=>window.dispatchEvent(new Event('online')));await expect(page.locator('.wm-map-source-status').filter({hasText:'USGS'}).first()).toHaveClass(/is-degraded/);const blockedCount=requests;await page.clock.fastForward(100_000);expect(requests).toBe(blockedCount);
    response='normal';await page.evaluate(()=>window.dispatchEvent(new Event('online')));await expect(page.locator('.wm-map-source-status').filter({hasText:'USGS'}).first()).toHaveClass(/is-ok/);
    response='throttle';await page.evaluate(()=>window.dispatchEvent(new Event('online')));await expect(page.locator('.wm-map-source-status').filter({hasText:'USGS'}).first()).toHaveClass(/is-degraded/);const throttledCount=requests;await page.clock.fastForward(110_000);expect(requests).toBe(throttledCount);response='normal';await page.clock.fastForward(20_000);await expect(page.locator('.wm-map-source-status').filter({hasText:'USGS'}).first()).toHaveClass(/is-ok/);
    await host.screenshot({path:resolve(root,'auth-throttle-recovered.png')});writeFileSync(resolve(root,'auth-throttle-cycle.json'),JSON.stringify({normal:true,auth:'403 / retained stale / no polls',throttle:'429 / Retry-After120s / no early poll',recovered:'source ok / renderer primary',requests}));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

test('one missing PMTiles leaf stays on the GPU and recovers without replacing the renderer',async({page})=>{
  test.skip(phase==='before');test.setTimeout(100_000);mkdirSync(root,{recursive:true});await page.setViewportSize({width:1536,height:1000});await page.clock.setFixedTime(new Date(GENERATED_AT));await installFixtures(page);const assets=await installRealMapAssets(page);
  let armed=false,broken:string|null=null,clear=false;const failed:string[]=[];
  await page.route('**/map-tiles/**',async route=>{const range=route.request().headers().range||'';
    if(armed&&!clear&&(!broken||broken===range)){broken=range;failed.push(range);await route.fulfill({status:503,body:'Controlled single leaf failure'});}else await route.fallback();});
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&time=all&layers=earthquakes-volcanoes');const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');
    const canvas=host.locator('canvas.maplibregl-canvas');await canvas.evaluate(el=>el.setAttribute('data-v3-original-canvas','true'));
    await host.screenshot({path:resolve(root,'leaf-normal.png')});armed=true;await host.evaluate((el:any)=>el.__polymonitorMapCamera([120,20],5));
    await expect(page.locator('.wm-weather-deck-status')).toContainText('PARTIAL BASEMAP',{timeout:20_000});await expect(page.locator('.wm-weather-deck-status')).toHaveAttribute('title',/Missing base tiles/);await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');await expect(canvas).toHaveAttribute('data-v3-original-canvas','true');await host.screenshot({path:resolve(root,'leaf-partial.png')});
    const camera=new URL(page.url()).searchParams.get('center');clear=true;await expect(page.locator('.wm-weather-deck-status')).toBeHidden({timeout:70_000});await expect(canvas).toHaveAttribute('data-v3-original-canvas','true');expect(new URL(page.url()).searchParams.get('center')).toBe(camera);
    await host.screenshot({path:resolve(root,'leaf-recovered.png')});writeFileSync(resolve(root,'leaf-cycle.json'),JSON.stringify({failedRange:broken,failedRequests:failed.length,partial:'same GPU / explicit missing tile',recovered:'same canvas / same camera',camera}));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

test('native Chromium tab zoom 125 percent retains full raster resolution and usable controls',async()=>{
  test.skip(phase==='before');test.setTimeout(90_000);mkdirSync(root,{recursive:true});
  const {chromium}=await import('@playwright/test');const {mkdtempSync,rmSync}=await import('node:fs');const {tmpdir}=await import('node:os');
  const temporary=mkdtempSync(resolve(tmpdir(),'polymonitor-v3-zoom-'));mkdirSync(resolve(temporary,'Default'));
  // Reuse the native profile zoom mechanism in map-alignment.spec.ts. This
  // changes Chromium's tab zoom, not page CSS or emulated device metrics.
  writeFileSync(resolve(temporary,'Default/Preferences'),JSON.stringify({partition:{default_zoom_level:{x:Math.log(1.25)/Math.log(1.2)}}}));
  let context:Awaited<ReturnType<typeof chromium.launchPersistentContext>>|undefined;
  try{
    context=await chromium.launchPersistentContext(temporary,{channel:'chrome',headless:true,viewport:null,deviceScaleFactor:undefined,serviceWorkers:'block',args:['--window-size=1920,1080','--force-device-scale-factor=2','--disable-partial-raster','--use-angle=vulkan','--enable-features=Vulkan']});
    const page=context.pages()[0];await page.clock.setFixedTime(new Date(GENERATED_AT));await installFixtures(page);const assets=await installRealMapAssets(page);
    try{
      await gotoMapScene(page, 'http://127.0.0.1:4174/?view=2d&mapPerf=1&basemap=pmtiles&time=all&layers=earthquakes-volcanoes');const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');
      const raster=await host.locator('canvas.maplibregl-canvas').evaluate((c:HTMLCanvasElement)=>({width:c.width,height:c.height,cssWidth:c.clientWidth,cssHeight:c.clientHeight,dpr:devicePixelRatio,innerWidth,outerWidth,visualScale:visualViewport!.scale}));
      expect(raster.outerWidth/raster.innerWidth).toBe(1.25);expect(raster.dpr).toBe(2.5);expect(raster.visualScale).toBe(1);
      expect(raster.width).toBeGreaterThanOrEqual(Math.floor(raster.cssWidth*raster.dpr));
      await page.locator('.wm-world-event-list-toggle').click();await page.locator('.wm-world-event-list-scroll li button').first().click();await expect(page.locator('.wm-event-inspector')).toBeVisible();
      await page.screenshot({path:resolve(root,'native-tab-zoom125.png')});writeFileSync(resolve(root,'native-tab-zoom125.json'),JSON.stringify({method:'Chromium native profile default_zoom_level',raster,realTabZoom:true,deviceScale:2}));
    }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
  }finally{await context?.close();rmSync(temporary,{recursive:true,force:true});}
});

test('fresh NWS catalog with delayed geometry keeps the same record and recovers its footprint',async({page})=>{
  test.skip(phase==='before');test.setTimeout(90_000);mkdirSync(root,{recursive:true});await page.clock.setFixedTime(new Date(GENERATED_AT));await installFixtures(page);const assets=await installRealMapAssets(page);
  const {hazard,mapResponse}=await import('./fixtures/world-event-map');let complete=false;const bodies:any[]=[];
  const original=hazard({id:'flood:nws:v3-cap',title:'Controlled NWS flood CAP revision',hazardKind:'flood',metrics:{kind:'weather-alert',event:'Flood Warning',severity:'Severe',certainty:'Observed',urgency:'Immediate'},geometry:null,locationPrecision:'unknown',sources:[{provider:'NWS',nativeId:'v3-cap',observedAt:GENERATED_AT,freshness:'live',status:'ok'}],properties:{mapEntity:'hazard-event',detailAvailable:true,geometryMode:'simplified',unresolvedZoneCount:1,resolvedZoneCount:0}});
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**',async route=>{const key=new URL(route.request().url()).searchParams.get('source')!;
    const event=complete?{...original,geometry:{type:'Polygon',coordinates:[[[-100,30],[-96,30],[-96,35],[-100,30]]]},locationPrecision:'region',properties:{...(original.properties as object),geometrySource:'nws-affected-zones',unresolvedZoneCount:0,resolvedZoneCount:1}}:original;
    const response=mapResponse(key,key==='nws'?[event]:[]);if(key==='nws')bodies.push(response);await route.fulfill({json:response});});
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&center=-98,32&zoom=4&time=all&layers=weather-alerts');const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText('1');
    const badge=page.locator('.wm-map-source-status').filter({has:page.locator('b',{hasText:/^NWS$/})});await expect(badge).toHaveClass(/is-partial/);await expect(badge).toContainText('PARTIAL');
    await page.locator('.wm-world-event-list-toggle').click();await expect(page.locator('.wm-world-event-list-scroll')).toContainText('Controlled NWS');await host.screenshot({path:resolve(root,'nws-core-partial.png')});await page.locator('.wm-world-event-list-close').click();
    complete=true;await page.evaluate(()=>window.dispatchEvent(new Event('online')));await expect(badge).toHaveClass(/is-ok/);await expect(badge).toContainText('FRESH');await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText('1');
    const audit=await host.evaluate((el:any)=>el.__polymonitorMapPresentation(true));expect(audit.membership['flood:nws:v3-cap']).toMatch(/^single/);
    const before=bodies[0].events[0],after=bodies.at(-1).events[0];expect(after.id).toBe(before.id);expect(after.updatedAt).toBe(before.updatedAt);expect(after.revision).toEqual(before.revision);
    await host.screenshot({path:resolve(root,'nws-geometry-recovered.png')});writeFileSync(resolve(root,'nws-geometry-cycle.json'),JSON.stringify({bodies,audit,sameRevision:true,sequence:['core ready','optional geometry partial / record accessible','same native ID / footprint recovered']},null,2));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

test('NWS authorization retention expires while polling is blocked and the catalog can recover',async({page})=>{
  test.skip(phase==='before');test.setTimeout(90_000);mkdirSync(root,{recursive:true});await page.clock.install({time:new Date(GENERATED_AT)});await installFixtures(page);const assets=await installRealMapAssets(page);
  const {hazard,mapResponse}=await import('./fixtures/world-event-map');let blocked=false,requests=0;
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**',async route=>{const key=new URL(route.request().url()).searchParams.get('source')!;if(key!=='nws'){await route.fulfill({json:mapResponse(key,[])});return;}requests++;
    if(blocked){await route.fulfill({status:403,body:'Controlled authorization failure'});return;}
    const response=mapResponse(key,[hazard({id:'weather:nws:expiry',title:'Controlled NWS retained record',hazardKind:'flood',metrics:{kind:'weather-alert',event:'Flood Warning',severity:'Severe',certainty:'Observed',urgency:'Immediate'},sources:[{provider:'NWS',nativeId:'expiry',observedAt:GENERATED_AT,freshness:'live',status:'ok'}]})]);response.sources[0].fetchedAt=await page.evaluate(()=>new Date().toISOString());await route.fulfill({json:response});
  });
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&time=all&layers=weather-alerts');const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');const badge=page.locator('.wm-map-source-status').filter({has:page.locator('b',{hasText:/^NWS$/})});await expect(badge).toHaveClass(/is-ok/);
    blocked=true;await page.evaluate(()=>window.dispatchEvent(new Event('online')));await expect(badge).toHaveClass(/is-degraded/);const blockedRequests=requests;
    await page.clock.fastForward(901_000);await expect(badge).toHaveClass(/is-error/);expect(requests).toBe(blockedRequests);await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText('0');await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');await host.screenshot({path:resolve(root,'nws-retention-expired.png')});
    blocked=false;await page.evaluate(()=>window.dispatchEvent(new Event('online')));await expect(badge).toHaveClass(/is-ok/);await expect(page.locator('.wm-world-event-list-toggle strong')).not.toHaveText('0');await host.screenshot({path:resolve(root,'nws-retention-recovered.png')});writeFileSync(resolve(root,'nws-retention-cycle.json'),JSON.stringify({deadlineMs:900000,blockedRequests,requests,sequence:['fresh','403 stale','expiry unavailable / no polls','fresh authorized probe'],renderer:'same GPU'}));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

test('one slow or malformed catalog preserves other sources, expires bounded stale data and recovers from valid empty',async({page})=>{
  test.skip(phase==='before');test.setTimeout(110_000);mkdirSync(root,{recursive:true});await page.clock.setFixedTime(new Date(GENERATED_AT));await installFixtures(page);const assets=await installRealMapAssets(page);
  const {hazard,sourceEvents,mapResponse}=await import('./fixtures/world-event-map');let mode='normal';const logs:any[]=[];
  const nwsEvent=hazard({id:'weather:nws:isolated',hazardKind:'flood',metrics:{kind:'weather-alert',event:'Flood Warning',severity:'Severe',certainty:'Observed',urgency:'Immediate'},title:'Controlled independent catalog',sources:[{provider:'NWS',nativeId:'isolated',observedAt:GENERATED_AT,freshness:'live',status:'ok'}]});
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**',async route=>{const key=new URL(route.request().url()).searchParams.get('source')!;logs.push({key,mode});
    if(key==='nws'&&mode==='timeout'){await page.waitForTimeout(6500);await route.fulfill({status:504,body:'Controlled absolute provider deadline'});}
    else if(key==='nws'&&mode==='schema')await route.fulfill({json:{schemaVersion:'broken',events:[]}});
    else await route.fulfill({json:mapResponse(key,key==='nws'?mode==='empty'?[]:[nwsEvent]:sourceEvents[key])});
  });
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&time=all&layers=earthquakes-volcanoes,weather-alerts');const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');const nwsBadge=page.locator('.wm-map-source-status').filter({has:page.locator('b',{hasText:/^NWS$/})});const usgsBadge=page.locator('.wm-map-source-status').filter({has:page.locator('b',{hasText:/^USGS$/})});await expect(nwsBadge).toHaveClass(/is-ok/);
    const count=await page.locator('.wm-world-event-list-toggle strong').innerText();
    for(const fault of ['timeout','schema']){mode=fault;await page.evaluate(()=>window.dispatchEvent(new Event('online')));await expect(nwsBadge).toContainText('STALE');await expect(usgsBadge).toHaveClass(/is-ok/);await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText(count);await host.screenshot({path:resolve(root,`nws-${fault}-isolated.png`)});}
    mode='empty';await page.evaluate(()=>window.dispatchEvent(new Event('online')));await expect(nwsBadge).toContainText('EMPTY');await expect(nwsBadge).toHaveClass(/is-ok/);await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText(String(Number(count)-1));
    mode='normal';await page.evaluate(()=>window.dispatchEvent(new Event('online')));await expect(nwsBadge).toContainText('FRESH');await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText(count);await host.screenshot({path:resolve(root,'nws-isolation-recovered.png')});writeFileSync(resolve(root,'nws-isolation-cycle.json'),JSON.stringify({logs,originalCount:count,sequence:['normal','6500ms timeout stale','malformed schema stale','valid empty','normal'],otherSources:'USGS ready / primary basemap unchanged'}));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});

test('all coincident important records remain reachable and selected identities leave exactly one primary representation',async({page})=>{
  test.skip(phase==='before');test.setTimeout(90_000);mkdirSync(root,{recursive:true});await page.setViewportSize({width:1536,height:1000});await page.clock.setFixedTime(new Date(GENERATED_AT));await installFixtures(page);const assets=await installRealMapAssets(page);
  const {hazard,mapResponse}=await import('./fixtures/world-event-map');const important=Array.from({length:95},(_,i)=>hazard({id:`critical:stack:${i}`,title:`Protected observation ${String(i).padStart(3,'0')}`,severity:'critical',geometry:{type:'Point',coordinates:[-122,37]}}));
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**',route=>{const key=new URL(route.request().url()).searchParams.get('source')!;return route.fulfill({json:mapResponse(key,key==='usgs'?important:[])});});
  try{
    await gotoMapScene(page, '/?view=2d&mapPerf=1&basemap=pmtiles&time=all&layers=earthquakes-volcanoes&center=-122,37&zoom=14');const host=page.locator('[data-map-renderer-ready]');await expect(host).toHaveAttribute('data-map-basemap-state','primary-ready');await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText('95');
    const original=await host.evaluate((el:any)=>el.__polymonitorMapPresentation(true));expect(Object.keys(original.membership)).toHaveLength(95);expect(Object.values(original.membership)).not.toContain('DUPLICATE');const box=(await host.boundingBox())!,point=await host.evaluate((el:any)=>el.__polymonitorProjectGeoPoint(-122,37));
    await page.mouse.click(box.x+point.x,box.y+point.y);await expect(page.getByRole('heading',{name:'Cluster members'})).toBeVisible();await expect(page.locator('.wm-world-event-list-summary')).toContainText('30 / 95');
    for(const loaded of [60,90,95]){await page.getByRole('button',{name:'Load 30 more',exact:true}).click();await expect(page.locator('.wm-world-event-list-summary')).toContainText(`${loaded} / 95`);}
    await expect(page.getByRole('button',{name:'Load 30 more',exact:true})).toHaveCount(0);
    await page.locator('.wm-world-event-list input[type=search]').fill('Protected observation 094');await page.getByRole('button',{name:/Protected observation 094/}).click();await expect(page.locator('.wm-event-inspector')).toContainText('Protected observation 094');
    const selected=await host.evaluate((el:any)=>el.__polymonitorMapPresentation(true));expect(selected.membership['critical:stack:94']).toMatch(/^single/);expect(Object.values(selected.membership)).not.toContain('DUPLICATE');await host.screenshot({path:resolve(root,'important-stack-selected-last.png')});
    await page.keyboard.press('Escape');await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText('95');writeFileSync(resolve(root,'important-stack.json'),JSON.stringify({input:95,reachable:95,original,selected,lastRecord:'critical:stack:94',silentTruncation:false},null,2));
  }finally{await page.goto('about:blank');await page.unrouteAll({behavior:'ignoreErrors'});await assets.dispose();}
});
