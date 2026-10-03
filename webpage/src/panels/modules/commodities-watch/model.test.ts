import { describe, expect, it } from 'vitest';
import { parseCommodities, quoteState, dailyMovers, formatPrice, commodityClass } from './model';

const now = Date.parse('2026-10-03T03:20:00Z');
const raw = (extra = {}) => ({ kind: 'commodities', generatedAt: '2026-10-03T03:19:00Z', items: [{ id: 'gold', label: 'GOLD', symbol: 'GC=F', price: 2400, currency: 'USD', changePercent: 1.5, changeBasis: 'previous-close', marketState: 'closed', quoteAt: '2026-10-02T20:00:00Z', fetchedAt: '2026-10-03T03:19:00Z', points: [] }], ...extra });
const quote = () => parseCommodities(raw()).items[0]!;
describe('Commodity source semantics', () => {
  it('rejects broken and empty payloads without replacing valid quotes', () => {
    for (const extra of [{ kind: 'crypto' }, { generatedAt: 'bad' }, { items: [] }, { items: [{}] }]) expect(() => parseCommodities(raw(extra))).toThrow();
  });
  it('keeps the 33-symbol denominator and does not coerce missing daily changes to zero', () => {
    const data = parseCommodities(raw());
    expect(data.coverage).toMatchObject({ expected: 33, succeeded: 1, missing: 32 });
    expect(data.status).toBe('degraded');
    expect(dailyMovers([{ ...quote(), changePercent: null }], now)).toHaveLength(0);
    expect(parseCommodities(raw({ items: [{ ...quote(), changeBasis: 'chart-baseline', changePercent: 99 }] })).items[0]!.changePercent).toBeNull();
  });
  it('preserves source clocks and distinguishes closed markets, old quotes and retention', () => {
    expect(quoteState(quote(), now)).toBe('closed');
    expect(quoteState({ ...quote(), marketState: 'open' }, now)).toBe('stale');
    expect(quoteState({ ...quote(), quoteAt: null }, now)).toBe('unknown');
    expect(quoteState({ ...quote(), acquisitionState: 'retained' }, now)).toBe('retained');
    expect(dailyMovers([{ ...quote(), acquisitionState: 'retained' }], now)).toHaveLength(0);
  });
  it('uses provider currency, cents and index points without losing precision', () => {
    expect(formatPrice(quote())).toBe('$2,400.00');
    expect(formatPrice({ ...quote(), symbol: 'TTF=F', price: 76.5, currency: 'EUR' })).toBe('€76.50');
    expect(formatPrice({ ...quote(), symbol: 'ZW=F', price: 683, currency: 'USX' })).toBe('683.00¢');
    expect(formatPrice({ ...quote(), symbol: '^VIX', price: 15.31 })).toBe('15.31');
    expect(formatPrice({ ...quote(), symbol: 'EURUSD=X', price: 1.1762 })).toBe('1.1762');
    expect(commodityClass({ ...quote(), symbol: 'MTF=F' })).toBe('ENERGY');
    expect(commodityClass({ ...quote(), symbol: 'URA' })).toBe('ETF');
  });
});
