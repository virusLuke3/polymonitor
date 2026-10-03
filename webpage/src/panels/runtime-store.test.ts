import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchPanelRuntimeData, mergeRuntimeData } from './runtime-store';
import { fetchRuntimePanels } from '@/services/api';
import type { PanelModule } from './types';
import { runtimePanelFromRenderer } from './definePanel';

vi.mock('@/services/api', () => ({ fetchRuntimePanels: vi.fn() }));
const panel = (id: string, fetchData = vi.fn().mockResolvedValue({ generatedAt: new Date().toISOString(), items: [id] })) => ({
  id, title: id, description: '', eyebrow: '', fetchData,
}) as PanelModule;
beforeEach(() => vi.clearAllMocks());

describe('runtime results', () => {
  it('uses each panel request limit for batches and their individual fallback with the same cancellation signal', async () => {
    const fetchData = vi.fn().mockResolvedValue({ generatedAt: new Date().toISOString(), items: ['source'] });
    const limited = (id: string, limit: number) => runtimePanelFromRenderer({
      [id]: { render: vi.fn() },
    }, { id, title: id, description: '', eyebrow: '' }, { tier: 'slow', limit, fetchData });
    const panels = [limited('a', 36), limited('b', 8)];
    const signal = new AbortController().signal;
    vi.mocked(fetchRuntimePanels).mockRejectedValue(new Error('Batch unavailable'));
    const result = await fetchPanelRuntimeData(panels, { signal, reason: 'refresh' });
    expect(fetchRuntimePanels).toHaveBeenCalledWith(['a', 'b'], { a: 36, b: 8 }, expect.any(AbortSignal));
    expect(fetchData).toHaveBeenNthCalledWith(1, { signal: expect.any(AbortSignal), reason: 'refresh' }, 36);
    expect(fetchData).toHaveBeenNthCalledWith(2, { signal: expect.any(AbortSignal), reason: 'refresh' }, 8);
    expect(Object.keys(result.data)).toEqual(['a', 'b']);
  });
  it('fetches dedicated endpoints through shared cancellation without batching their IDs', async () => {
    const dedicated = { ...panel('analysis'), batch: false };
    vi.mocked(fetchRuntimePanels).mockResolvedValue({ panels: { a: {}, b: {} }, errors: {}, metadata: {} } as any);
    const signal = new AbortController().signal;
    const result = await fetchPanelRuntimeData([panel('a'), dedicated, panel('b')], { signal, reason: 'manual' });
    expect(fetchRuntimePanels).toHaveBeenCalledWith(['a', 'b'], {}, expect.any(AbortSignal));
    expect(dedicated.fetchData).toHaveBeenCalledWith({ signal: expect.any(AbortSignal), reason: 'manual' });
    expect(result.data.analysis).toEqual({ generatedAt: expect.any(String), items: ['analysis'] });
  });
  it('retains independent successes from a partially failed batch', async () => {
    vi.mocked(fetchRuntimePanels).mockResolvedValue({ generatedAt: '2026-08-26T03:00:00Z', status: 'partial', requestId: 'fixture', panels: { a: { generatedAt: '2026-08-26T03:00:00Z', items: ['a'] } }, errors: { b: 'unavailable' }, metadata: {} });
    const result = await fetchPanelRuntimeData([panel('a'), panel('b')], { signal: new AbortController().signal, reason: 'refresh' });
    expect(result.data).toEqual({ a: { generatedAt: '2026-08-26T03:00:00Z', items: ['a'] } });
    expect(result.errors.b?.message).toBe('unavailable');
    expect(fetchRuntimePanels).toHaveBeenCalledTimes(1);
  });
  it('does not publish or continue an aborted individual request even when a provider ignores its signal', async () => {
    const controller = new AbortController();
    let finish!: (value: unknown) => void;
    const first = panel('a', vi.fn(() => new Promise((resolve) => { finish = resolve; })));
    const second = panel('b');
    const onPanelData = vi.fn();
    const request = fetchPanelRuntimeData([first, second], { signal: controller.signal, reason: 'refresh', maxBatchSize: 1, onPanelData });
    await Promise.resolve();
    controller.abort(); finish({ items: ['obsolete'] });
    const result = await request;
    expect(onPanelData).not.toHaveBeenCalled();
    expect(second.fetchData).not.toHaveBeenCalled();
    expect(result.data).toEqual({});
  });
  it('keeps the last useful snapshot on warming, but accepts authoritative empty data', () => {
    const previous = { a: { items: ['retained'] } };
    expect(mergeRuntimeData(previous, { a: { items: [], status: 'warming' } })).toEqual(previous);
    expect(mergeRuntimeData(previous, { a: { items: [], status: 'ok' } })).toEqual({ a: { items: [], status: 'ok' } });
  });
});

