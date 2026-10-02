import { describe, it, expect } from 'vitest';
import { parseAlphaPayload, signalDirection, alphaStatusLabel } from './model';
const item = () => ({ id: 'alpha:7:token:BUY', marketId: 7, tokenId: 'token', marketTitle: 'Market', side: 'BUY', logicalOutcome: 'YES', sourceOutcomeLabel: 'Yes', price: '.62', timestamp: '2026-10-02T09:00:00Z', outcomeSemanticsValid: true, outcomeSemanticsCapabilities: { supportsYesNoWording: true }, metrics: { totalNotional: 15000, netFlowNotional: 14000, netDirectionStrength: .875, marketShare: .3, uniqueTraderCount: 6, tradeCount: 12, score: 88 } });
const payload = () => ({ policyVersion: 'token-flow-v1', scope: 'global', status: 'ok', generatedAt: '2026-10-02T09:00:00Z', windowMinutes: 15, baselineMinutes: 60, items: [item()], coverage: { candidateCount: 1, verifiedCount: 1, rejectedCount: 0, rejectionReasons: {} } });
const status = { phase: 'ready' as const, updatedAt: 1, lastAttemptAt: 1, failureCount: 0, error: null };
describe('Alpha owned contract', () => {
  it('rejects legacy identity, invalid dates, unrelated scope and malformed pages', () => {
    for (const change of [{ policyVersion: undefined }, { generatedAt: 'bad' }, { scope: 'market' }, { items: {} }]) expect(() => parseAlphaPayload({ ...payload(), ...change })).toThrow();
  });
  it('uses actual trader counts and preserves valid zero values', () => {
    const raw = payload(); raw.items[0]!.price = '0'; raw.items[0]!.metrics.uniqueTraderCount = 0;
    const data = parseAlphaPayload(raw); expect(data.items[0]!.price).toBe(0); expect(data.items[0]!.metrics.uniqueTraderCount).toBe(0);
  });
  it('isolates invalid cards instead of inventing missing values', () => {
    const raw = payload(); raw.items.push({ ...item(), id: 'bad', price: 'nan' });
    const data = parseAlphaPayload(raw); expect(data.items).toHaveLength(1); expect(data.status).toBe('partial'); expect(data.coverage.rejectedCount).toBe(1);
    expect(parseAlphaPayload({ ...payload(), items: [{ ...item(), outcomeSemanticsValid: false }] }).items).toHaveLength(0);
  });
  it('keeps neutral candidates separate without prices, outcomes or scores', () => {
    const raw = { ...item(), id: 'candidate', marketIdentityVerified: true, qualification: 'labels-unavailable', outcomeSemanticsValid: false };
    const data = parseAlphaPayload({ ...payload(), status: 'partial', items: [], candidates: [raw] });
    expect(data.items).toHaveLength(0); expect(data.candidates).toHaveLength(1); expect(data.candidates[0]).not.toHaveProperty('price'); expect(data.candidates[0]!.metrics).not.toHaveProperty('score'); expect(alphaStatusLabel(data, status)).toBe('NEEDS LABELS'); expect(signalDirection(data.candidates[0]!)).toBe('buy');
  });
  it('distinguishes healthy empty, limited and stale snapshots', () => {
    expect(alphaStatusLabel(parseAlphaPayload({ ...payload(), items: [], status: 'empty' }), status)).toBe('NO MATCH'); expect(alphaStatusLabel(parseAlphaPayload({ ...payload(), status: 'stale' }), status)).toBe('STALE'); expect(alphaStatusLabel(parseAlphaPayload(payload()), { ...status, error: '503' })).toBeUndefined();
  });
});
