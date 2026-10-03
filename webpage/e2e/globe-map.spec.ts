import { expect, test } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';

test('2D does not download the globe engine or texture',async({page})=>{
  const downloads:string[]=[];
  page.on('request',request=>{if(/GlobeMapRenderer|earth-topo-bathy|globe_gl|three\.module/.test(request.url()))downloads.push(request.url());});
  await installDashboard(page);
  await page.goto('/?view=2d&mapPerf=1&basemap=openfreemap');
  await expect(page.locator('[data-map-renderer-ready]')).toHaveAttribute('data-map-renderer-ready',/webgl|svg/,{timeout:60000});
  expect(downloads).toEqual([]);
});

test('3D context failure falls back and recovers the same filtered records',async({page})=>{
  test.setTimeout(180000);
  await installDashboard(page);
  await page.clock.install({time:new Date('2026-08-26T03:00:00Z')});
  await page.goto('/?view=3d&mapPerf=1&time=all&center=-70,43&zoom=3');
  const host=page.locator('[data-map-renderer-ready]');
  await expect(host).toHaveAttribute('data-map-renderer-ready','globe',{timeout:60000});
  const globe=page.locator('.wm-globe-renderer');
  await expect.poll(async()=>Number(await globe.getAttribute('data-globe-records'))).toBeGreaterThan(0);
  await expect(globe).toHaveAttribute('data-globe-aircraft','1');
  const records=await globe.getAttribute('data-globe-records');
  for (let episode=0;episode<2;episode++) {
  await globe.locator('canvas').first().evaluate(canvas=>{
    const gl=(canvas as HTMLCanvasElement).getContext('webgl2')!;
    const extension=gl.getExtension('WEBGL_lose_context');
    if(!extension)throw new Error('Context loss extension unavailable');
    extension.loseContext();
  });
  await expect(host).toHaveAttribute('data-map-renderer-ready','svg',{timeout:30000});
  await page.getByRole('button',{name:'Retry detailed map'}).click();
  await expect(host).toHaveAttribute('data-map-renderer-ready','globe',{timeout:60000});
  await expect(globe).toHaveAttribute('data-globe-records',records!);
  await expect(page.locator('.wm-map-renderer-retry')).toHaveCount(0);
  }
  await page.screenshot({path:'artifacts/map-unified-renderer-20261003/candidate/globe-recovered.png'});
});
