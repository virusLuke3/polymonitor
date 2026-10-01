import { describe, expect, it, vi } from 'vitest';
import { DeckMapRenderer } from './DeckMapRenderer';
import * as basemap from '@/config/weatherBasemap';
import { SvgMapRenderer } from './SvgMapRenderer';
import type { MapRendererCallbacks } from './MapRenderer';
import { defaultWorldEventMapState } from '../state/mapState';
import type { GeoEvent } from '../domain/types';

function callbacks(): MapRendererCallbacks {
  return {
    onCameraChange: vi.fn(),
    onEventSelect: vi.fn(),
    onCountrySelect: vi.fn(),
    onCountryContextMenu: vi.fn(),
    onBasemapStateChange: vi.fn(),
    onRendererFallbackRequested: vi.fn(),
    onError: vi.fn(),
  };
}

describe('renderer hover lifecycle', () => {
  it.each(['basemap', 'weather-radar', 'country-boundaries'])('bounds initial loading while only %s metadata is ready', (sourceId) => {
    const renderer = new DeckMapRenderer() as any;
    vi.useFakeTimers(); vi.stubGlobal('window', globalThis);
    renderer.map = {}; renderer.callbacks = callbacks(); renderer.applyLocalFallback = vi.fn();
    try {
      renderer.schedulePrimaryDeadline();
      renderer.handleSourceData({sourceId, sourceDataType:'metadata'});
      vi.advanceTimersByTime(10_000);
      expect(renderer.applyLocalFallback).toHaveBeenCalledTimes(sourceId==='basemap'?0:1);
      expect(renderer.callbacks.onBasemapStateChange).not.toHaveBeenCalledWith('primary-ready');
      if (sourceId==='basemap') {
        // More metadata does not renew the one-shot grace budget.
        renderer.handleSourceData({sourceId,sourceDataType:'metadata'});
        vi.advanceTimersByTime(10_000);
        expect(renderer.applyLocalFallback).toHaveBeenCalledTimes(1);
      }
    } finally {renderer.map=null;renderer.destroy();vi.useRealTimers();vi.unstubAllGlobals();}
  });

  it('mounts radar on a parsed style without waiting for unrelated source loading or animation idle', () => {
    const renderer = new DeckMapRenderer() as any;
    renderer.callbacks = { ...callbacks(), onRadarStateChange: vi.fn() };
    const addSource = vi.fn(), addLayer = vi.fn(), once = vi.fn();
    renderer.map = { isStyleLoaded: () => false, getStyle: () => ({layers:[]}), getSource: () => null,
      getLayer: () => null, addSource, addLayer, once };
    renderer.setRadar({ tiles: '/radar/{z}/{x}/{y}.png', coverageTiles: '/coverage/{z}/{x}/{y}.png' });
    expect(addSource.mock.calls.map(([id]) => id)).toEqual(['weather-radar', 'weather-radar-coverage']);
    expect(addLayer).toHaveBeenCalledTimes(2);
    expect(once).not.toHaveBeenCalled();
    expect(renderer.callbacks.onRadarStateChange).toHaveBeenCalledWith('loading');
    renderer.map = null; renderer.destroy();
  });
  it('checks event picking at the click position before claiming a country without prior hover', () => {
    const renderer = new DeckMapRenderer() as any;
    renderer.callbacks = callbacks();
    renderer.countryAtPoint = vi.fn(() => ({ iso2: 'US' }));
    const pickObject = vi.fn(() => ({ object: { kind: 'event-cluster' } }));
    renderer.overlay = { pickObject };
    renderer.handleCountryClick({ point: { x: 12, y: 34 } });
    expect(pickObject).toHaveBeenCalledWith({ x: 12, y: 34, radius: 8 });
    expect(renderer.countryAtPoint).not.toHaveBeenCalled();
    renderer.overlay = null; renderer.destroy();
  });
  it('retains picked event ownership between pointer down and click', () => {
    const renderer = new DeckMapRenderer() as any;
    renderer.callbacks = callbacks();
    renderer.hoveredDeckEventId = 'event:1'; renderer.deckHoverActive = true;
    renderer.countryAtPoint = vi.fn(() => ({ iso2: 'US' }));
    renderer.handlePointerDown();
    renderer.handleCountryClick({ point: { x: 10, y: 10 } });
    expect(renderer.hoveredDeckEventId).toBe('event:1');
    expect(renderer.countryAtPoint).not.toHaveBeenCalled();
    expect(renderer.callbacks.onCountrySelect).not.toHaveBeenCalled();
    renderer.destroy();
  });
  it('removes radar demand while its source is still loading', () => {
    const renderer = new DeckMapRenderer() as any;
    const removeSource = vi.fn(), removeLayer = vi.fn();
    renderer.map = { isStyleLoaded: () => false, getLayer: () => ({}), getSource: () => ({}), removeLayer, removeSource };
    renderer.setRadar(null);
    expect(removeSource.mock.calls.map(([id]) => id)).toEqual(['weather-radar', 'weather-radar-coverage', 'weather-radar-next', 'weather-radar-next-coverage']);
    expect(removeLayer).toHaveBeenCalledTimes(4);
    renderer.map = null; renderer.destroy();
  });
  it('does not persist the provisional camera before initial world fit', () => {
    const renderer = new DeckMapRenderer() as any;
    renderer.state = { ...defaultWorldEventMapState(), fitWorld: true };
    renderer.callbacks = callbacks(); renderer.map = {};
    renderer.handleMoveEnd();
    expect(renderer.callbacks.onCameraChange).not.toHaveBeenCalled();
    renderer.map = null; renderer.destroy();
  });
  it('does not declare the local fallback ready before country geometry loads', () => {
    const onBasemapStateChange = vi.fn();
    const renderer = new DeckMapRenderer() as unknown as {
      callbacks: MapRendererCallbacks;
      fallbackApplied: boolean;
      map: { getSource: () => object; isSourceLoaded: () => boolean };
      markLocalFallbackReadyIfLoaded: () => boolean;
      destroy: () => void;
    };
    renderer.callbacks = { ...callbacks(), onBasemapStateChange };
    renderer.fallbackApplied = true;
    renderer.map = {
      getSource: () => ({}),
      isSourceLoaded: () => false,
    };

    expect(renderer.markLocalFallbackReadyIfLoaded()).toBe(false);
    expect(onBasemapStateChange).not.toHaveBeenCalledWith('local-fallback-ready');
    renderer.map = null as never;
    renderer.destroy();
  });

  it('declares the local fallback ready after country geometry loads', () => {
    const onBasemapStateChange = vi.fn();
    const renderer = new DeckMapRenderer() as unknown as {
      callbacks: MapRendererCallbacks;
      fallbackApplied: boolean;
      map: { getSource: () => object; isSourceLoaded: () => boolean };
      markLocalFallbackReadyIfLoaded: () => boolean;
      destroy: () => void;
    };
    renderer.callbacks = { ...callbacks(), onBasemapStateChange };
    renderer.fallbackApplied = true;
    renderer.map = {
      getSource: () => ({}),
      isSourceLoaded: () => true,
    };

    expect(renderer.markLocalFallbackReadyIfLoaded()).toBe(true);
    expect(onBasemapStateChange).toHaveBeenCalledWith('local-fallback-ready');
    renderer.map = null as never;
    renderer.destroy();
  });

  it('keeps a loaded primary basemap when an individual tile fails later', () => {
    const onError = vi.fn();
    const renderer = new DeckMapRenderer() as unknown as {
      callbacks: MapRendererCallbacks;
      fallbackApplied: boolean;
      handleMapError: (event: { error?: Error; message?: string }) => void;
      destroy: () => void;
    };
    renderer.callbacks = { ...callbacks(), onError };
    renderer.handleMapError({ message: 'Tile network request failed' });
    renderer.handleMapError({ message: 'Glyph fetch network request failed' });

    expect(renderer.fallbackApplied).toBe(false);
    expect(onError).toHaveBeenCalledTimes(2);
    renderer.destroy();
  });

  it('quarantines only the failed deck layer and reports an explicit degraded state', () => {
    const onLayerDegraded = vi.fn();
    const onError = vi.fn();
    const renderer = new DeckMapRenderer() as unknown as {
      callbacks: MapRendererCallbacks;
      quarantinedLayerIds: Set<string>;
      handleDeckLayerError: (error: Error, layer?: { id: string }) => void;
      destroy: () => void;
    };
    renderer.callbacks = { ...callbacks(), onLayerDegraded, onError };

    const failure = new Error('fixture shader failure');
    renderer.handleDeckLayerError(failure, { id: 'world-event-points' });
    renderer.handleDeckLayerError(failure, { id: 'world-event-points' });

    expect(renderer.quarantinedLayerIds).toEqual(new Set(['world-event-points']));
    expect(onLayerDegraded).toHaveBeenCalledOnce();
    expect(onLayerDegraded).toHaveBeenCalledWith('world-event-points', failure);
    expect(onError).toHaveBeenCalledOnce();
    renderer.destroy();
  });

  it('lets retryable PMTiles resources recover before the readiness timeout', () => {
    const onError = vi.fn();
    const renderer = new DeckMapRenderer() as unknown as {
      callbacks: MapRendererCallbacks;
      fallbackApplied: boolean;
      handleMapError: (event: { error?: Error; message?: string }) => void;
      destroy: () => void;
    };
    renderer.callbacks = { ...callbacks(), onError };
    renderer.handleMapError({ message: 'Tile network request failed' });
    renderer.handleMapError({ message: 'Glyph fetch network request failed' });

    expect(renderer.fallbackApplied).toBe(false);
    expect(onError).toHaveBeenCalledTimes(2);
    renderer.destroy();
  });

  it('clears Deck hover locally when a map drag starts', () => {
    const off = vi.fn();
    const sync = vi.fn();
    const canvas = { style: { visibility: '' } } as HTMLCanvasElement;
    const renderer = new DeckMapRenderer() as unknown as {
      callbacks: MapRendererCallbacks;
      map: {
        off: (event: string, callback: () => void) => void;
        getLayer: () => undefined;
        getCanvas: () => { classList: { toggle: () => void } };
      };
      aviationOverlay: { getCanvas: () => HTMLCanvasElement };
      aviationOverlayViewSync: () => void;
      hoveredDeckEventId: string | null;
      deckHoverActive: boolean;
      handleMoveStart: () => void;
    };
    renderer.callbacks = callbacks();
    renderer.map = {
      off,
      getLayer: () => undefined,
      getCanvas: () => ({ classList: { toggle: vi.fn() } }),
    };
    renderer.aviationOverlay = { getCanvas: () => canvas };
    renderer.aviationOverlayViewSync = sync;
    renderer.hoveredDeckEventId = 'event:1';
    renderer.deckHoverActive = true;

    renderer.handleMoveStart();

    expect(renderer.hoveredDeckEventId).toBeNull();
    expect(renderer.deckHoverActive).toBe(false);
    // Drag start stops the motion clock but preserves the mounted camera
    // listener and the last observed aircraft positions.
    expect(off).not.toHaveBeenCalled();
    expect(sync).not.toHaveBeenCalled();
    expect(canvas.style.visibility).toBe('');
  });

  it('does not require App hover state during Deck destruction', () => {
    const renderer = new DeckMapRenderer() as unknown as {
      callbacks: MapRendererCallbacks | null;
      hoveredDeckEventId: string | null;
      destroy: () => void;
    };
    renderer.callbacks = callbacks();
    renderer.hoveredDeckEventId = 'event:1';

    renderer.destroy();

    expect(renderer.callbacks).toBeNull();
  });

  it('keeps animated aircraft hover and click without a second GPU picking pass', () => {
    const onEventSelect = vi.fn();
    const show = vi.fn();
    const flight = {
      id: 'flight:cpu-pick',
      category: 'infrastructure',
      title: 'PX 204',
      severity: 'watch',
      geometry: { type: 'LineString', coordinates: [[0, 0], [2, 2]] },
      locationPrecision: 'exact',
      sources: [{ provider: 'fixture' }],
      limitations: [],
      relatedMarketIds: [],
      properties: { mapEntity: 'air-flight', flightId: 'PX204' },
    } as GeoEvent;
    const renderer = new DeckMapRenderer() as unknown as {
      callbacks: MapRendererCallbacks;
      map: {
        project: () => { x: number; y: number };
        getCanvas: () => { classList: { toggle: () => void } };
      };
      seededAircraftPickPoints: Array<{
        id: string;
        event: GeoEvent;
        position: [number, number];
        color: [number, number, number, number];
        angle: number;
        size: number;
        count: number;
      }>;
      manualAviationTooltip: { show: typeof show; clear: () => void; destroy: () => void };
      hoveredDeckEventId: string | null;
      handleManualAviationHover: (event: { point: { x: number; y: number } }) => void;
      handleManualAviationClick: () => void;
      destroy: () => void;
    };
    renderer.callbacks = { ...callbacks(), onEventSelect };
    renderer.map = {
      project: () => ({ x: 20, y: 20 }),
      getCanvas: () => ({ classList: { toggle: vi.fn() } }),
    };
    renderer.seededAircraftPickPoints = [{
      id: 'PX204',
      event: flight,
      position: [1, 1],
      color: [92, 241, 255, 170],
      angle: 45,
      size: 14,
      count: 1,
    }];
    renderer.manualAviationTooltip = { show, clear: vi.fn(), destroy: vi.fn() };

    renderer.handleManualAviationHover({ point: { x: 24, y: 23 } });
    expect(renderer.hoveredDeckEventId).toBe(flight.id);
    expect(show).toHaveBeenCalled();
    renderer.handleManualAviationClick();
    expect(onEventSelect).toHaveBeenCalledWith(flight.id);

    renderer.map = null as never;
    renderer.destroy();
  });

  it('does not rebuild disaster and geometry layers for an aviation-only refresh', () => {
    const hazard = {
      id: 'hazard:stable',
      sources: [{ provider: 'fixture' }],
      category: 'natural-hazard',
      severity: 'warning',
      geometry: { type: 'Point', coordinates: [10, 10] },
      properties: {},
    } as GeoEvent;
    const flight = (id: string) => ({
      id,
      category: 'infrastructure',
      title: id,
      severity: 'info',
      geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] },
      locationPrecision: 'exact',
      sources: [{ provider: 'fixture' }],
      limitations: [],
      relatedMarketIds: [],
      properties: { mapEntity: 'air-flight' },
    }) as GeoEvent;
    const previousPointLayers = [{}];
    const previousGeometryLayers = [{}];
    const renderer = new DeckMapRenderer() as unknown as {
      events: GeoEvent[];
      pointLayers: object[];
      geometryLayers: object[];
      geometryNeedsCommit: boolean;
      aviationLayerSections: object | null;
      setEvents: (events: GeoEvent[]) => void;
      destroy: () => void;
    };
    renderer.events = [hazard, flight('flight:old')];
    renderer.pointLayers = previousPointLayers;
    renderer.geometryLayers = previousGeometryLayers;
    renderer.geometryNeedsCommit = false;
    renderer.aviationLayerSections = {};

    renderer.setEvents([hazard, flight('flight:new')]);

    expect(renderer.pointLayers).toBe(previousPointLayers);
    expect(renderer.geometryLayers).toBe(previousGeometryLayers);
    expect(renderer.geometryNeedsCommit).toBe(false);
    expect(renderer.aviationLayerSections).toBeNull();
    renderer.destroy();
  });

  it('clears and destroys the renderer-owned SVG tooltip', () => {
    const clear = vi.fn();
    const destroyTooltip = vi.fn();
    const renderer = new SvgMapRenderer() as unknown as {
      callbacks: MapRendererCallbacks | null;
      tooltip: { clear: () => void; destroy: () => void };
      pause: () => void;
      destroy: () => void;
    };
    renderer.callbacks = callbacks();
    renderer.tooltip = { clear, destroy: destroyTooltip };

    renderer.pause();
    renderer.destroy();

    expect(clear).toHaveBeenCalled();
    expect(destroyTooltip).toHaveBeenCalled();
    expect(renderer.callbacks).toBeNull();
  });

  it('reduces aviation frame rate after a delayed RAF and recovers gradually', () => {
    const renderer = new DeckMapRenderer() as unknown as {
      animationIntervalMs: number;
      animationRecoveryFrames: number;
      updateAdaptiveAnimationBudget: (frameCostMs: number) => void;
      destroy: () => void;
    };

    renderer.updateAdaptiveAnimationBudget(25);
    expect(renderer.animationIntervalMs).toBe(80);

    for (let frame = 0; frame < 59; frame += 1) renderer.updateAdaptiveAnimationBudget(16);
    expect(renderer.animationIntervalMs).toBe(80);
    expect(renderer.animationRecoveryFrames).toBe(59);

    renderer.updateAdaptiveAnimationBudget(16);
    expect(renderer.animationIntervalMs).toBe(40);
    expect(renderer.animationRecoveryFrames).toBe(0);
    renderer.destroy();
  });

  it('uses the shared animation clock only for recent events and stops during interaction', () => {
    const requestAnimationFrame = vi.fn(() => 41);
    const cancelAnimationFrame = vi.fn();
    vi.stubGlobal('window', { location: { search: '' }, requestAnimationFrame, cancelAnimationFrame });
    const critical = {
      id: 'earthquake:critical',
      category: 'natural-hazard',
      title: 'Critical earthquake',
      severity: 'critical',
      geometry: { type: 'Point', coordinates: [10, 10] },
      locationPrecision: 'exact',
      sources: [{ provider: 'fixture' }],
      limitations: [],
      relatedMarketIds: [],
      properties: {},
      hazardKind: 'earthquake',
      lifecycle: 'active',
      coverage: { scope: 'global', label: 'fixture', isComplete: false, gaps: [] },
      severityEvidence: { provider: 'fixture', mappingVersion: 'fixture', reason: 'fixture' },
      revision: { nativeEventId: 'critical' },
      metrics: { kind: 'earthquake', magnitude: 6.2 },
    } as GeoEvent;
    const renderer = new DeckMapRenderer() as unknown as {
      overlay: object;
      state: ReturnType<typeof defaultWorldEventMapState>;
      events: GeoEvent[];
      pulseEvents: GeoEvent[];
      eventFirstSeenAt: Map<string, number>;
      animationFrame: number | null;
      interacting: boolean;
      syncAnimationLoop: () => void;
      destroy: () => void;
    };
    renderer.overlay = {};
    renderer.state = defaultWorldEventMapState();
    renderer.events = [critical];
    renderer.pulseEvents = [critical];
    renderer.eventFirstSeenAt = new Map([[critical.id, Date.now()]]);

    renderer.syncAnimationLoop();
    expect(requestAnimationFrame).toHaveBeenCalledWith(expect.any(Function));
    expect(renderer.animationFrame).toBe(41);

    renderer.interacting = true;
    renderer.syncAnimationLoop();
    expect(cancelAnimationFrame).toHaveBeenCalledWith(41);
    expect(renderer.animationFrame).toBeNull();
    renderer.destroy();
    vi.unstubAllGlobals();
  });

  it('renders the static map without allocating an aviation overlay', () => {
    const request = vi.fn();
    const renderer = new DeckMapRenderer() as unknown as {
      overlay: object;
      aviationOverlay: object | null;
      state: ReturnType<typeof defaultWorldEventMapState>;
      renderScheduler: { request: typeof request; cancel: () => void };
      requestRender: (invalidation: { points: boolean }) => void;
      destroy: () => void;
    };
    renderer.overlay = {};
    renderer.aviationOverlay = null;
    renderer.state = defaultWorldEventMapState();
    renderer.renderScheduler = { request, cancel: vi.fn() };

    renderer.requestRender({ points: true });

    expect(request).toHaveBeenCalledWith({ points: true });
    expect(renderer.aviationOverlay).toBeNull();
    renderer.destroy();
  });

  it('commits static labels atomically so cached Deck layers are never finalized and reinserted', () => {
    const setProps = vi.fn();
    const events = Array.from({ length: 6 }, (_, index) => ({
      id: `earthquake:cluster:${index}`,
      category: 'natural-hazard',
      title: `Earthquake ${index}`,
      severity: 'critical',
      geometry: { type: 'Point', coordinates: [10 + index * 0.02, 10 + index * 0.02] },
      locationPrecision: 'exact',
      sources: [{ provider: 'fixture', nativeId: String(index) }],
      limitations: [],
      relatedMarketIds: [],
      properties: { mapEntity: 'hazard-event' },
      hazardKind: 'earthquake',
      lifecycle: 'active',
      coverage: { scope: 'global', label: 'fixture', isComplete: false, gaps: [] },
      severityEvidence: { provider: 'fixture', mappingVersion: 'fixture', reason: 'fixture' },
      revision: { nativeEventId: String(index) },
      metrics: { kind: 'earthquake', magnitude: 6.4 },
    })) as GeoEvent[];
    const renderer = new DeckMapRenderer() as unknown as {
      overlay: { setProps: typeof setProps };
      state: ReturnType<typeof defaultWorldEventMapState>;
      events: GeoEvent[];
      clusterIndex: { update: (items: GeoEvent[]) => void };
      flushRender: (invalidation: {
        points: boolean;
        aviation: boolean;
        geometry: boolean;
        dynamic: boolean;
        pulse: boolean;
        interaction: boolean;
      }) => void;
      destroy: () => void;
    };
    renderer.overlay = { setProps };
    renderer.state = {
      ...defaultWorldEventMapState(),
      activeLayerIds: ['earthquakes-volcanoes'],
    };
    renderer.events = events;
    renderer.clusterIndex.update(events);

    renderer.flushRender({
      points: true,
      aviation: false,
      geometry: false,
      dynamic: false,
      pulse: false,
      interaction: false,
    });

    expect(setProps).toHaveBeenCalledTimes(1);
    const committed = setProps.mock.calls[0]?.[0]?.layers as Array<{ id: string }>;
    expect(committed.map((layer) => layer.id)).toContain('world-event-cluster-counts');
    renderer.destroy();
  });
});

