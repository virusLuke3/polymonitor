import { describe, expect, it, vi } from 'vitest';
import { DeckMapRenderer } from './DeckMapRenderer';
import { SvgMapRenderer } from './SvgMapRenderer';
import type { MapRendererCallbacks } from './MapRenderer';

function callbacks(onEventHover = vi.fn(), onHoverTooltip = vi.fn()): MapRendererCallbacks {
  return {
    onCameraChange: vi.fn(),
    onEventSelect: vi.fn(),
    onEventHover,
    onHoverTooltip,
    onBasemapStateChange: vi.fn(),
    onRendererFallbackRequested: vi.fn(),
    onError: vi.fn(),
  };
}

describe('renderer hover lifecycle', () => {
  it('clears Deck event hover when a map drag starts', () => {
    const onEventHover = vi.fn();
    const renderer = new DeckMapRenderer() as unknown as {
      callbacks: MapRendererCallbacks;
      hoveredDeckEventId: string | null;
      deckHoverActive: boolean;
      handleMoveStart: () => void;
    };
    renderer.callbacks = callbacks(onEventHover);
    renderer.hoveredDeckEventId = 'event:1';
    renderer.deckHoverActive = true;

    renderer.handleMoveStart();

    expect(onEventHover).toHaveBeenCalledWith(null);
    expect(renderer.hoveredDeckEventId).toBeNull();
    expect(renderer.deckHoverActive).toBe(false);
  });

  it('notifies external hover state before Deck destruction clears callbacks', () => {
    const onEventHover = vi.fn();
    const renderer = new DeckMapRenderer() as unknown as {
      callbacks: MapRendererCallbacks | null;
      hoveredDeckEventId: string | null;
      destroy: () => void;
    };
    renderer.callbacks = callbacks(onEventHover);
    renderer.hoveredDeckEventId = 'event:1';

    renderer.destroy();

    expect(onEventHover).toHaveBeenCalledWith(null);
    expect(renderer.callbacks).toBeNull();
  });

  it('clears SVG event and custom tooltip state on pause and destroy', () => {
    const onEventHover = vi.fn();
    const onHoverTooltip = vi.fn();
    const renderer = new SvgMapRenderer() as unknown as {
      callbacks: MapRendererCallbacks | null;
      pause: () => void;
      destroy: () => void;
    };
    renderer.callbacks = callbacks(onEventHover, onHoverTooltip);

    renderer.pause();
    renderer.destroy();

    expect(onEventHover).toHaveBeenCalledWith(null);
    expect(onHoverTooltip).toHaveBeenCalledWith(null);
    expect(renderer.callbacks).toBeNull();
  });
});
