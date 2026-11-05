import { describe, expect, it } from 'vitest';
import type { LobPayload } from '@/types';
import { emptyWorkspaceBundle } from '@/features/market-focus/marketBundle';
import { orderBookResource } from '@/features/market-focus/orderBookResource';
import { parseRuntimeSnapshot } from '@/panels/runtime-store';
import type { PanelSnapshotContract } from '@/panels/resource-cache';
import { resolveFocusedMarketContext, summaryQuote, type SummaryInputs } from './model';

const now = Date.now();
const time = new Date(now).toISOString();
const market = { id: 1, slug: 'one', title: 'One', yesTokenId: '111', noTokenId: '222' };
const ctx: SummaryInputs = { runtimeData: {}, selectedMarketId: 1, selectedMarket: market, selectedMarketGroupId: null,
  selectedMarketGroupOutcomeKey: null, selectedMarketGroupDetail: null, marketGroups: [], markets: [], bootstrap: null,
  bundle: { ...emptyWorkspaceBundle(), market, price: { marketId: 1, latestYesPrice: null, latestNoPrice: null } } };
const side = (tokenId: string, bid: number, ask: number) => ({ tokenId, bookStatus: 'available' as const,
  upstreamReady: true, observedAt: time, eventAt: time, bestBid: bid, bestAsk: ask,
  bids: [{ price: bid, size: 10 }], asks: [{ price: ask, size: 10 }] });
const book: LobPayload = { marketId: 1, yes: side('111', .002, .004), no: side('222', .996, .998) };

describe('market summary quote ownership', () => {
  it('uses the selected book when Gamma detail fields are null', () => {
    expect(summaryQuote(ctx, book, false, now)).toEqual({ yes: .003, no: .997, source: 'available', at: time });
  });
  it('does not use another market or bootstrap when selection changes', () => {
    const changed = { ...ctx, selectedMarketId: 2 };
    expect(resolveFocusedMarketContext(changed)).toMatchObject({ selected: null, price: null, selectedOutcome: null });
    expect(summaryQuote(changed, book, false, now)).toMatchObject({ yes: null, no: null, source: 'unavailable' });
  });
  it('withdraws unready, expired and closed book quotes without inventing a complement', () => {
    expect(summaryQuote(ctx, { ...book, yes: { ...book.yes, upstreamReady: false } }, false, now).yes).toBeNull();
    expect(summaryQuote(ctx, book, false, now + 31_000).source).toBe('unavailable');
    expect(summaryQuote(ctx, book, true, now)).toMatchObject({ yes: null, no: null, source: 'closed' });
  });
  it('falls back to same-market catalog values and preserves zero', () => {
    const catalog = { ...ctx, markets: [{ ...market, latestYesPrice: 0, latestNoPrice: 1, quoteUpdatedAt: time }] };
    expect(summaryQuote(catalog, null, false, now)).toEqual({ yes: 0, no: 1, source: 'catalog', at: time });
  });
});

describe('shared book resource contract', () => {
  const resource = orderBookResource(1, '111', '222');
  const parse = (value: unknown) => parseRuntimeSnapshot({ id: resource.key, title: 'Book', eyebrow: '', description: '', snapshot: resource as PanelSnapshotContract<unknown> }, value);
  it('uses the same key for sibling consumers and separates changed identities', () => {
    expect(resource.key).toBe(orderBookResource(1, '111', '222').key);
    expect(resource.key).not.toBe(orderBookResource(2, '111', '222').key);
    expect(resource.key).not.toBe(orderBookResource(1, '111', '333').key);
    expect(parse(book)).toBe(book);
  });
  it('rejects mismatched tokens/market and malformed book levels', () => {
    expect(() => parse({ ...book, marketId: 2 })).toThrow('identity mismatch');
    expect(() => parse({ ...book, no: side('333', .9, 1) })).toThrow('identity mismatch');
    expect(() => parse({ ...book, yes: { ...book.yes, bids: [{ price: 2, size: 10 }] } })).toThrow('Invalid order book levels');
  });
  it('never renews old or missing source observation with envelope time', () => {
    const old = new Date(now - 60_000).toISOString();
    expect(() => parse({ ...book, generatedAt: time, yes: { ...book.yes, observedAt: old } })).toThrow('overdue');
    expect(() => parse({ ...book, generatedAt: time, yes: { ...book.yes, observedAt: null } })).toThrow('time is unknown');
  });
});
