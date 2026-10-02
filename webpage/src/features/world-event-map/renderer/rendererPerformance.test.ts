import { afterEach, describe, expect, it, vi } from 'vitest';
import { DeckMapRenderer } from './DeckMapRenderer';
import { defaultWorldEventMapState } from '../state/mapState';
import type { GeoEvent } from '../domain/types';
import { createEventGeometryLayers, EventGeometryCache } from './layerFactories/eventGeometryLayers';

const point: GeoEvent = {id:'point',category:'intel',title:'Observed event',severity:'watch',geometry:{type:'Point',coordinates:[0,0]},locationPrecision:'exact',sources:[{provider:'fixture'}],limitations:[],relatedMarketIds:[],properties:{}};
const country: GeoEvent = {...point,id:'country',category:'country-risk',geometry:{type:'Polygon',coordinates:[[[0,0],[1,0],[1,1],[0,0]]]},properties:{mapEntity:'country-risk-area'}};
const path: GeoEvent = {...point,id:'path',geometry:{type:'LineString',coordinates:[[0,0],[1,1]]}};
const flags = {points:false,geometry:false,aviation:false,dynamic:false,pulse:false,interaction:false};
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});

describe('map render work ownership',()=>{
  it('does not submit the static scene for an aircraft-only frame',()=>{
    const renderer=new DeckMapRenderer() as any;
    vi.stubGlobal('window',{location:{search:''},requestAnimationFrame:vi.fn(()=>1),cancelAnimationFrame:vi.fn(),clearTimeout});
    renderer.setEvents([{...path,category:'infrastructure',properties:{mapEntity:'air-route'}}]);
    renderer.state={...defaultWorldEventMapState(),activeLayerIds:['air-routes']};
    const request=vi.spyOn(renderer,'requestRender');
    renderer.lastAnimationTimestamp=0;renderer.handleAnimationFrame(100);
    expect(request).toHaveBeenLastCalledWith({dynamic:true,pulse:false});
    const staticCommit=vi.fn(),motionCommit=vi.fn();renderer.overlay={setProps:staticCommit};renderer.aviationOverlay={setProps:motionCommit};
    renderer.aviationLayerSections={data:{routeMotionGroups:[],flightMotionGroups:[]}};
    renderer.flushRender({...flags,dynamic:true});
    expect(motionCommit).toHaveBeenCalledOnce();expect(staticCommit).not.toHaveBeenCalled();
    renderer.overlay=null;renderer.aviationOverlay=null;renderer.destroy();
  });
  it('keeps geometry valid when only ordinary points change',()=>{
    const renderer=new DeckMapRenderer() as any;
    renderer.setEvents([country,point]);const version=renderer.geometryGeneration;
    renderer.setEvents([country,{...point,title:'Revised point'}]);
    expect(renderer.geometryGeneration).toBe(version);
    renderer.setEvents([{...country,severity:'critical'},point]);
    expect(renderer.geometryGeneration).toBe(version+1);renderer.destroy();
  });
  it('cannot lose a completed geometry commit when an aircraft frame shares its RAF', async () => {
    vi.useFakeTimers();
    const renderer = new DeckMapRenderer() as any;
    const request = vi.spyOn(renderer, 'requestRender').mockImplementation(() => undefined);
    renderer.heavyGeometryCommit.stage({
      events: [path], selectedEventId: null, zoom: 2,
      generation: renderer.geometryGeneration,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(renderer.geometryLayers[0].id).toBe('world-event-paths');
    expect(request).toHaveBeenLastCalledWith({ interaction: true });
    renderer.destroy();
  });
  it('reuses country/path layers independently and never reuses removed or context-lost instances',()=>{
    const cache=new EventGeometryCache();
    const build=(events:GeoEvent[],selected:string|null=null)=>createEventGeometryLayers(events,selected,2,'labels',undefined,cache) as any[];
    const first=build([country,path]);const next=build([country,{...path,severity:'warning'}]);
    expect(next[0]).toBe(first[0]);expect(next[1]).not.toBe(first[1]);
    const selected=build([country,path],country.id);expect(selected[0]).not.toBe(first[0]);
    build([]);expect(build([country,path])[0]).not.toBe(selected[0]);
    const attached=build([country,path]);cache.clear();expect(build([country,path])[0]).not.toBe(attached[0]);
  });
  it('reuses label queries for data updates and refreshes after resize',()=>{
    const renderer=new DeckMapRenderer() as any;const query=vi.fn(()=>[]);
    renderer.state={...defaultWorldEventMapState(),activeLayerIds:[]};renderer.geometryNeedsCommit=false;
    renderer.map={getBounds:()=>null,getStyle:()=>({layers:[{id:'labels',type:'symbol'}]}),queryRenderedFeatures:query,
      getContainer:()=>({clientWidth:1000,clientHeight:700}),project:()=>({x:0,y:0}),triggerRepaint:vi.fn(),resize:vi.fn()};
    renderer.overlay={setProps:vi.fn()};renderer.schedulePickingWarmup=vi.fn();renderer.emitViewport=vi.fn();
    renderer.flushRender({...flags,points:true});renderer.flushRender({...flags,points:true});expect(query).toHaveBeenCalledOnce();
    renderer.resize();renderer.flushRender({...flags,points:true});expect(query).toHaveBeenCalledTimes(2);
    renderer.map=null;renderer.overlay=null;renderer.destroy();
  });
  it('retries transient radar tiles promptly, stops at the budget and respects rate limits',()=>{
    const renderer=new DeckMapRenderer() as any;vi.useFakeTimers();vi.stubGlobal('window',globalThis);
    renderer.radarFrame={time:1,tiles:'fixture',coverageTiles:'coverage'};renderer.applyRadar=vi.fn();
    for(const delay of [5000,15000,45000]){renderer.handleMapError({sourceId:'weather-radar',error:{message:'network'}});vi.advanceTimersByTime(delay);}
    expect(renderer.applyRadar).toHaveBeenCalledTimes(3);
    renderer.handleMapError({sourceId:'weather-radar',error:{message:'network'}});vi.advanceTimersByTime(60000);
    expect(renderer.applyRadar).toHaveBeenCalledTimes(3);
    renderer.radarRetryCount=0;
    renderer.handleMapError({sourceId:'weather-radar',error:{status:429,message:'limited',headers:new Headers({'Retry-After':'600'})}});
    vi.advanceTimersByTime(599999);expect(renderer.applyRadar).toHaveBeenCalledTimes(3);
    vi.advanceTimersByTime(1);expect(renderer.applyRadar).toHaveBeenCalledTimes(4);renderer.destroy();
  });
});