for (const Renderer of [DeckMapRenderer, SvgMapRenderer]) {
  it(`${Renderer.name} treats provider bootstrap and historical records as static, then cues only a new arrival`, () => {
    const now = Date.now();
    const event = (id: string, provider = 'USGS', occurred = now): GeoEvent => ({
      id, title: id, category: 'natural-hazard', severity: 'critical',
      geometry: { type: 'Point', coordinates: [10, 20] }, locationPrecision: 'exact',
      occurredAt: new Date(occurred).toISOString(), sources: [{ provider }],
      properties: {}, limitations: [], relatedMarketIds: [],
    });
    const renderer = new Renderer() as unknown as { paused: boolean; setEvents: (events: GeoEvent[]) => void; eventFirstSeenAt: Map<string, number>; destroy: () => void };
    renderer.paused = true; // Exercise arrival classification independently of a mounted DOM.
    const initial = event('initial');
    renderer.setEvents([initial]);
    expect(renderer.eventFirstSeenAt.size).toBe(0);
    const otherProvider = event('other-source', 'EONET');
    renderer.setEvents([initial, otherProvider]);
    expect(renderer.eventFirstSeenAt.size).toBe(0);
    const arrival = event('new');
    renderer.setEvents([initial, otherProvider, arrival, event('historical', 'USGS', now - 600_000)]);
    expect([...renderer.eventFirstSeenAt.keys()]).toEqual(['new']);
    renderer.setEvents([initial]);
    renderer.setEvents([initial, arrival]);
    expect(renderer.eventFirstSeenAt.size).toBe(0);
    renderer.destroy();
  });
}

