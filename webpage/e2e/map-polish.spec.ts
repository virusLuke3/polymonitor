import { gotoMapScene } from './fixtures/browser';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test, expect } from '@playwright/test';
import { GENERATED_AT, hazard, mapResponse, installFixtures, transportPayload } from './fixtures/world-event-map';
import { installRealMapAssets } from './fixtures/real-map-assets';

// Explicit test-only workload, never a production provider or fake live feed.
const phase = process.env.MAP_POLISH_PHASE;
const baseline = phase?.startsWith('before');
const v3 = phase?.includes('v3');
test.use({ trace: 'off' });
const output = resolve('artifacts/map-polish-round2', phase || 'unrequested');
test.skip(!phase, 'Opt-in fixed-input visual/performance comparison.');
for (const count of [v3 ? 750 : 713, 5000]) test(`polish ${count}: mixed dense events and continuous interaction`, async ({ page, browser }) => {
  test.setTimeout(180_000);
  mkdirSync(output, { recursive: true });
  await page.setViewportSize({ width: 2040, height: 1100 });
  await page.clock.setFixedTime(new Date(GENERATED_AT));
  await installFixtures(page);
  const events = Array.from({ length: count }, (_, i) => hazard({
    id: `polish-fixture:${i}`, title: `Test event ${String(i).padStart(4, '0')}`,
    hazardKind: ['earthquake', 'wildfire', 'volcano'][i % 3],
    metrics: i % 3 === 0 ? { kind: 'earthquake', magnitude: 6.4, depthKm: 12 } : i % 3 === 1 ? { kind: 'wildfire', detectionCount: 3 } : { kind: 'volcano-or-other', statusLabel: 'fixture' },
    severity: ['info', 'watch', 'warning', 'critical'][i % 4],
    geometry: { type: 'Point', coordinates: i < 90 ? [-122.1, 37.4] : [-128 + (i % 31) * .42, 31 + (Math.floor(i / 31) % 25) * .5] },
  }));
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**', route => route.fulfill({
    json: mapResponse(new URL(route.request().url()).searchParams.get('source')!,
      new URL(route.request().url()).searchParams.get('source') === 'usgs' ? events : []),
  }));
  const aircraftCount = v3 ? count === 750 ? 180 : 1000 : 0;
  if (v3) {
    await page.route('**/wm-api/runtime/transport/global-shipping**', route => route.fulfill({json:{...transportPayload, aviation:{generatedAt:GENERATED_AT, routes:[], hubs:[], flights:[], liveFlights:[]}}}));
    await page.route('**/wm-api/runtime/transport/aviation-viewport?**', route => route.fulfill({json:{
      schemaVersion:'aviation-viewport.v1',status:'ok',generatedAt:GENERATED_AT,source:'Controlled performance fixture',
      bbox:new URL(route.request().url()).searchParams.get('bbox')!.split(',').map(Number),zoom:3,coverage:{complete:true},
      aircraftCount,availableAircraftCount:aircraftCount,
      aircraft:Array.from({length:aircraftCount},(_,i)=>({id:`perf-plane:${i}`,icao24:`v3${i}`,callsign:`Controlled ${i}`,lon:-128+(i%40)*.6,lat:31+(Math.floor(i/40)%25)*.4,updatedAt:GENERATED_AT,source:'Controlled performance fixture',heading:i%360})),
    }}));
  }
  const network = await installRealMapAssets(page);
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  try {
    await gotoMapScene(page, `/?view=2d&mapPerf=1&basemap=pmtiles&center=-110,38&zoom=3&time=all&layers=earthquakes-volcanoes,wildfires${v3 ? ',air-routes&air=all' : ''}&severity=info,watch,warning,critical`);
    await page.addStyleTag({ content: '.wm-map-stage,.wm-inline-weather-map,.wm-weather-deck-map{height:620px!important;min-height:620px!important;max-height:620px!important;width:2040px!important}' });
    const host = page.locator('[data-map-renderer-ready]');
    await expect(host).toHaveAttribute('data-map-basemap-state', 'primary-ready');
    await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText(String(count + aircraftCount));
    await page.evaluate(() => document.fonts.ready);
    await host.scrollIntoViewIfNeeded(); await page.mouse.move(0, 0); await page.waitForTimeout(2000);
    await page.locator('.wm-weather-deck-map').screenshot({ path: resolve(output, `${count}-dense.png`) });
    const initialIndex = await host.evaluate((el: any) => el.__polymonitorMapPresentation?.(false));
    await page.context().tracing.start({ screenshots: true, snapshots: true });
    await page.evaluate(() => {
      const w = window as any; w.__polishFrames = []; w.__polishTasks = []; w.__polishMeasuring = true;
      w.__polishObserver = new PerformanceObserver(list => w.__polishTasks.push(...list.getEntries().map(e => e.duration)));
      w.__polishObserver.observe({ type: 'longtask', buffered: false });
      let previous = performance.now();
      const sample = (now: number) => { if (!w.__polishMeasuring) return; w.__polishFrames.push(now - previous); previous = now; requestAnimationFrame(sample); };
      requestAnimationFrame(sample);
    });
    const box = (await host.boundingBox())!;
    await page.mouse.move(box.x + 1000, box.y + 300); await page.mouse.down();
    for (let i = 0; i < 300; i++) {
      await page.mouse.move(box.x + 1000 + Math.sin(i / 12) * 160, box.y + 300 + Math.cos(i / 12) * 50);
      await page.waitForTimeout(100);
    }
    await page.mouse.up();
    const performance = await page.evaluate(() => {
      const w = window as any; w.__polishMeasuring = false; w.__polishObserver.disconnect();
      const frames = w.__polishFrames.sort((a: number, b: number) => a - b);
      return { rafP95: frames[Math.ceil(frames.length * .95) - 1], rafMax: frames.at(-1), longTasks: w.__polishTasks,
        phases: window.__POLYMONITOR_MAP_PERF__?.snapshot(), dpr: devicePixelRatio };
    });
    // moveend publishes a new real bbox: wait for its debounced response,
    // without adding that wait to the continuous-drag timing sample.
    if(v3)await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText(String(count+aircraftCount));
    const finalIndex = await host.evaluate((el: any) => el.__polymonitorMapPresentation?.(false));
    if (!baseline) {
      expect(finalIndex.leafReadCount).toBe(initialIndex.leafReadCount);
      expect(finalIndex.buildCount).toBe(initialIndex.buildCount);
      const audit = await host.evaluate((el: any) => el.__polymonitorMapPresentation(true));
      writeFileSync(resolve(output, `${count}-membership.json`), JSON.stringify(audit, null, 2));
      expect(Object.keys(audit.membership)).toHaveLength(count+aircraftCount);
      expect(Object.keys(audit.membership).filter(id=>id.startsWith('polish-fixture:'))).toHaveLength(count);
      expect(Object.values(audit.membership)).not.toContain('DUPLICATE');
      expect(Object.entries(audit.membership).filter(([id])=>id.startsWith('polish-fixture:')).every(([,value])=>/^(single|mixed:|cluster:)/.test(String(value)))).toBe(true);
      // Dragging can put returned aircraft outside the camera. They must have
      // an explicit offscreen classification and remain in the complete list.
      const aircraftMembers=Object.entries(audit.membership).filter(([id])=>id.endsWith(':live-aircraft'));
      expect(aircraftMembers).toHaveLength(aircraftCount);
      expect(aircraftMembers.every(([,value])=>/^(record-entry:|offscreen:)/.test(String(value)))).toBe(true);
    }
    const hoverMs: number[] = [];
    if (!baseline || v3) {
      const target = await host.evaluate((el: any) => {
        const rect = el.getBoundingClientRect();
        return el.__polymonitorMapPresentation(false).markers.map((marker: any) => ({ ...marker,
          p: el.__polymonitorProjectGeoPoint(...marker.coordinates) })).find((marker: any) =>
          marker.count > 1 && marker.p.x > 400 && marker.p.x < rect.width - 100 && marker.p.y > 60 && marker.p.y < rect.height - 100);
      });
      expect(target).toBeTruthy();
      for (let i = 0; i < 20; i++) {
        await page.mouse.move(box.x + box.width - 150, box.y + 50);
        await expect(page.locator('.wm-world-event-renderer-tooltip')).toBeHidden();
        await host.evaluate(el => {
          const w = window as any; w.__hoverLatency = null;
          el.addEventListener('pointermove', () => {
            const start = performance.now(); const observer = new MutationObserver(() => {
              const tooltip = el.querySelector<HTMLElement>('.wm-world-event-renderer-tooltip');
              if (!tooltip || tooltip.hidden) return;
              observer.disconnect(); requestAnimationFrame(() => { w.__hoverLatency = performance.now() - start; });
            }); observer.observe(el, { subtree: true, childList: true, attributes: true });
          }, { once: true, capture: true });
        });
        await page.mouse.move(box.x + target.p.x, box.y + target.p.y);
        await page.waitForFunction(() => (window as any).__hoverLatency !== null);
        hoverMs.push(await page.evaluate(() => (window as any).__hoverLatency));
      }
      hoverMs.sort((a,b) => a-b);
      await page.mouse.click(box.x + target.p.x, box.y + target.p.y);
      if (!await page.locator('#wm-world-event-list-panel').isVisible()) await page.locator('.wm-world-event-list-toggle').click();
    } else {
      await page.mouse.wheel(0, -150); await page.waitForTimeout(700);
      await page.locator('.wm-world-event-list-toggle').click();
    }
    await expect(page.locator('.wm-world-event-list-scroll')).toBeVisible();
    if(v3&&!baseline){
      const allLoaded=page.getByRole('button',{name:'All loaded events',exact:true});if(await allLoaded.isVisible())await allLoaded.click();
      await page.locator('.wm-world-event-list input[type=search]').fill(`Controlled ${aircraftCount-1}`);
      await expect(page.getByRole('button',{name:new RegExp(`Controlled ${aircraftCount-1}(?:\\s|$)`)})).toBeVisible();
      await page.locator('.wm-world-event-list input[type=search]').fill('');
    }
    await page.locator('.wm-world-event-list li button').first().evaluate(el => {
      el.addEventListener('click',()=>{
        (window as any).__localSelectionStart = performance.now();
        const observer = new MutationObserver(() => {
          if (!document.querySelector('.wm-event-inspector')) return;
          observer.disconnect();
          requestAnimationFrame(() => { (window as any).__localSelectionMs = performance.now() - (window as any).__localSelectionStart; });
        });observer.observe(document.body,{childList:true,subtree:true});
      },{once:true,capture:true});
    });
    await page.locator('.wm-world-event-list li button').first().click();
    await expect(page.locator('.wm-event-inspector')).toBeVisible();
    await page.waitForFunction(() => (window as any).__localSelectionMs !== undefined);
    const localSelectionMs = await page.evaluate(() => (window as any).__localSelectionMs);
    await page.waitForTimeout(1000); await page.keyboard.press('Escape');
    if (!baseline) {
      if (await page.locator('.wm-world-event-list-close').isVisible()) await page.locator('.wm-world-event-list-close').click();
      await host.hover({ position: { x: 1000, y: 200 } });
      await page.mouse.wheel(0, -150); await page.waitForTimeout(700);
      await page.getByRole('checkbox', { name: 'Hide Wildfires', exact: true }).uncheck();
      await page.waitForTimeout(500);
      await page.getByRole('checkbox', { name: 'Show Wildfires', exact: true }).check();
      await expect(page.locator('.wm-world-event-list-toggle strong')).toHaveText(String(count + aircraftCount));
      await page.waitForTimeout(500);
    }
    await page.context().tracing.stop({ path: resolve(output, `${count}-interaction.zip`) });
    writeFileSync(resolve(output, `${count}-evidence.json`), JSON.stringify({ phase, count, aircraftCount, fixture: GENERATED_AT, browser: browser.version(), performance, localSelectionMs, hoverMs, hoverP95: hoverMs[Math.ceil(hoverMs.length * .95) - 1], initialIndex, finalIndex, errors }, null, 2));
    expect(errors).toEqual([]);
    if (!baseline) { expect(performance.rafP95).toBeLessThanOrEqual(32); expect(localSelectionMs).toBeLessThanOrEqual(150); expect(hoverMs[18]).toBeLessThanOrEqual(v3 ? 100 : 120); }
  } finally { await page.goto('about:blank'); await page.unrouteAll({ behavior: 'wait' }); await network.dispose(); }
});
