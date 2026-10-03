import { describe, expect, it } from 'vitest';
import { cryptoQuoteState, parseCrypto, RETAIN_MS } from './model';
const generatedAt = '2026-10-03T06:00:00Z';
const row = { id: 'btc', label: 'BTC', symbol: 'BTC-USD', price: 110, quoteAt: generatedAt, fetchedAt: generatedAt, changePercent: 120, points: [] };
const data = (items: unknown[] = [row]) => ({ kind: 'crypto', generatedAt, status: 'ok', items });
describe('crypto quote semantics', () => {
  it('rejects wrong identity, invalid clock and unusable prices', () => {
    for (const raw of [{ ...data(), kind: 'commodities' }, { ...data(), generatedAt: '' }, data([{ ...row, price: NaN }])]) expect(() => parseCrypto(raw)).toThrow();
  });
  it('accepts 24h change only with an explicit basis', () => {
    expect(parseCrypto(data()).items[0]!.changePercent).toBeNull();
    expect(parseCrypto(data([{ ...row, changeBasis: 'rolling-24h', changePercent: 10 }])).items[0]!.changePercent).toBe(10);
  });
  it('preserves source time, filters malformed points and reports partial coverage', () => {
    const value = parseCrypto(data([{ ...row, points: [{ value: 12, timestamp: 'broken' }, { value: 110, timestamp: generatedAt }] }]));
    expect(value.coverage).toEqual({ expected: 13, succeeded: 1, retained: 0, missing: 12 });
    expect(value.status).toBe('degraded');
    expect(value.items[0]!.points).toHaveLength(1);
    expect(value.items[0]!.quoteAt).toBe(generatedAt);
  });
  it('distinguishes unknown, stale and retained quotes from a live 24/7 quote', () => {
    const item = parseCrypto(data()).items[0]!, now = Date.parse(generatedAt);
    expect(cryptoQuoteState(item, now)).toBe('live');
    expect(cryptoQuoteState(item, now + RETAIN_MS)).toBe('stale');
    expect(cryptoQuoteState({ ...item, quoteAt: null }, now)).toBe('unknown');
    expect(cryptoQuoteState({ ...item, acquisitionState: 'retained' }, now)).toBe('retained');
  });
});