describe('bounded independent resource lifecycles', () => {
  it('releases a non-settling provider and suppresses its late response', async () => {
    vi.useFakeTimers();
    let finish!: (value: unknown) => void;
    let signal!: AbortSignal;
    const hung = { ...panel('hung', vi.fn(context => {
      signal = context.signal;
      return new Promise(resolve => { finish = resolve; });
    })), batch: false, refreshPolicy: { tier: 'fast', requestTimeoutMs: 50 } } as PanelModule;
    const onPanelSettled = vi.fn(), onPanelData = vi.fn();
    const resultPromise = fetchPanelRuntimeData([hung], { signal: new AbortController().signal, reason: 'interval', onPanelSettled, onPanelData });
    await vi.advanceTimersByTimeAsync(50);
    const result = await resultPromise;
    expect(result.errors.hung!.message).toContain('exceeded 50ms');
    expect(signal.aborted).toBe(true);
    expect(onPanelSettled).toHaveBeenCalledExactlyOnceWith('hung');
    finish({ generatedAt: new Date().toISOString(), items: ['obsolete'] });
    await Promise.resolve();
    expect(onPanelData).not.toHaveBeenCalled();
    vi.useRealTimers();
  });
  it('settles a successful resource independently while another is still running', async () => {
    vi.useFakeTimers();
    const slow = { ...panel('slow', vi.fn(() => new Promise(() => {}))), batch: false, refreshPolicy: { tier: 'fast', requestTimeoutMs: 100 } } as PanelModule;
    const fast = { ...panel('fast'), batch: false };
    const onPanelSettled = vi.fn();
    const request = fetchPanelRuntimeData([slow, fast], { signal: new AbortController().signal, reason: 'interval', onPanelSettled });
    await vi.advanceTimersByTimeAsync(1);
    expect(onPanelSettled.mock.calls).toEqual([['fast']]);
    await vi.advanceTimersByTimeAsync(100);
    expect((await request).data.fast).toBeDefined();
    vi.useRealTimers();
  });
  it('bounds the whole batch when the transport ignores cancellation', async () => {
    vi.useFakeTimers();
    vi.mocked(fetchRuntimePanels).mockImplementation(() => new Promise(() => {}));
    const entries = ['a', 'b'].map(id => ({ ...panel(id), refreshPolicy: { tier: 'slow', requestTimeoutMs: 100 } } as PanelModule));
    const request = fetchPanelRuntimeData(entries, { signal: new AbortController().signal, reason: 'interval' });
    await vi.advanceTimersByTimeAsync(100);
    expect(Object.keys((await request).errors)).toEqual(['a', 'b']);
    expect(vi.mocked(fetchRuntimePanels).mock.calls[0]![2]?.aborted).toBe(true);
    vi.useRealTimers();
  });
  it('keeps the shared transport alive when one resource loses demand', async () => {
    let finish!: (value: any) => void;
    vi.mocked(fetchRuntimePanels).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const a = new AbortController(), b = new AbortController();
    const request = fetchPanelRuntimeData([panel('a'), panel('b')], {
      signal: new AbortController().signal, panelSignals: { a: a.signal, b: b.signal }, reason: 'interval',
    });
    a.abort();
    await Promise.resolve(); await Promise.resolve();
    expect(vi.mocked(fetchRuntimePanels).mock.calls[0]![2]?.aborted).toBe(false);
    finish({ panels: { a: { generatedAt: new Date().toISOString() }, b: { generatedAt: new Date().toISOString(), items: ['kept'] } } });
    const result = await request;
    expect(result.data.b).toBeDefined(); expect(result.data.a).toBeUndefined();
  });
  it('applies domain validation to both batch responses and individual fallback', async () => {
    const entry = (id: string) => ({ ...panel(id), snapshot: {
      key: id, maxAgeMs: 1000, updatedAt: (value: any) => Date.parse(value.generatedAt),
      parse: (value: any) => { if (value.panelId !== id) throw new Error('Wrong identity'); return value; },
    } } as PanelModule);
    const a = entry('a'), b = entry('b');
    vi.mocked(fetchRuntimePanels).mockResolvedValue({ panels: {
      a: { panelId: 'wrong', generatedAt: new Date().toISOString() }, b: { panelId: 'b', generatedAt: new Date().toISOString(), items: [] },
    } } as any);
    const first = await fetchPanelRuntimeData([a, b], { signal: new AbortController().signal, reason: 'interval' });
    expect(first.errors.a!.message).toBe('Wrong identity'); expect(first.data.b).toBeDefined();
    vi.mocked(fetchRuntimePanels).mockRejectedValue(new Error('Route unavailable'));
    const second = await fetchPanelRuntimeData([a, b], { signal: new AbortController().signal, reason: 'interval' });
    expect(second.errors.a!.message).toBe('Wrong identity'); expect(second.errors.b!.message).toBe('Wrong identity');
  });
  it.each([{}, { generatedAt: 'bad' }, { generatedAt: new Date(Date.now() + 120_000).toISOString() }, { status: 'unavailable', generatedAt: new Date().toISOString(), items: [] }])('rejects unavailable or unknown-time successes: %j', async value => {
    const result = await fetchPanelRuntimeData([{ ...panel('a', vi.fn().mockResolvedValue(value)), batch: false }], { signal: new AbortController().signal, reason: 'interval' });
    expect(result.data.a).toBeUndefined(); expect(result.errors.a).toBeDefined();
  });
});
