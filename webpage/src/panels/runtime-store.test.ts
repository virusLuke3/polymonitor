import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchPanelRuntimeData, mergeRuntimeData } from './runtime-store';
import { fetchRuntimePanels } from '@/services/api';
import type { PanelModule } from './types';
import { runtimePanelFromRenderer } from './definePanel';

vi.mock('@/services/api', () => ({ fetchRuntimePanels: vi.fn() }));
const panel = (id: string, fetchData = vi.fn().mockResolvedValue({ items: [id] })) => ({
  id, title: id, description: '', eyebrow: '', fetchData,
}) as PanelModule;
beforeEach(() => vi.clearAllMocks());

describe('runtime results', () => {
  it('uses each panel request limit for batches and their individual fallback with the same cancellation signal', async () => {
    const fetchData = vi.fn().mockResolvedValue({ items: ['source'] });
    const limited = (id: string, limit: number) => runtimePanelFromRenderer({
      [id]: { render: vi.fn() },
    }, { id, title: id, description: '', eyebrow: '' }, { tier: 'slow', limit, fetchData });
    const panels = [limited('a', 36), limited('b', 8)];
    const signal = new AbortController().signal;
    vi.mocked(fetchRuntimePanels).mockRejectedValue(new Error('Batch unavailable'));
    const result = await fetchPanelRuntimeData(panels, { signal, reason: 'refresh' });
    expect(fetchRuntimePanels).toHaveBeenCalledWith(['a', 'b'], { a: 36, b: 8 }, signal);
    expect(fetchData).toHaveBeenNthCalledWith(1, { signal, reason: 'refresh' }, 36);
    expect(fetchData).toHaveBeenNthCalledWith(2, { signal, reason: 'refresh' }, 8);
    expect(Object.keys(result.data)).toEqual(['a', 'b']);
  });
  it('fetches dedicated endpoints through shared cancellation without batching their IDs', async () => {
    const dedicated = { ...panel('analysis'), batch: false };
    vi.mocked(fetchRuntimePanels).mockResolvedValue({ panels: { a: {}, b: {} }, errors: {}, metadata: {} } as any);
    const signal = new AbortController().signal;
    const result = await fetchPanelRuntimeData([panel('a'), dedicated, panel('b')], { signal, reason: 'manual' });
    expect(fetchRuntimePanels).toHaveBeenCalledWith(['a', 'b'], {}, signal);
    expect(dedicated.fetchData).toHaveBeenCalledWith({ signal, reason: 'manual' });
    expect(result.data.analysis).toEqual({ items: ['analysis'] });
  });
  it('retains independent successes from a partially failed batch', async () => {
    vi.mocked(fetchRuntimePanels).mockResolvedValue({ generatedAt: '2026-08-26T03:00:00Z', status: 'partial', requestId: 'fixture', panels: { a: { items: ['a'] } }, errors: { b: 'unavailable' }, metadata: {} });
    const result = await fetchPanelRuntimeData([panel('a'), panel('b')], { signal: new AbortController().signal, reason: 'refresh' });
    expect(result.data).toEqual({ a: { items: ['a'] } });
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
