import { describe, expect, it } from 'vitest';
import { bundleMatchesMarket, emptyWorkspaceBundle, mergeWorkspaceBundle } from './marketBundle';

describe('market bundle identity', () => {
  it('rejects a mixed identity even if one sub-payload matches', () => {
    const bundle = { ...emptyWorkspaceBundle(), market: { id: 2, title: 'Two', slug: 'two' }, chart: { marketId: 1, range: '1d', interval: '5m', points: [] } };
    expect(bundleMatchesMarket(bundle, 1)).toBe(false);
    expect(bundleMatchesMarket(bundle, 2)).toBe(false);
    expect(bundleMatchesMarket(emptyWorkspaceBundle(), 1)).toBe(false);
  });
  it('never carries the previous market chart or book into a new optimistic selection', () => {
    const previous = { ...emptyWorkspaceBundle(), market: { id: 1, title: 'One', slug: 'one' }, chart: { marketId: 1, range: '1d', interval: '5m', points: [] }, lob: { marketId: 1, yes: { tokenId: 'one', bids: [], asks: [] } } };
    const next = mergeWorkspaceBundle(previous, { ...emptyWorkspaceBundle(), market: { id: 2, title: 'Two', slug: 'two' } });
    expect(next.market?.id).toBe(2);
    expect(next.chart).toBeNull();
    expect(next.lob).toBeNull();
  });
  it('retains a real chart when the same market returns a warming snapshot', () => {
    const previous = { ...emptyWorkspaceBundle(), chart: { marketId: 1, range: '1d', interval: '5m', points: [{ timestamp: '2026-08-26T03:00:00Z', yesPrice: '.5' }] } };
    const patch = { ...emptyWorkspaceBundle(), chart: { marketId: 1, range: 'snapshot', interval: 'snapshot', points: [] } };
    expect(mergeWorkspaceBundle(previous, patch).chart).toEqual(previous.chart);
  });
});