it('V3 layer fuse rejects the SAME toxic data but accepts a fresh corrected version once',()=>{
  const renderer=new DeckMapRenderer() as any;
  renderer.callbacks=callbacks();renderer.callbacks.onLayerRecovered=vi.fn();
  const layer={id:'world-event-points',props:{data:[{id:'bad',geometry:null}]}};
  renderer.handleDeckLayerError(new Error('bad feature'),layer);
  expect(renderer.acceptLayerVersion({...layer,props:{data:[{id:'bad',geometry:null}]}})).toBe(false);
  const fixed={id:layer.id,props:{data:[{id:'bad',geometry:{type:'Point',coordinates:[1,2]}}]}};
  expect(renderer.acceptLayerVersion(fixed)).toBe(true);
  expect(renderer.acceptLayerVersion(fixed)).toBe(true);
  expect(renderer.callbacks.onLayerRecovered).toHaveBeenCalledOnce();renderer.destroy();
});

it('V3 radar commits only a complete visible frame and retains the previous frame on error',()=>{
  const renderer=new DeckMapRenderer() as any;renderer.callbacks=callbacks();renderer.callbacks.onRadarStateChange=vi.fn();
  let loaded=false;const layers=new Set<string>(),sources=new Set<string>();
  renderer.map={isStyleLoaded:()=>true,getStyle:()=>({layers:[]}),getLayer:(id:string)=>layers.has(id),getSource:(id:string)=>sources.has(id),
    addSource:(id:string)=>sources.add(id),addLayer:(l:any)=>layers.add(l.id),removeLayer:(id:string)=>layers.delete(id),removeSource:(id:string)=>sources.delete(id),
    isSourceLoaded:()=>loaded,setPaintProperty:vi.fn()};
  const first={time:100,tiles:'first',coverageTiles:'coverage'};renderer.setRadar(first);renderer.commitRadarIfReady();
  expect(renderer.radarAppliedUrl).toBe('');loaded=true;renderer.commitRadarIfReady();expect(renderer.radarAppliedUrl).toBe('first');
  loaded=false;renderer.setRadar({time:200,tiles:'second',coverageTiles:'coverage'});renderer.commitRadarIfReady();expect(renderer.radarAppliedUrl).toBe('first');
  vi.stubGlobal('window',globalThis);renderer.handleMapError({sourceId:'weather-radar-next',message:'503'});
  expect(renderer.radarAppliedUrl).toBe('first');expect(renderer.radarPending).toBeNull();
  renderer.applyRadar();loaded=true;renderer.commitRadarIfReady();expect(renderer.radarAppliedUrl).toBe('second');
  renderer.map=null;renderer.destroy();vi.unstubAllGlobals();
});

