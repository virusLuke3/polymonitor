import { describe, expect, it, vi } from 'vitest';
import { DeckMapRenderer } from './DeckMapRenderer';
import { SvgMapRenderer } from './SvgMapRenderer';
import type { MapRendererCallbacks } from './MapRenderer';
import { defaultWorldEventMapState } from '../state/mapState';
import type { GeoEvent } from '../domain/types';

function callbacks(): MapRendererCallbacks {
  return {
    onCameraChange: vi.fn(),
    onEventSelect: vi.fn(),
    onBasemapStateChange: vi.fn(),
    onRendererFallbackRequested: vi.fn(),
    onError: vi.fn(),
  };
}

describe('renderer hover lifecycle', () => {
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

  it('clears Deck hover locally when a map drag starts', () => {
    const renderer = new DeckMapRenderer() as unknown as {
      callbacks: MapRendererCallbacks;
      hoveredDeckEventId: string | null;
      deckHoverActive: boolean;
      handleMoveStart: () => void;
    };
    renderer.callbacks = callbacks();
    renderer.hoveredDeckEventId = 'event:1';
    renderer.deckHoverActive = true;

    renderer.handleMoveStart();

    expect(renderer.hoveredDeckEventId).toBeNull();
    expect(renderer.deckHoverActive).toBe(false);
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

    for (let frame = 0; frame < 599; frame += 1) renderer.updateAdaptiveAnimationBudget(16);
    expect(renderer.animationIntervalMs).toBe(80);
    expect(renderer.animationRecoveryFrames).toBe(599);

    renderer.updateAdaptiveAnimationBudget(16);
    expect(renderer.animationIntervalMs).toBe(40);
    expect(renderer.animationRecoveryFrames).toBe(0);
    renderer.destroy();
  });

  it('runs hazard pulses on a separate 500ms clock and stops it during interaction', () => {
    const setInterval = vi.fn(() => 41);
    const clearInterval = vi.fn();
    vi.stubGlobal('window', { location: { search: '' }, setInterval, clearInterval });
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
      aviationOverlay: object;
      state: ReturnType<typeof defaultWorldEventMapState>;
      events: GeoEvent[];
      pulseEvents: GeoEvent[];
      eventFirstSeenAt: Map<string, number>;
      hazardPulseTimer: number | null;
      interacting: boolean;
      syncHazardPulseLoop: () => void;
      destroy: () => void;
    };
    renderer.overlay = {};
    renderer.aviationOverlay = {};
    renderer.state = defaultWorldEventMapState();
    renderer.events = [critical];
    renderer.pulseEvents = [critical];
    renderer.eventFirstSeenAt = new Map();

    renderer.syncHazardPulseLoop();
    expect(setInterval).toHaveBeenCalledWith(expect.any(Function), 500);
    expect(renderer.hazardPulseTimer).toBe(41);

    renderer.interacting = true;
    renderer.syncHazardPulseLoop();
    expect(clearInterval).toHaveBeenCalledWith(41);
    expect(renderer.hazardPulseTimer).toBeNull();
    renderer.destroy();
    vi.unstubAllGlobals();
  });
});
