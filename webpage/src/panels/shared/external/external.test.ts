import {expect,it} from 'vitest';
import {DEFAULT_PANEL_IDS,PANEL_REGISTRY} from '../../registry';
import {reconcileDefaultPanels} from '../../../features/workspace/defaultPanels';
import {isBasePayload} from './resource';
const ids=['geo-conflict-watch','geo-ceasefire-watch','geo-territory-control','geo-diplomacy-calendar','geo-treaty-tracker','weather-precipitation','weather-drought','weather-extremes','weather-storm-advisory','sports-spread-monitor','sports-total-monitor','sports-player-props','sports-tournament-path','sports-season-race','sports-awards-watch','esports-map-state','esports-tournament-path','crypto-listing-watch','crypto-project-milestones','chain-metrics-monitor','fiscal-tax-monitor','merger-progress','private-valuation-watch','ai-leaderboard-watch','art-auction-watch','culture-box-office','culture-awards-race','culture-music-charts','product-release-watch','public-figure-events','reality-show-progress','research-evidence-watch','social-window-monitor','space-mission-watch','mentions-evidence'];
it('adds all 35 modules to existing layouts while preserving explicit later hides',()=>{
 const before=['crypto-watch','policy-progress'];const known=DEFAULT_PANEL_IDS.filter(id=>!ids.includes(id));
 const next=reconcileDefaultPanels(before,DEFAULT_PANEL_IDS,known);
 expect(next.activePanelIds.slice(0,2)).toEqual(before);expect(next.activePanelIds.slice(2).sort()).toEqual([...ids].sort());
 for(const id of ids){expect(PANEL_REGISTRY[id]?.fetchData).toBeTypeOf('function');expect(PANEL_REGISTRY[id]?.defaultEnabled).toBe(true);}
 const hidden=next.activePanelIds.filter(id=>id!=='geo-conflict-watch');
 expect(reconcileDefaultPanels(hidden,DEFAULT_PANEL_IDS,next.knownDefaultPanelIds).activePanelIds).toEqual(hidden);
});
it('does not accept fabricated source clocks',()=>{
 expect(isBasePayload({panelId:'x',schemaVersion:1,generatedAt:'not-a-date',status:'ok',sources:[]})).toBe(false);
 expect(isBasePayload({panelId:'x',schemaVersion:1,generatedAt:null,status:'unavailable',sources:[{id:'x',lastSuccessAt:null,usable:false,stale:true}]})).toBe(true);
});
it('rejects a cache whose older source expired despite another fresh component',()=>{
 const contract=PANEL_REGISTRY['geo-ceasefire-watch']!.snapshot!;
 const fresh=new Date().toISOString(),old=new Date(Date.now()-3600000).toISOString();
 const value={panelId:'geo-ceasefire-watch',schemaVersion:1,generatedAt:fresh,status:'ok',items:[],historical:[],sources:[
  {id:'recent',lastSuccessAt:fresh,usable:true,stale:false,maxRetentionSeconds:7200},
  {id:'old',lastSuccessAt:old,usable:true,stale:false,maxRetentionSeconds:900},
 ]};
 expect(()=>contract.parse(value)).toThrow('retention');
});
