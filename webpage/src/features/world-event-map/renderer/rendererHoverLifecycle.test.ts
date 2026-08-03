import { describe, expect, it, vi } from 'vitest';
import { DeckMapRenderer } from './DeckMapRenderer';
import { SvgMapRenderer } from './SvgMapRenderer';
import type { MapRendererCallbacks } from './MapRenderer';

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

  it('reduces aviation frame rate after an expensive dynamic commit and recovers gradually', () => {
    const renderer = new DeckMapRenderer() as unknown as {
      animationIntervalMs: number;
      animationRecoveryFrames: number;
      updateAdaptiveAnimationBudget: (frameCostMs: number) => void;
      destroy: () => void;
    };

    renderer.updateAdaptiveAnimationBudget(17);
    expect(renderer.animationIntervalMs).toBe(80);

    for (let frame = 0; frame < 29; frame += 1) renderer.updateAdaptiveAnimationBudget(4);
    expect(renderer.animationIntervalMs).toBe(80);
    expect(renderer.animationRecoveryFrames).toBe(29);

    renderer.updateAdaptiveAnimationBudget(4);
    expect(renderer.animationIntervalMs).toBe(40);
    expect(renderer.animationRecoveryFrames).toBe(0);
    renderer.destroy();
  });
});
