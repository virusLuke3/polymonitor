import type { LobPayload, MarketGroupItem } from '@/types';
import type { PanelInputs } from '@/panels/types';
import { globalMarkets } from '@/panels/shared/selectors';
import { bookMidValue, liveBookStatus, lobMatchesTokens } from '@/features/market-focus/orderBook';

export type SummaryInputs = PanelInputs<'bootstrap' | 'bundle' | 'marketGroups' | 'markets' | 'selectedMarket' | 'selectedMarketGroupDetail' | 'selectedMarketGroupId' | 'selectedMarketGroupOutcomeKey' | 'selectedMarketId'>;

export function resolveFocusedMarketContext(ctx: SummaryInputs) {
  const id = ctx.selectedMarketId;
  const matchesGroup = (group: MarketGroupItem | null | undefined) => group && (id != null
    ? Number(group.defaultMarketId) === id || [...(group.outcomes || []), ...(group.topOutcomes || [])].some(outcome => Number(outcome.marketId) === id)
    : ctx.selectedMarketGroupId != null && String(group.eventId) === ctx.selectedMarketGroupId);
  const selectedGroup = [ctx.selectedMarketGroupDetail, ctx.bundle?.group, ...ctx.marketGroups].find(matchesGroup) || null;
  const bundleMatches = id != null && ctx.bundle?.market?.id === id;
  const selectedOutcome = id != null && ctx.bundle?.selectedOutcome?.marketId === id ? ctx.bundle.selectedOutcome
    : [...(selectedGroup?.outcomes || []), ...(selectedGroup?.topOutcomes || [])].find(outcome => id != null
      ? outcome.marketId === id : outcome.outcomeKey === ctx.selectedMarketGroupOutcomeKey) || null;
  const selected = (bundleMatches ? ctx.bundle?.market : null)
    || (id != null && ctx.selectedMarket?.id === id ? ctx.selectedMarket : null)
    || (id != null && ctx.bootstrap?.featuredMarket?.id === id ? ctx.bootstrap.featuredMarket : null);
  const listMarket = globalMarkets(ctx).find(market => market.id === id) || null;
  const price = id != null && ctx.bundle?.price?.marketId === id ? ctx.bundle.price : null;
  return { selectedGroup, selectedOutcome, selected, listMarket, price };
}

function probability(...values: Array<string | number | null | undefined>) {
  for (const value of values) {
    if (value == null || value === '') continue;
    const number = Number(value);
    if (Number.isFinite(number) && number >= 0 && number <= 1) return number;
  }
  return null;
}

export function summaryQuote(ctx: SummaryInputs, lob: LobPayload | null, closed: boolean, now = Date.now()) {
  const { selectedOutcome, selected, listMarket, price } = resolveFocusedMarketContext(ctx);
  const yesToken = String(selectedOutcome?.yesTokenId || selected?.yesTokenId || listMarket?.yesTokenId || '');
  const noToken = String(selectedOutcome?.noTokenId || selected?.noTokenId || listMarket?.noTokenId || '');
  const matches = !closed && lobMatchesTokens(lob, yesToken, noToken);
  const yesStatus = matches ? liveBookStatus(lob, 'yes', now) : 'unavailable';
  const noStatus = matches ? liveBookStatus(lob, 'no', now) : 'unavailable';
  const bookYes = ['live', 'available'].includes(yesStatus) ? bookMidValue(lob, 'yes') : null;
  const bookNo = ['live', 'available'].includes(noStatus) ? bookMidValue(lob, 'no') : null;
  if (bookYes != null || bookNo != null) {
    const side = bookYes != null ? lob?.yes : lob?.no;
    return { yes: bookYes, no: bookNo, source: bookYes != null ? yesStatus : noStatus,
      at: side?.receivedAt || side?.eventAt || side?.observedAt || null };
  }
  // A closed market has no current execution quote; do not revive its old price.
  if (closed) return { yes: null, no: null, source: 'closed', at: null };
  const yes = probability(price?.latestYesPrice, price?.latestPrice, selectedOutcome?.yesPrice,
    selected?.latestYesPrice, selected?.latestPrice, listMarket?.latestYesPrice, listMarket?.latestPrice);
  const no = probability(price?.latestNoPrice, selectedOutcome?.noPrice, selected?.latestNoPrice, listMarket?.latestNoPrice);
  return { yes, no, source: yes != null || no != null ? 'catalog' : 'unavailable',
    at: yes != null || no != null ? price?.updatedAt || selected?.quoteUpdatedAt || listMarket?.quoteUpdatedAt || null : null };
}
