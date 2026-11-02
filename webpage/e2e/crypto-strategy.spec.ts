import { test, expect } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';
test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });
const ids = ['crypto-watch','crypto-order-flow','crypto-funding-watch','crypto-perp-funding','crypto-oracle-reference','options-implied-probability','crypto-exchange-inflow','stablecoin-monitor'];

for (const width of [1440,390]) test(`crypto strategy source states and controls at ${width}px`, async ({page}) => {
  await page.setViewportSize({width,height:900});
  await installDashboard(page,'en',ids);
  const now=Date.now(), errors:string[]=[];
  await page.clock.setFixedTime(new Date(now));
  page.on('pageerror',e=>errors.push(e.message));
  let requests=0, offline=false;
  const fixture = {
    schemaVersion:1,kind:'crypto-strategy',status:'partial',generatedAt:new Date(now).toISOString(),collectedAt:now,
    assets:Object.fromEntries(['BTC','ETH','SOL','XRP'].map(asset=>[asset,{asset,spot:{price:100},linear:{mark:101,index:100,oi:500,oiValue:50000},spotHistory:[{t:now-900000,v:100},{t:now,v:101}],oiHistory:[{t:now-900000,v:500},{t:now,v:550}],basisBps:100,premiumBps:100,fundingHistory:[{t:now-28800000,v:.01},{t:now,v:.02}],
      flow:{net:99,buy:200,sell:101,count:2,limit:60,from:now-1000,to:now,cvd:[{t:now-1000,v:200},{t:now,v:99}],trades:[]},depth:{bids:[[99,1]],asks:[[101,1]],imbalance:-.01,levels:1,method:'snapshot'}}])),
    references:{BTC:{status:'stale',latest:{value:'101',event_at_ms:now-600000,window_seconds:60},history:[],spotHistory:[],quotes:{}}},
    options:{BTC:{source:'Deribit',observedAt:new Date(now).toISOString(),expiries:[{expiry:new Date(now+86400000).toISOString(),underlying:77500,bands:[{strike:77000,lowerStrike:76000,upperStrike:78000,probability:.5,low:.4,high:.6,iv:50,instruments:['BTC-CALL']}]}]}},
    stablecoins:[{asset:'USDC',source:'Coinbase',price:1.001,deviationBps:10,status:'ok',receivedAt:new Date(now).toISOString(),history:[{t:now-30000,v:5},{t:now,v:10}]}],
    inflows:{mode:'historical',rows:[{date:'2026-06-25',exchange:'Binance',inflow:5,outflow:4,net:1,transactions:2},{date:'2026-06-26',exchange:'Binance',inflow:6,outflow:4,net:2,transactions:3}]},
  };
  await page.route('**/wm-api/runtime/crypto/order-flow',route=>{ requests++; return offline?route.fulfill({status:503,json:{error:'fixture outage'}}):route.fulfill({json:fixture}); });
  await page.goto('/e2e/panels.html');
  await page.waitForFunction(()=>window.panelHarness);
  for (const id of ids) {
    await page.evaluate(id=>window.panelHarness.mount(id),id);
    const panel=page.locator('.wm-panel-slot');
    await expect(panel.locator('.wm-panel')).toBeVisible();
    if (id==='crypto-funding-watch') {
      await panel.locator('details').filter({hasText:'Settled funding history'}).locator('summary').click();
    } else {
      await expect(panel).toContainText(id==='crypto-exchange-inflow'?'Historical BTC research':id==='stablecoin-monitor'?'Coinbase':'BTC');
    }
    expect(await panel.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  }
  await page.evaluate(()=>window.panelHarness.mount('crypto-oracle-reference'));
  await expect(page.locator('.wm-cstrategy-empty')).toBeVisible();
  await expect(page.locator('.wm-cstrategy-stats')).toHaveCount(0);
  await page.evaluate(()=>window.panelHarness.mount('options-implied-probability'));
  const optionsPanel = page.locator('.wm-panel');
  // At 1440px the actual five-column workspace gives this panel only 284px.
  await page.locator('.wm-panel-slot').evaluate((el, width) => {
    (el as HTMLElement).style.width = `${width === 1440 ? 284 : 382}px`;
    (el as HTMLElement).style.height = '284px';
  }, width);
  await expect(optionsPanel).toContainText('PM expiry unmatched');
  const optionsChart = await optionsPanel.locator('.wm-cstrategy-chart svg').boundingBox();
  const optionsBody = await optionsPanel.locator('.wm-panel-body').boundingBox();
  expect(optionsChart!.y + optionsChart!.height).toBeLessThanOrEqual(optionsBody!.y + optionsBody!.height);
  await page.locator('.wm-panel-slot').evaluate(el => el.removeAttribute('style'));
  await page.evaluate(()=>window.panelHarness.mount('crypto-order-flow'));
  await expect(page.locator('.wm-cstrategy-stats')).toContainText('99');
  const flowPanel = page.locator('.wm-panel');
  await expect(flowPanel.locator('.wm-panel-title')).toHaveCSS('font-size', '11px');
  await expect(flowPanel.locator('.wm-panel-title')).toHaveCSS('font-weight', '600');
  await expect(page.locator('.wm-panel-slot')).toHaveCSS('box-shadow', 'none');
  await expect(flowPanel.locator('.wm-panel-header').getByRole('button', { name: 'Refresh', exact: true })).toBeVisible();
  await expect(flowPanel.locator('.wm-panel-body')).not.toContainText('Snapshot');
  await expect(flowPanel.locator('.wm-panel-data-popover')).not.toBeVisible();
  const chart = await flowPanel.locator('.wm-cstrategy-chart svg').boundingBox();
  const body = await flowPanel.locator('.wm-panel-body').boundingBox();
  expect(chart!.y + chart!.height).toBeLessThanOrEqual(body!.y + body!.height);
  await flowPanel.getByLabel('Data details', { exact: true }).click();
  await expect(flowPanel.locator('.wm-panel-data-popover')).toBeVisible();
  await expect(flowPanel.locator('.wm-panel-data-popover')).toContainText('Snapshot');
  await flowPanel.getByLabel('Data details', { exact: true }).press('Escape');
  await expect(flowPanel.locator('.wm-panel-data-popover')).not.toBeVisible();

  await page.getByRole('button',{name:'ETH',exact:true}).click();
  await page.evaluate(()=>window.panelHarness.mount('crypto-perp-funding'));
  await expect(page.getByRole('button',{name:'ETH',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(page.locator('.wm-cstrategy-stats').first()).toContainText('500');
  const before=requests; offline=true;
  await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await expect.poll(()=>requests).toBeGreaterThan(before);
  await expect(page.locator('.wm-panel-slot')).toContainText('Delayed or unavailable');
  await expect(page.locator('.wm-cstrategy-stats').first()).toContainText('500');
  expect(errors).toEqual([]);
});