it('V3 a single missing tile has a bounded source retry, pauses, then recovers without replacing the GPU',async()=>{
  vi.useFakeTimers();
  const renderer=new DeckMapRenderer() as any;vi.stubGlobal('window',globalThis);renderer.callbacks={...callbacks(),onBasemapIssueChange:vi.fn()};
  renderer.map={refreshTiles:vi.fn()};renderer.primaryHasContent=true;
  const tile={x:5,y:3,z:3};
  renderer.handleMapError({sourceId:'basemap',tile:{tileID:{canonical:tile}},message:'tile controlled 503'});
  expect(renderer.callbacks.onRendererFallbackRequested).not.toHaveBeenCalled();
  renderer.paused=true;vi.advanceTimersByTime(30_000);expect(renderer.map.refreshTiles).not.toHaveBeenCalled();
  const reset=vi.spyOn(basemap,'resetWorldEventPMTilesArchive').mockResolvedValue(undefined);
  renderer.paused=false;renderer.scheduleMissingTileRecovery();await vi.advanceTimersByTimeAsync(30_000);
  expect(renderer.map.refreshTiles).toHaveBeenCalledWith('basemap',[tile]);
  renderer.markPrimaryReady=vi.fn();renderer.handleSourceData({sourceId:'basemap',tile:{state:'loaded',tileID:{canonical:tile}}});
  expect(renderer.missingBaseTiles.size).toBe(0);expect(renderer.callbacks.onBasemapIssueChange).toHaveBeenLastCalledWith(null);
  renderer.map=null;renderer.destroy();reset.mockRestore();vi.useRealTimers();vi.unstubAllGlobals();
});


