import { describe, expect, it } from 'vitest';
import { num, seriesScores, validateSports, type ProMatch } from './model';
const base = { schemaVersion: 1, generatedAt: '2026-11-08T00:00:00Z', status: 'ok', sources: [] };
describe('sports expansion semantics', () => {
  it('retains unavailable data without manufacturing rows or numbers', () => {
    expect(validateSports({ ...base, panelId: 'sports-total-monitor', game: null })).toBe(true);
    expect(num(null)).toBe('—');
    expect(num(0)).toBe('0');
  });
  it('rejects invalid quarter values before the chart can turn them into zero', () => {
    expect(validateSports({ ...base, panelId: 'sports-total-monitor', game: { eventId: '1', teams: [{ id: '1', name: 'Alpha', score: 0, periods: ['bad'] }], players: [], odds: [] } })).toBe(false);
  });
  it('rejects wrong standings shape rather than silently showing an empty season', () => {
    expect(validateSports({ ...base, panelId: 'sports-season-race', groups: {} })).toBe(false);
  });
  it('keeps series score order stable across Radiant/Dire side changes', () => {
    const match = { radiant: 'Beta', dire: 'Alpha', radiantScore: 38, direScore: 10 } as ProMatch;
    expect(seriesScores(match, 'Alpha')).toEqual([10, 38]);
    expect(seriesScores(match, 'Beta')).toEqual([38, 10]);
    expect(seriesScores(match, 'Unknown')).toEqual([null, null]);
  });
});
