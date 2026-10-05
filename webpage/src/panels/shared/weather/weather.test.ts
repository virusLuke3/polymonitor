import { afterEach, describe, expect, it, vi } from 'vitest';
import type { LobPayload } from '@/types';
import { bookMidPrice, currentWeatherTemp, displayQuoteBins, highWeatherTemp, weatherSourceLabel } from './model';
import { mergeLiveQuote, quoteFromLob } from './quote';
import { sevenDayPoints } from './trend';
import { weatherQuoteResource } from './useLiveWeatherQuoteBins';
import { fetchWeatherBooks } from '@/services/api';
vi.mock('@/services/api', () => ({ fetchWeatherBooks: vi.fn() }));
const now = Date.now();
const live = (): LobPayload => ({ marketId: 1, bookStatus: 'live', yes: { bookStatus: 'live', continuity: true,
  bestBid: .3, bestAsk: .4, receivedAt: new Date(now - 1000).toISOString(), heartbeatAt: new Date(now).toISOString(), staleAfter: new Date(now + 20_000).toISOString() } });
afterEach(() => vi.resetAllMocks());
describe('weather source and book contracts', () => {
  it('does not construct unlisted bins or use seven-day maximum as market-day high', () => {
    expect(displayQuoteBins({ currentTemp: 70, forecastHigh: 98 })).toEqual([]);
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
  it('clears failed bids/asks and labels retained reference prices separately', () => {
    const seed = { bestBidYes: .3, bestAskYes: .4, midPriceYes: .35, priceSource: 'clob-book', bookStatus: 'ok' };
    const next = mergeLiveQuote(seed, { bestBidYes: null, bestAskYes: null, bookStatus: 'warming' }, now);
    expect(next.bestBidYes).toBeNull(); expect(next.priceSource).toBe('previous-book');
    expect(next.midPriceYes).toBe(.35); expect(bookMidPrice(next)).toBeNull();
    const expired = mergeLiveQuote(seed, quoteFromLob(live(), now), now + 21_000);
    expect(expired.bookStatus).toBe('stale'); expect(bookMidPrice(expired)).toBeNull();
  });
  it('deduplicates identity and recovers warming books on the next check', async () => {
    const resource = weatherQuoteResource([{ yesTokenId: '2' }, { yesTokenId: '1' }, { yesTokenId: '2' }]);
    expect(resource.key).toBe(weatherQuoteResource([{ yesTokenId: '1' }, { yesTokenId: '2' }]).key);
    expect(resource.refreshPolicy.intervalMs).toBe(15_000);
    const fetch = vi.mocked(fetchWeatherBooks);
    fetch.mockResolvedValue({ books: { '1': { marketId: 1, bookStatus: 'warming' }, '2': { marketId: 1, bookStatus: 'warming' } } });
    expect(resource.parse(await resource.fetch()).status).toBe('partial'); expect(fetch).toHaveBeenCalledTimes(1);
    fetch.mockResolvedValue({ books: { '1': live(), '2': live() } });
    expect(resource.parse(await resource.fetch()).status).toBe('ok'); expect(fetch).toHaveBeenCalledTimes(2);
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
});
