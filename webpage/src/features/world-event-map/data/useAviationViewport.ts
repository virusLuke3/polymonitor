import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { ApiHttpError, fetchAviationViewport } from '@/services/api';
import type { AviationViewportPayload } from '@/types';
import type { RendererViewport } from '../renderer/MapRenderer';

const CACHE_TTL_MS = 30_000;
const viewportCache = new Map<string, { storedAt: number; payload: AviationViewportPayload }>();
export type AviationPhase = 'OFF' | 'ZOOM_REQUIRED' | 'LOADING' | 'READY' | 'EMPTY' | 'PARTIAL' | 'STALE' | 'UNAVAILABLE' | 'RENDERER_LIMITED';
/** Outward quantization guarantees coverage of every corner, never center rounding. */
export function aviationQueryBounds(viewport: RendererViewport | null) {
  if (!viewport || viewport.zoom < 2) return [];
  return viewport.bounds.map(([w,s,e,n]) => [Math.max(-180,Math.floor(w*20)/20),Math.max(-85,Math.floor(s*20)/20),Math.min(180,Math.ceil(e*20)/20),Math.min(85,Math.ceil(n*20)/20)] as [number,number,number,number]);
}
export function useAviationViewport(enabled: boolean, viewport: RendererViewport | null) {
  const bounds = useMemo(() => aviationQueryBounds(viewport), [viewport]);
  const zoom = viewport?.zoom ?? 0;
  const key = bounds.length ? `${Math.floor(zoom)}:${bounds.map(b=>b.join(',')).join('|')}` : '';
  const [payload,setPayload]=useState<AviationViewportPayload|null>(null);
  const [error,setError]=useState<string|null>(null);
  const generationRef=useRef(0);
  useEffect(()=>{
    const generation=++generationRef.current;
    if(!enabled || !key) {setPayload(null);setError(null);return;}
    const entry=viewportCache.get(key);
    const cached=entry && Date.now()-entry.storedAt <= 120_000 ? entry : undefined;
    setPayload(cached?.payload??null);setError(null);
    let disposed=false,controller:AbortController|null=null,timer:ReturnType<typeof setTimeout>|undefined;
    let expiryTimer: ReturnType<typeof setTimeout>|undefined;
    const expireSnapshot = () => {
      clearTimeout(expiryTimer);
      const saved=viewportCache.get(key);
      if(!saved)return;
      expiryTimer=setTimeout(()=>{
        if(disposed || generation!==generationRef.current)return;
        viewportCache.delete(key);setPayload(null);setError('Last aviation observation exceeds the 120 second retention budget');
      },Math.max(0,120_000-(Date.now()-saved.storedAt)));
    };
    if(cached)expireSnapshot();
    let failures=0,blocked=false,retryAfterMs=0;
    const refresh=async()=>{
      if(disposed||document.hidden||navigator.onLine===false||controller) return;
      const request=new AbortController();controller=request;
      try{
        const responses=await Promise.all(bounds.map(b=>fetchAviationViewport(b,zoom,request.signal)));
        if(disposed||request.signal.aborted||generation!==generationRef.current)return;
        if (responses.some(part => part.schemaVersion !== 'aviation-viewport.v1' || !Array.isArray(part.aircraft) || !['ok','empty','partial','unavailable'].includes(part.status))) {
          throw new Error('Invalid aviation viewport response');
        }
        if(responses.every(part=>part.status==='unavailable'))throw new Error(responses.flatMap(part=>part.limitations||[part.errorCode||'Aviation source unavailable']).join(' · '));
        const returned = responses.reduce((n,p) => n + p.aircraft.length, 0);
        const byId=new Map<string,AviationViewportPayload['aircraft'][number]>();
        for(const part of responses) for(const aircraft of part.aircraft||[]) {
          const lon=Number(aircraft.lon),lat=Number(aircraft.lat);
          if(aircraft.lon==null || aircraft.lat==null || aircraft.lon==='' || aircraft.lat==='' || !Number.isFinite(lon)||!Number.isFinite(lat)||lon < -180 || lon > 180 || lat < -90 || lat > 90)continue;
          const id=String(aircraft.icao24||aircraft.id||'');if(id)byId.set(id,aircraft);
        }
        const inView = [...byId.values()].filter(a => viewport!.bounds.some(([w,s,e,n]) => Number(a.lon)>=w && Number(a.lon)<=e && Number(a.lat)>=s && Number(a.lat)<=n)).length;
        const next={...(responses.find(part=>part.status!=='unavailable')||responses[0]!),aircraft:[...byId.values()],aircraftCount:byId.size,
          counts: {returned, valid: byId.size, inView},
          coverage: {complete: responses.every(p => p.status!=='unavailable' && p.coverage?.complete !== false), mode: responses.map(p => p.coverage?.mode).filter(Boolean).join(', '), sectorCount: responses.reduce((n,p) => n + (p.coverage?.sectorCount || 0),0)},
          availableAircraftCount:responses.reduce((n,p)=>n+(p.availableAircraftCount??p.aircraftCount),0),
          status:responses.some(p=>!['ok','empty'].includes(p.status))?'partial':byId.size?'ok':'empty',
          limitations:[...new Set(responses.flatMap(p=>p.limitations||[]))]};
        viewportCache.delete(key);viewportCache.set(key,{storedAt:Date.now(),payload:next});expireSnapshot();
        while(viewportCache.size>16)viewportCache.delete(viewportCache.keys().next().value!);
        setPayload(next);setError(null);failures=0;
      }catch(reason){
        if(disposed||request.signal.aborted||generation!==generationRef.current)return;
        failures++;blocked=reason instanceof ApiHttpError&&[401,403].includes(reason.status);retryAfterMs=reason instanceof ApiHttpError?reason.retryAfterMs||0:0;
        const retained=viewportCache.get(key);if(!retained || Date.now()-retained.storedAt>120_000)setPayload(null);
        setError(reason instanceof Error?reason.message:String(reason));
      }finally{
        if(controller===request)controller=null;
        if(!disposed&&!request.signal.aborted&&!document.hidden&&!blocked)timer=setTimeout(refresh,Math.max(retryAfterMs,Math.min(120_000,CACHE_TTL_MS*2**Math.min(failures,2))));
      }
    };
    const visibilityChanged=()=>{clearTimeout(timer);controller?.abort();controller=null;if(!document.hidden&&navigator.onLine!==false)timer=setTimeout(refresh,300);};
    document.addEventListener('visibilitychange',visibilityChanged);
    window.addEventListener('online',visibilityChanged);window.addEventListener('offline',visibilityChanged);
    timer=setTimeout(refresh,cached?Math.max(300,CACHE_TTL_MS-(Date.now()-cached.storedAt)):300);
    return()=>{disposed=true;clearTimeout(timer);clearTimeout(expiryTimer);controller?.abort();document.removeEventListener('visibilitychange',visibilityChanged);window.removeEventListener('online',visibilityChanged);window.removeEventListener('offline',visibilityChanged);};
  },[enabled,key]);
  const phase:AviationPhase=!enabled?'OFF':!viewport?'LOADING':zoom<2?'ZOOM_REQUIRED':error?(payload?'STALE':'UNAVAILABLE'):!payload?'LOADING':payload.status==='unavailable'?'UNAVAILABLE':!['ok','empty'].includes(payload.status)||payload.coverage?.complete===false||(payload.availableAircraftCount??payload.aircraftCount)>payload.aircraftCount?'PARTIAL':payload.aircraft.length?'READY':'EMPTY';
  return {payload,error,bbox:bounds[0]??null,phase,loading:phase==='LOADING'};
}
