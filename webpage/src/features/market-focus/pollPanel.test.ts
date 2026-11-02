import { afterEach, describe, expect, it, vi } from 'vitest';
import { pollPanel } from './pollPanel';

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

function setup() {
  vi.useFakeTimers();
  const document = Object.assign(new EventTarget(), { hidden: false });
  vi.stubGlobal('document', document);
  return document;
}

describe('panel polling budget', () => {
  it('does not overlap an outstanding read and discards its result after selection changes', async () => {
    setup();
    let finish!: (value: string) => void;
    const load = vi.fn(() => new Promise<string>((resolve) => { finish = resolve; }));
    const apply = vi.fn();
    const stop = pollPanel(load, apply, vi.fn(), 1000);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(load).toHaveBeenCalledTimes(1);
    stop(); finish('old market'); await Promise.resolve();
    expect(apply).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('honors failure backoff across tab visibility changes', async () => {
    const document = setup();
    const load = vi.fn(async () => { throw { retryAfterMs: 30_000 }; });
    const stop = pollPanel(load, vi.fn(), vi.fn(), 1000);
    await vi.advanceTimersByTimeAsync(100);
    for (let i = 0; i < 10; i++) {
      document.hidden = true; document.dispatchEvent(new Event('visibilitychange'));
      document.hidden = false; document.dispatchEvent(new Event('visibilitychange'));
    }
    await vi.advanceTimersByTimeAsync(29_000);
    expect(load).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(load).toHaveBeenCalledTimes(2);
    stop(); expect(vi.getTimerCount()).toBe(0);
  });
  it('pauses while hidden and resumes a single read', async () => {
    const document = setup();
    const load = vi.fn(async () => 'ok');
    const stop = pollPanel(load, vi.fn(), vi.fn(), 1000);
    document.hidden = true; document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(load).not.toHaveBeenCalled();
    document.hidden = false; document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(250);
    expect(load).toHaveBeenCalledTimes(1);
    stop();
  });
});
