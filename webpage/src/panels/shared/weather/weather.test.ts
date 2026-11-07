import { afterEach, describe, expect, it, vi } from 'vitest';
import type { LobPayload } from '@/types';
import { bookCoverage, bookMidPrice, currentWeatherTemp, displayQuoteBins, highWeatherTemp, quoteBinLabel, weatherSourceLabel } from './model';
import { mergeLiveQuote, quoteFromLob } from './quote';
import { sevenDayPoints } from './trend';
import { weatherQuoteResource } from './useLiveWeatherQuoteBins';
import { fetchWeatherBooks } from '@/services/api';
vi.mock('@/services/api', () => ({ fetchWeatherBooks: vi.fn() }));
const now = Date.now();
const live = (tokenId?: string): LobPayload => ({ marketId: 1, bookStatus: 'live', yes: { tokenId, bookStatus: 'live', continuity: true,
  bestBid: .3, bestAsk: .4, receivedAt: new Date(now - 1000).toISOString(), heartbeatAt: new Date(now).toISOString(), staleAfter: new Date(now + 20_000).toISOString() } });
afterEach(() => vi.resetAllMocks());
describe('weather source and book contracts', () => {
  it('does not construct unlisted bins or use seven-day maximum as market-day high', () => {
    expect(displayQuoteBins({ currentTemp: 70, forecastHigh: 98 })).toEqual([]);
    expect(quoteBinLabel({ minTemp: 0, maxTemp: 1, unit: 'C' })).toBe('0–1°C');
    expect(quoteBinLabel({ maxTemp: 51, unit: 'F' })).toBe('≤51°F');
    expect(highWeatherTemp({ marketDate: '2026-10-06', forecastHigh: 98, marketForecastHigh: 71 })).toBe(71);
    expect(highWeatherTemp({ marketDate: '2026-10-12', forecastHigh: 98 })).toBeNull();
  });
  it('shows a fresh observation rather than carried model temperature', () => {
    const city = { currentTemp: 74, metarTemp: 59, weatherCarryForward: true, sourceStates: { openMeteo: 'stale', metar: 'ok' } };
    expect(currentWeatherTemp(city)).toBe(59); expect(weatherSourceLabel(city)).toBe('METAR OBSERVATION');
  });
  it('keeps high/low midpoint distinct from a daily mean', () => {
    expect(sevenDayPoints({ daily: [{ date: '2026-10-06', high: 80, low: 60 }] })[0]?.avg).toBe(70);
  });
  it('rejects stale ladders, missing continuity, elapsed source deadlines and crossed prices', () => {
    expect(quoteFromLob(live(), now).bestBidYes).toBe(.3);
    for (const patch of [{ bookStatus: 'stale' }, { continuity: false }, { staleAfter: new Date(now).toISOString() }, { bestBid: .6, bestAsk: .4 }]) {
      const payload = live(); Object.assign(payload.yes!, patch);
      expect(quoteFromLob(payload, now).bestBidYes).toBeNull();
    }
  });
  it('clears undated prices and bounds retained prices by the original source time', () => {
    const seed = { bestBidYes: .3, bestAskYes: .4, midPriceYes: .35, priceSource: 'clob-book', bookStatus: 'ok' };
    const next = mergeLiveQuote(seed, { bestBidYes: null, bestAskYes: null, bookStatus: 'warming' }, now);
    expect(next.bestBidYes).toBeNull(); expect(next.priceSource).toBeUndefined();
    expect(next.midPriceYes).toBeNull(); expect(bookMidPrice(next)).toBeNull();
    const expired = mergeLiveQuote(seed, quoteFromLob(live(), now), now + 21_000);
    expect(expired.bookStatus).toBe('retained'); expect(bookMidPrice(expired)).toBeNull();
  });
  it('deduplicates identity and recovers warming books on the next check', async () => {
    const resource = weatherQuoteResource([{ yesTokenId: '2' }, { yesTokenId: '1' }, { yesTokenId: '2' }]);
    expect(resource.key).toBe(weatherQuoteResource([{ yesTokenId: '1' }, { yesTokenId: '2' }]).key);
    expect(resource.refreshPolicy.intervalMs).toBe(15_000);
    const fetch = vi.mocked(fetchWeatherBooks);
    fetch.mockResolvedValue({ books: { '1': { marketId: 1, bookStatus: 'warming' }, '2': { marketId: 1, bookStatus: 'warming' } } });
    expect(resource.parse(await resource.fetch()).status).toBe('partial'); expect(fetch).toHaveBeenCalledTimes(1);
    fetch.mockResolvedValue({ books: { '1': live('1'), '2': live('2') } });
    expect(resource.parse(await resource.fetch()).status).toBe('ok'); expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('uses a committed ready snapshot without inventing continuous live reception', () => {
    const payload = { marketId: 1, yes: { tokenId: '1', bookStatus: 'available' as const, upstreamReady: true,
      observedAt: new Date(now).toISOString(), eventAt: new Date(now - 60_000).toISOString(), bestBid: 0, bestAsk: .1 } };
    const quote = quoteFromLob(payload, now, '1');
    expect(quote.bookStatus).toBe('snapshot'); expect(quote.bestBidYes).toBe(0);
    expect(quote.quoteUpdatedAt).toBe(payload.yes.eventAt);
    expect(quoteFromLob(payload, now, 'wrong').bestBidYes).toBeNull();
    const stale = quoteFromLob({ ...payload, yes: { ...payload.yes, upstreamReady: false } }, now, '1');
    expect(stale.bookStatus).toBe('retained'); expect(bookMidPrice(stale)).toBeNull();
    const later = mergeLiveQuote({}, stale, now + 2 * 60 * 60 * 1000);
    expect(later.bestBidYes).toBeNull(); expect(later.midPriceYes).toBeNull();
    expect(quoteFromLob({ ...payload, yes: { ...payload.yes, upstreamReady: false, eventAt: undefined } }, now).bestBidYes).toBeNull();
  });
  it('expires ready snapshots into retained quotes and clears valid empty books', () => {
    const quote = { bookStatus: 'snapshot', priceSource: 'clob-snapshot', bestBidYes: .2, bestAskYes: .3,
      quoteUpdatedAt: new Date(now - 1000).toISOString(), quoteStaleAfter: new Date(now + 30_000).toISOString() };
    expect(mergeLiveQuote({}, quote, now + 31_000).bookStatus).toBe('retained');
    expect(mergeLiveQuote(quote, { bookStatus: 'no-book', bestBidYes: null, bestAskYes: null }, now).midPriceYes).toBeNull();
    expect(mergeLiveQuote({}, { ...quote, bestBidYes: .9 }, now).bookStatus).toBe('invalid');
  });
  it('uses one bounded HTTP batch and forwards cancellation', async () => {
    const controller = new AbortController();
    vi.mocked(fetchWeatherBooks).mockResolvedValue({ books: {} });
    const resource = weatherQuoteResource(Array.from({ length: 11 }, (_, i) => ({ yesTokenId: String(i + 1) })));
    await resource.fetch({ signal: controller.signal } as never);
    expect(fetchWeatherBooks).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetchWeatherBooks).mock.calls[0]?.[0]).toHaveLength(11);
    expect(vi.mocked(fetchWeatherBooks).mock.calls[0]?.[1]).toBe(controller.signal);
  });
  it('counts only current books in overview and detail coverage', () => {
    const current = { bookStatus: 'ok', bestBidYes: .4, quoteStaleAfter: new Date(Date.now() + 20_000).toISOString() };
    const expired = { ...current, quoteStaleAfter: new Date(Date.now() - 1).toISOString() };
    expect(bookCoverage({ bins: [current, expired, { ...current, bookStatus: 'warming' }, { bestBidYes: .5 }] })).toBe('1/4');
    expect(bookMidPrice({ ...expired, bestAskYes: .5 })).toBeNull();
  });
});
