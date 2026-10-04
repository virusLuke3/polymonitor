import { describe, expect, it } from 'vitest';
import { assetStats, fundingStats, parseFunding, percent, quoteState, MAX_AGE_MS, RETAIN_MS } from './model';

const generatedAt = '2026-10-04T10:00:00Z', now = Date.parse(generatedAt);
function quote(exchange = 'Binance', rate = -0.0004, period: number | null = 8) {
  return { id: `${exchange.toLowerCase()}:BTCUSDT`, asset: 'BTC', symbol: 'BTCUSDT', exchange,
    eligible: true, contractType: 'perpetual', contractStatus: exchange === 'Binance' ? 'TRADING' : 'Trading', settleCoin: 'USDT',
    fundingRate: rate, fundingRatePercent: rate * 100, fundingIntervalHours: period,
    updatedAt: generatedAt, fetchedAt: generatedAt, eligibilityCheckedAt: generatedAt,
    quoteObservedAt: exchange === 'Binance' ? generatedAt : null, sourceResponseAt: exchange === 'Bybit' ? generatedAt : null,
    acquisitionState: 'ok' };
}
function payload(quotes: unknown[] = [quote(), quote('Bybit', -0.0002)]) {
  return { kind: 'crypto-funding', schemaVersion: 3, generatedAt, status: 'ok', sources: { binance: 'ok', bybit: 'ok' },
    assets: [{ id: 'BTC', asset: 'BTC', quotes, maxAbsFundingPercent: 0.04, marketCount: 2, priceMarketCount: 2 }],
    coverage: { expectedQuotes: 2, succeeded: 2 }, marketUniverse: { status: 'ok', observedAt: generatedAt } };
}

describe('qualified funding domain contract', () => {
  it('keeps the negative sign and recomputes a signed extreme rather than trusting an absolute backend value', () => {
    const row = parseFunding(payload(), now).assets[0]!;
    const stats = assetStats(row, now);
    expect(stats.strongest?.fundingRatePercent8h).toBeCloseTo(-0.04);
    expect(stats.mean).toBeCloseTo(-0.03);
    expect(stats.bias).toBe('shorts-pay');
    expect(percent(stats.strongest?.fundingRatePercent8h)).toBe('-0.0400%');
  });
  it('compares actual periods on an explicit normalized basis', () => {
    const row = parseFunding(payload([quote('Binance', -0.0004, 4), quote('Bybit', -0.0002, 8)]), now).assets[0]!;
    expect(assetStats(row, now).mean).toBeCloseTo(-0.05);
    expect(row.quotes[0]!.annualizedPercent).toBeCloseTo(-0.04 * 6 * 365);
    expect(row.quotes[0]!.fundingRatePercent).toBe(-0.04);
  });
  it('retains an unknown period without assuming a rate comparison or annual return', () => {
    const data = parseFunding(payload([quote('Binance', -0.0004, null)]), now);
    expect(data.status).toBe('degraded');
    expect(data.assets[0]!.quotes[0]!.annualizedPercent).toBeNull();
    expect(assetStats(data.assets[0]!, now).mean).toBeNull();
  });
  it('rejects inactive instruments, malformed numbers, wrong underliers and future clocks', () => {
    for (const change of [
      { contractStatus: 'SETTLING' }, { eligible: false }, { fundingRate: null, fundingRatePercent: null },
      { acquisitionState: 'error' }, { acquisitionState: undefined },
      { fundingRatePercent: Infinity }, { fundingRatePercent: -40 }, { settleCoin: 'USDC' },
      { symbol: 'ETHUSDT', id: 'binance:ETHUSDT' }, { eligibilityCheckedAt: '2026-10-05T00:00:00Z' },
      { updatedAt: '2026-10-04T11:00:00Z', quoteObservedAt: '2026-10-04T11:00:00Z' },
    ]) expect(() => parseFunding(payload([{ ...quote(), ...change }]), now)).toThrow();
  });
  it('binds the snapshot family and schema, and bounds retention', () => {
    expect(() => parseFunding({ ...payload(), kind: 'crypto' }, now)).toThrow();
    expect(() => parseFunding({ ...payload(), schemaVersion: 2 }, now)).toThrow();
    expect(() => parseFunding(payload(), now + RETAIN_MS + 1)).toThrow();
  });
  it('distinguishes a valid zero fee from a missing value and zero alerts from coin count', () => {
    const data = parseFunding(payload([quote('Binance', 0)]), now);
    expect(percent(null)).toBe('—');
    expect(percent(0)).toBe('0.0000%');
    expect(fundingStats(data.assets, now).alerts).toBe(0);
    expect(assetStats(data.assets[0]!, now).bias).toBe('flat');
  });
  it('computes the mean absolute fee over fresh venue quotes and excludes saved quotes', () => {
    const data = parseFunding(payload([quote(), { ...quote('Bybit', 0.0002), acquisitionState: 'retained' }]), now);
    expect(data.status).toBe('degraded');
    expect(fundingStats(data.assets, now).averageAbs).toBeCloseTo(0.04);
    expect(assetStats(data.assets[0]!, now).mean).toBeCloseTo(-0.04);
    expect(quoteState(data.assets[0]!.quotes[1]!, now)).toBe('retained');
    expect(quoteState(data.assets[0]!.quotes[0]!, now + MAX_AGE_MS + 1)).toBe('stale');
  });
  it('preserves provider response time instead of inventing a Bybit quote observation', () => {
    const data = parseFunding(payload([quote('Bybit')]), now);
    expect(data.assets[0]!.quotes[0]!.quoteObservedAt).toBeNull();
    expect(data.assets[0]!.quotes[0]!.sourceResponseAt).toBe(generatedAt);
  });
  it('rejects expired or unsafe market links while retaining an explicitly contextual relation', () => {
    const raw = payload();
    Object.assign(raw.assets[0]!, { relatedMarkets: [
      { id: '1', title: 'Expired', url: 'https://polymarket.com/event/old', endAt: '2026-01-01T00:00:00Z' },
      { id: '2', title: 'Unsafe', url: 'https://evil.test/event/fake', endAt: '2027-01-01T00:00:00Z' },
      { id: '3', title: 'BTC context', url: 'https://polymarket.com/event/btc-context', endAt: '2027-01-01T00:00:00Z', relation: 'asset-context' },
    ] });
    const data = parseFunding(raw, now);
    expect(data.assets[0]!.relatedMarkets).toHaveLength(1);
    expect(data.assets[0]!.relatedMarkets[0]!.relation).toBe('asset-context');
  });
});
