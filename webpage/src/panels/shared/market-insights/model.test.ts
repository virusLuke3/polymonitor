import { describe, expect, it } from 'vitest';
import { insightView, isInsight } from './model';
const now = Date.parse('2026-09-29T10:00:00Z');
const snapshot = {
  status: 'live', model: 'actual-model', lens: 'overview', generationMode: 'ai',
  brief: 'Measured overview.', focus: [], specialMarkets: [], themes: [], watchlist: [], evidence: [],
  snapshotGeneratedAt: '2026-09-29T09:00:00Z', snapshotExpiresAt: '2026-09-29T21:00:00Z',
};
describe('analysis snapshot contract', () => {
  it('never labels gateway failure or deterministic snapshots as AI', () => {
    for (const patch of [{ status: 'gateway-error' }, { generationMode: 'rules' }, { model: 'deterministic-fallback' }, { error: 'failed' }]) {
      expect(insightView({ ...snapshot, ...patch }, 'overview', now)).toMatchObject({ mode: 'rules', badge: 'rules', healthy: false });
    }
  });
  it('separates expired and unknown timestamps from a current AI snapshot', () => {
    expect(insightView(snapshot, 'overview', now)).toMatchObject({ badge: 'ai', healthy: true });
    expect(insightView({ ...snapshot, snapshotExpiresAt: '2026-09-29T09:30:00Z' }, 'overview', now)).toMatchObject({ badge: 'stale', healthy: false });
    expect(insightView({ ...snapshot, snapshotGeneratedAt: 'invalid' }, 'overview', now)).toMatchObject({ badge: 'unknownTime', healthy: false });
  });
  it('rejects the wrong lens and malformed cards, preserving authoritative empty lists', () => {
    expect(isInsight(snapshot, 'special')).toBe(false);
    expect(isInsight({ ...snapshot, focus: [null] }, 'overview')).toBe(false);
    expect(isInsight({ ...snapshot, focus: [{ title: {} }] }, 'overview')).toBe(false);
    expect(insightView(snapshot, 'overview', now).insight?.focus).toEqual([]);
    expect(insightView(null, 'overview', now).badge).toBe('unavailable');
  });
});
