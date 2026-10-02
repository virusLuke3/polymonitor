import { test, expect } from '@playwright/test';
import { installFixtures, GENERATED_AT } from './fixtures/world-event-map';
import { gotoMapScene, selectMapLayers } from './fixtures/browser';

const frame = {host:'https://tilecache.rainviewer.com',radar:{past:[{time:Date.parse(GENERATED_AT)/1000,path:'/v2/radar/recovered'}]}};
test.afterEach(async ({page}) => { await page.unrouteAll({behavior:'ignoreErrors'}); await page.goto('about:blank'); });

test.beforeEach(async ({page}) => { await page.clock.setFixedTime(new Date(GENERATED_AT)); await installFixtures(page); });

test('radar recovers promptly from first manifest failure and respects manual off', async ({page}) => {
  let count=0;
  await page.route('https://api.rainviewer.com/public/weather-maps.json',route=>{
    count++;return count===1?route.fulfill({status:503,body:'temporary failure'}):route.fulfill({json:frame});
  });
  await page.goto('/?view=2d&basemap=openfreemap&mapPerf=1');
  await page.locator('.wm-map-section').scrollIntoViewIfNeeded();
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready','webgl');
  await expect.poll(()=>count,{timeout:20000}).toBeGreaterThanOrEqual(2);
  const radar=page.locator('.wm-map-radar-status');
  await expect(radar).toHaveAttribute('data-radar-tiles','ready');
  await radar.locator('summary').click();
  await expect(radar.getByRole('button',{name:'Refresh radar',exact:true})).toBeVisible();
  const before=count;
  await radar.getByRole('button',{name:'Refresh radar',exact:true}).click();
  await expect.poll(()=>count).toBeGreaterThan(before);
  await radar.locator('summary').click();
  // Existing layer controls remain the sole enablement authority.
  await selectMapLayers(page, new URL(page.url()).searchParams.get('layers')!.split(',').filter(id=>id!=='weather-radar'));
  await expect(radar.locator('summary')).toContainText('Off');
});

test('search, regional temperature and country brief share real map navigation', async ({page}) => {
  const queries:string[]=[];
  await page.route('**/runtime/weather/map-query?**',route=>{
    const u=new URL(route.request().url());queries.push(u.search);
    return route.fulfill({json:u.searchParams.has('lat')?{
      status:'ok',current:{time:GENERATED_AT.slice(0,16),temperature_2m:18.4,wind_speed_10m:8,relative_humidity_2m:60},
      hourly:{time:[],temperature_2m:[]},daily:{time:['2026-08-26'],temperature_2m_min:[12],temperature_2m_max:[20]},
      source:'Open-Meteo',sourceUrl:'https://open-meteo.com/',
    }:{status:'ok',places:[{id:'london',name:'London',lat:51.5085,lon:-.1257,country:'United Kingdom',region:'England'}]}});
  });
  await gotoMapScene(page,'/?view=2d&basemap=openfreemap&mapPerf=1&layers=weather-alerts,earthquakes-volcanoes');
  const search=page.locator('.wm-map-explore');await search.locator('summary').click();
  await search.getByRole('searchbox').fill('London');
  await search.getByRole('button',{name:'London · England · United Kingdom',exact:true}).click();
  await expect(search).toContainText('18.4 °C');
  await expect(search).toContainText('Model estimate, not a hazard warning');
  expect(queries.some(q=>q.includes('lat=51.5085')&&q.includes('lon=-0.1257'))).toBe(true);
  await expect(page).toHaveURL(/zoom=5/);
  await search.getByRole('searchbox').fill('Taiwan');
  await search.getByRole('button',{name:/Taiwan.*Country brief/}).click();
  await expect(page.locator('.wm-event-inspector')).toContainText('Country brief');
  await page.getByRole('button',{name:'Filter country',exact:true}).click();
  await expect(page).toHaveURL(/country=TW/);
});

test('mobile map keeps filters available with compact source and aviation panels', async ({page}) => {
  await page.setViewportSize({width:390,height:844});
  await page.goto('/?view=2d&basemap=openfreemap&mapPerf=1');
  await page.locator('.wm-map-section').scrollIntoViewIfNeeded();
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready','webgl');
  const filters=page.locator('.wm-map-filter-details');
  await expect(filters).not.toHaveAttribute('open','');
  await filters.locator('summary').click();
  await filters.getByRole('button',{name:'24h',exact:true}).click();
  await expect(page).toHaveURL(/time=24h/);
  await filters.locator('summary').click();
  await expect(page.locator('.wm-map-source-details')).not.toHaveAttribute('open','');
  const lens=page.locator('.wm-aviation-lens');await expect(lens).toBeVisible();
  expect((await lens.boundingBox())!.height).toBeLessThan(100);
  await page.locator('.wm-map-source-details > summary').click();
  await expect(page.locator('.wm-map-source-statuses')).toBeVisible();
  await page.screenshot({path:'artifacts/map-completion-20261002/fixture-mobile-controls.png'});
  await page.locator('.wm-map-source-details > summary').click();
  const host=page.locator('[data-map-renderer-ready]');
  await host.dispatchEvent('polymonitor:map-renderer-failure');
  await expect(host).toHaveAttribute('data-map-renderer-ready','svg');
  const warning=(await page.locator('.wm-weather-deck-status').boundingBox())!;
  const search=(await page.locator('.wm-map-explore > summary').boundingBox())!;
  expect(search.y).toBeGreaterThanOrEqual(warning.y+warning.height);
  await page.getByRole('button',{name:'Retry detailed map',exact:true}).click();
  await expect(host).toHaveAttribute('data-map-renderer-ready','webgl');
});

test('turning off one supplemental layer keeps the other source requests owned', async ({page}) => {
  let gps=0, faa=0;
  await page.route('**/runtime/world/signals?source=gpsjam',r=>{gps++;return r.fulfill({json:{status:'partial',events:[],message:'GPS fixture'}});});
  await page.route('**/runtime/transport/map?source=faa',r=>{faa++;return r.fulfill({json:{status:'partial',events:[],message:'FAA fixture'}});});
  await page.goto('/?view=2d&basemap=openfreemap&mapPerf=1');
  await page.locator('.wm-map-section').scrollIntoViewIfNeeded();
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready','webgl');
  await expect.poll(()=>gps).toBe(1);await expect.poll(()=>faa).toBe(1);
  await expect(page).toHaveURL(/layers=/);
  await selectMapLayers(page,new URL(page.url()).searchParams.get('layers')!.split(',').filter(id=>id!=='airport-disruptions'));
  await page.waitForTimeout(700);
  expect(gps).toBe(1);expect(faa).toBe(1);
});
