import { afterEach, describe, expect, it, vi } from 'vitest';
import { rectIntersectsViewport, selectionPanOffset } from './rendererVisibility';

const rect = (overrides: Partial<DOMRectReadOnly> = {}) => ({
  top: 100,
  right: 500,
  bottom: 500,
  left: 100,
  width: 400,
  height: 400,
  ...overrides,
});

describe('renderer visibility', () => {
  afterEach(() => vi.unstubAllGlobals());
  it('recognizes a map that is already visible before IntersectionObserver reports', () => {
    expect(rectIntersectsViewport(rect(), 1920, 1080)).toBe(true);
  });

  it('rejects zero-sized and fully offscreen hosts', () => {
    expect(rectIntersectsViewport(rect({ width: 0 }), 1920, 1080)).toBe(false);
    expect(rectIntersectsViewport(rect({ top: 1200, bottom: 1600 }), 1920, 1080)).toBe(false);
    expect(rectIntersectsViewport(rect({ right: -1, left: -401 }), 1920, 1080)).toBe(false);
  });

  it('accepts a partially visible map host', () => {
    expect(rectIntersectsViewport(rect({ top: -300, bottom: 100 }), 1920, 1080)).toBe(true);
  });

  it('moves selection only enough to clear the desktop report', () => {
    vi.stubGlobal('innerWidth', 1440); vi.stubGlobal('innerHeight', 900);
    const host = { getBoundingClientRect: () => rect({ left: 0, top: 100, width: 1440, height: 620 }),
      closest: () => ({ querySelectorAll: () => [{ getBoundingClientRect: () => rect({ left: 1020, top: 116, width: 400, height: 500 }) }] }) } as unknown as HTMLElement;
    expect(selectionPanOffset(host, { x: 1100, y: 300 })).toEqual({ x: 104, y: 0 });
    expect(selectionPanOffset(host, { x: 500, y: 300 })).toEqual({ x: 0, y: 0 });
  });

  it('keeps selection in the visible strip above a fixed mobile report', () => {
    vi.stubGlobal('innerWidth', 390); vi.stubGlobal('innerHeight', 844);
    const host = { getBoundingClientRect: () => rect({ left: 0, top: -100, width: 390, height: 620 }),
      closest: () => ({ querySelectorAll: () => [{ getBoundingClientRect: () => rect({ left: 10, top: 300, width: 370, height: 464 }) }] }) } as unknown as HTMLElement;
    expect(selectionPanOffset(host, { x: 200, y: 500 })).toEqual({ x: 0, y: 124 });
    expect(selectionPanOffset(host, { x: 200, y: 20 })).toEqual({ x: 0, y: -96 });
  });
});
