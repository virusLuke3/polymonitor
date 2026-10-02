import { useEffect, useMemo, useState } from 'preact/hooks';
import { fetchMapInfrastructure } from '@/services/api';
import type { RendererViewport } from '../renderer/MapRenderer';
import type { GeoEvent } from '../domain/types';
import type { WorldEventSourceStatus } from './sourceStatus';
import { validateGeoEvents } from '../domain/validation';
import { aviationQueryBounds } from './useAviationViewport';

/** Actual renderer bounds, including both date-line halves; never a center box. */
export function useMapInfrastructure(enabled: boolean, viewport: RendererViewport | null) {
  const bounds = aviationQueryBounds(viewport);
  const ready = bounds.length > 0 && bounds.every(([w,s,e,n]) => (e-w)*(n-s) <= 25);
  const key = enabled && ready ? JSON.stringify(bounds) : '';
  const [result, setResult] = useState<{key:string; events: GeoEvent[]; error?:string; updatedAt?:string; message?:string} | null>(null);
  useEffect(() => {
    if (!key) return;
    let disposed=false, controller: AbortController | null=null, timer:ReturnType<typeof setTimeout>|undefined, failures=0;
    const refresh=async()=>{
      if(disposed || document.hidden || navigator.onLine===false || controller)return;
      const request=new AbortController();controller=request;
      try {
        const parts = await Promise.all((JSON.parse(key) as number[][]).map(b => fetchMapInfrastructure(b, request.signal)));
        if (disposed || request.signal.aborted || controller!==request)return;
        const parsed=validateGeoEvents(parts.flatMap(p=>p.events));
        setResult({key,events:[...new Map(parsed.events.map(e=>[e.id,e])).values()],updatedAt:parts[0]?.updatedAt,
          message: [...new Set(parts.map(p=>p.message))].join(' · ') + (parsed.rejected.length ? ` · ${parsed.rejected.length} invalid records rejected` : '')});failures=0;
      } catch(error) {if(!disposed && !request.signal.aborted) {failures++;setResult({key,events:[],error:String(error)});}}
      finally {if(controller===request){controller=null;if(!disposed && !document.hidden)timer=setTimeout(refresh,failures?[5000,15000,45000][failures-1]??300000:3600000);}}
    };
    const resume=()=>{clearTimeout(timer);controller?.abort();controller=null;void refresh();};
    timer=setTimeout(refresh,500);document.addEventListener('visibilitychange',resume);window.addEventListener('online',resume);
    return()=>{disposed=true;clearTimeout(timer);controller?.abort();document.removeEventListener('visibilitychange',resume);window.removeEventListener('online',resume);};
  },[key]);
  return useMemo(() => {
  const current=result?.key===key?result:null;
  const source:WorldEventSourceStatus={key:'osm-infrastructure',label:'OSM infrastructure',status: !ready?'partial':current?.error?'error':current?'partial':'loading',
    eventCount:current?.events.length||0,rejectedCount:0,generatedAt:current?.updatedAt,
    message:!ready?'Zoom in for mapped waterways, cables and pipelines; native viewport query limited to 25 square degrees.':current?.error||current?.message,
    phase:!ready?'zoom-required':current?.error?'unavailable':current?'partial':'loading'};
  return {events:enabled?current?.events||[]:[],sources:enabled?[source]:[]};
  }, [result, key, ready, enabled]);
}
