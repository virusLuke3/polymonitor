import { describe, expect, it } from 'vitest';
import { parseWatchSnapshot } from './watch-snapshot';
const snapshot = { panelId: 'watch', generatedAt: '2026-10-03T06:00:00Z', status: 'ok', items: [{ id: 'one', label: 'ONE', metric: 10 }] };
describe('family watch acceptance', () => {
  it('checks resource identity, clock and row schema', () => {
    for (const raw of [{ ...snapshot, panelId: 'other' }, { ...snapshot, generatedAt: '' }, { ...snapshot, items: [{ title: {} }] }]) expect(() => parseWatchSnapshot(raw, 'watch', 10)).toThrow();
  });
  it('keeps healthy empty distinct from unavailable and preserves partial source evidence', () => {
    expect(parseWatchSnapshot({ ...snapshot, status: 'empty', items: [], sources: { feed: 'ok' } }, 'watch', 10).status).toBe('empty');
    expect(parseWatchSnapshot({ ...snapshot, sources: { model: 'error' } }, 'watch', 10).status).toBe('degraded');
    expect(parseWatchSnapshot({ ...snapshot, status: 'stale', sources: { model: 'error' } }, 'watch', 10).status).toBe('stale');
  });
  it('sanitizes unsafe links, numeric missing values and malformed summaries without inventing zero', () => {
    const value = parseWatchSnapshot({ ...snapshot, items: [{ id: 'one', metric: ' ', url: 'javascript:alert(1)', points: [{ timestamp: 'bad', value: 1 }] }, {}], summary: { watchlist: 'bad', metrics: [{ label: { nested: true }, value: 10 }] } }, 'watch', 10);
    expect(value.items![0]!.metric).toBeNull();
    expect(value.items![0]!.url).toBeNull();
    expect(value.summary?.watchlist).toEqual([]);
    expect(value.summary?.metrics).toEqual([{ value: 10 }]);
    expect(value.status).toBe('degraded');
  });
});
