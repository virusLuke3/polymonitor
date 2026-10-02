import { describe, it, expect } from 'vitest';
import { parseTradeFeed, tradeStatusLabel } from './model';
const row = () => ({ marketId: 7, marketTitle: 'Market', tokenId: 'token-a', txHash: 'a'.repeat(64), logIndex: 1,
  timestamp: '2026-10-02T09:00:00Z', side: 'SELL', price: '0', notional: '6000', outcome: 'YES',
  outcomeSemanticsValid: false, maker: `0x${'b'.repeat(40)}`, taker: `0x${'c'.repeat(40)}` });
const payload = () => ({ schemaVersion: 'trade-watch-v1', kind: 'flow-watch', status: 'ok', generatedAt: '2026-10-02T09:00:00Z', items: [row()] });
const status = { phase: 'ready' as const, updatedAt: 1, lastAttemptAt: 1, failureCount: 0, error: null };
describe('canonical trade observation contract', () => {
  it('rejects legacy snapshots, wrong resource identities and unknown generation times', () => {
    for (const change of [{ schemaVersion: undefined }, { kind: 'whale-trades' }, { generatedAt: null }, { items: {} }]) expect(() => parseTradeFeed({ ...payload(), ...change }, 'flow-watch')).toThrow();
  });
  it('does not guess BUY, outcomes, addresses or timestamps', () => {
    const data = parseTradeFeed({ ...payload(), items: [{ ...row(), side: null, maker: 'a'.repeat(64), timestamp: 'bad' }] }, 'flow-watch');
    expect(data.items[0]).toMatchObject({ side: 'UNKNOWN', outcome: null, maker: null, timestamp: null, price: 0 });
  });
  it('uses verified source labels and actual maker/taker addresses', () => {
    const data = parseTradeFeed({ ...payload(), items: [{ ...row(), outcomeSemanticsValid: true, sourceOutcomeLabel: 'Alice' }] }, 'flow-watch');
    expect(data.items[0]!.outcome).toBe('Alice'); expect(data.items[0]!.maker).not.toBe(data.items[0]!.txHash);
  });
  it('isolates malformed cards while keeping distinct fills in one transaction', () => {
    const data = parseTradeFeed({ ...payload(), items: [row(), { ...row(), logIndex: 2 }, { ...row(), marketId: -1 }] }, 'flow-watch');
    expect(data.items).toHaveLength(2); expect(data.status).toBe('partial'); expect(data.coverage.invalidDisplayCount).toBe(1);
    expect(() => parseTradeFeed({ ...payload(), items: [{ ...row(), tokenId: null }] }, 'flow-watch')).toThrow();
  });
  it('keeps source failure, stale state, fallback and healthy empty distinct', () => {
    expect(tradeStatusLabel(parseTradeFeed(payload(), 'flow-watch'), status)).toBe('LARGE TRADES');
    expect(tradeStatusLabel(parseTradeFeed({ ...payload(), status: 'stale' }, 'flow-watch'), status)).toBe('STALE');
    expect(tradeStatusLabel(parseTradeFeed({ ...payload(), status: 'empty', items: [] }, 'flow-watch'), status)).toBe('NO MATCH');
    expect(tradeStatusLabel(parseTradeFeed(payload(), 'flow-watch'), { ...status, error: '503' })).toBeUndefined();
  });
});