it('keeps committed geometry alive across repeated offscreen pauses and resumes the aircraft clock', () => {
  const renderer = new DeckMapRenderer() as any;
  const layers = [{ id: 'world-event-paths' }, { id: 'world-event-country-risk' }];
  const setProps = vi.fn();
  const stop = vi.fn(), start = vi.fn(), sync = vi.fn();
  renderer.overlay = { setProps };
  renderer.geometryLayers = layers;
  renderer.aviationOverlay = { getCanvas: () => ({ style: {} }), _deck: { animationLoop: { stop, start } } };
  renderer.aviationOverlayViewSync = sync;
  renderer.resize = vi.fn(); renderer.applyRadar = vi.fn();
  renderer.requestRender = vi.fn(); renderer.syncAnimationLoop = vi.fn();
  for (let i = 0; i < 3; i++) {
    renderer.pause(); renderer.pause();
    expect(renderer.geometryLayers).toBe(layers);
    expect(setProps).not.toHaveBeenCalled(); // Removing layers finalizes their GPU instances.
    renderer.resume();
  }
  expect(stop).toHaveBeenCalledTimes(3);
  expect(start).toHaveBeenCalledTimes(3);
  expect(sync).toHaveBeenCalledTimes(3);
  renderer.overlay = null; renderer.aviationOverlay = null; renderer.destroy();
});


it('discards finalized geometry instances after actual context loss', () => {
  const renderer = new DeckMapRenderer() as any;
  vi.stubGlobal('window', globalThis); vi.useFakeTimers();
  renderer.geometryLayers = [{ id: 'world-event-paths' }];
  renderer.pointLayers = [{ id: 'world-event-points' }];
  renderer.aviationLayerSections = { routes: [] };
  renderer.overlay = { setProps: vi.fn() };
  renderer.handleContextLost({ preventDefault: vi.fn() });
  expect(renderer.overlay.setProps).toHaveBeenCalledWith({ layers: [] });
  expect(renderer.geometryLayers).toEqual([]);
  expect(renderer.pointLayers).toBeNull();
  expect(renderer.aviationLayerSections).toBeNull();
  renderer.overlay = null; renderer.destroy(); vi.useRealTimers(); vi.unstubAllGlobals();
});
