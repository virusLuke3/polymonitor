import { numericValue } from '@/panels/shared/formatters';
import { createContext } from 'preact';
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import type { MarketGroupItem, MarketGroupOutcome, MarketGroupSort, MarketListItem } from '@/types';
import type { PanelRenderMap } from '@/panels/types';
import { emptyState } from '@/panels/shared/renderers';
import { globalMarkets } from '@/panels/shared/selectors';
import { useI18n, type MessageKey } from '@/services/i18n';
import { localizedCurrency, MarketI18n, localizedPercent, localizedCompact, firstFiniteValue, uniqueGroupOutcomes, groupDisplayTradeCount, groupDisplayVolume } from '../../shared/market-values';
import { panelFromRenderer } from '@/panels/definePanel';

const MARKET_CATALOG_AUTO_REFRESH_MS = 20_000;

const MARKET_CATALOG_SYNC_DELAYED_MS = 60_000;

const MARKET_ACTIVITY_DELAYED_MS = 12 * 60 * 60 * 1000;

const MARKET_ACTIVITY_STALE_MS = 24 * 60 * 60 * 1000;

const MARKET_SORT_OPTIONS: ReadonlyArray<{ value: MarketGroupSort; label: MessageKey }> = [
  { value: 'active', label: 'atlasMarket.sort.active' },
  { value: 'volume', label: 'atlasMarket.sort.volume' },
  { value: 'close', label: 'atlasMarket.sort.close' },
  { value: 'move', label: 'atlasMarket.sort.move' },
  { value: 'trades', label: 'atlasMarket.sort.transactions' },
  { value: 'new', label: 'atlasMarket.sort.newest' },
];

const MARKET_SORT_HELP_KEYS: Record<MarketGroupSort, MessageKey> = {
  active: 'atlasMarket.sortHelp.active',
  volume: 'atlasMarket.sortHelp.volume',
  close: 'atlasMarket.sortHelp.close',
  move: 'atlasMarket.sortHelp.move',
  trades: 'atlasMarket.sortHelp.trades',
  new: 'atlasMarket.sortHelp.new',
};

function localizedEmptyCopy(i18n: MarketI18n) {
  return {
    label: i18n.t('atlasShared.standby'),
    detail: i18n.t('atlasShared.emptyDetail'),
  };
}

const GENERIC_MARKET_TAGS = new Set([
  'all',
  'featured',
  'hide-from-new',
  'recurring',
  'onchain-registry',
  'up-or-down',
  'crypto-prices',
  '5m',
  '15m',
]);

function parseTimestamp(value: string | null | undefined) {
  if (!value) return 0;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
}

function newestTimestamp(values: Array<string | null | undefined>) {
  return values.reduce((latest, value) => Math.max(latest, parseTimestamp(value)), 0);
}

function marketCatalogGeneratedAt(groups: MarketGroupItem[]) {
  return newestTimestamp(groups.map((group) => group.generatedAt));
}

function marketCatalogActivityAt(groups: MarketGroupItem[]) {
  return newestTimestamp(groups.flatMap((group) => [
    group.lastActivityAt,
    group.createdAt,
    ...(group.outcomes || []).map((outcome) => outcome.lastTradeAt),
    ...(group.topOutcomes || []).map((outcome) => outcome.lastTradeAt),
  ]));
}

function isDefaultSuppressedMarket(market: MarketListItem) {
  const tags = (market.tags || []).map((item) => String(item || '').trim().toLowerCase());
  const slug = String(market.slug || '').toLowerCase();
  const title = String(market.title || '').toLowerCase();
  const endAt = parseTimestamp(market.endDate);
  const price = numericValue(market.latestPrice);
  if (endAt && endAt < Date.now()) return true;
  if (price > 0 && (price < 0.1 || price > 0.9)) return true;
  if (tags.some((tag) => tag === 'hide-from-new' || tag === 'recurring' || tag === 'onchain-registry')) return true;
  if (slug.includes('updown-5m') || slug.includes('updown-15m')) return true;
  return title.includes(' up or down - ');
}

function marketTopic(market: MarketListItem) {
  const tags = (market.tags || []).map((item) => String(item || '').trim().toLowerCase()).filter(Boolean);
  const category = String(market.category || '').trim().toLowerCase();
  const title = `${market.title || ''} ${market.slug || ''}`.toLowerCase();
  if (category === 'crypto' || tags.includes('crypto') || tags.includes('crypto-prices')) return 'crypto';
  if (category === 'sports' || /tennis|wta|atp|itf|soccer|nba|nfl|mlb|nhl|fifa|ufc/.test(title) || tags.includes('sports') || tags.includes('soccer')) return 'sports';
  if (/esports|counter-strike|league of legends|lol:|dota|valorant|rainbow six/.test(title) || tags.some((tag) => ['esports', 'gaming'].includes(tag))) return 'games';
  if (category.includes('politic') || tags.some((tag) => tag.includes('election') || tag.includes('politic'))) return 'politics';
  if (category.includes('economic') || category.includes('finance') || tags.some((tag) => ['fed', 'macro', 'economy', 'finance'].includes(tag))) return 'macro';
  if (category.includes('tech') || tags.some((tag) => ['ai', 'tech'].includes(tag))) return 'tech';
  const semanticTag = tags.find((tag) => !GENERIC_MARKET_TAGS.has(tag));
  if (semanticTag) return semanticTag;
  if (title.includes('bitcoin') || title.includes('ethereum') || title.includes('solana') || title.includes('xrp') || title.includes('dogecoin')) return 'crypto';
  return category || String(market.status || 'market').toLowerCase();
}

function groupTopic(group: MarketGroupItem) {
  const tags = (group.tags || []).map((item) => String(item || '').trim().toLowerCase()).filter(Boolean);
  const category = String(group.category || '').trim().toLowerCase();
  const title = `${group.title || ''} ${group.slug || ''}`.toLowerCase();
  if (category === 'crypto' || tags.includes('crypto') || tags.includes('crypto-prices')) return 'crypto';
  if (category === 'sports' || /tennis|wta|atp|itf|soccer|nba|nfl|mlb|nhl|fifa|ufc/.test(title) || tags.includes('sports') || tags.includes('soccer')) return 'sports';
  if (/esports|counter-strike|league of legends|lol:|dota|valorant|rainbow six/.test(title) || tags.some((tag) => ['esports', 'gaming'].includes(tag))) return 'games';
  if (category.includes('politic') || tags.some((tag) => tag.includes('election') || tag.includes('politic'))) return 'politics';
  if (category.includes('economic') || category.includes('finance') || tags.some((tag) => ['fed', 'macro', 'economy', 'finance'].includes(tag))) return 'macro';
  if (category.includes('tech') || tags.some((tag) => ['ai', 'tech'].includes(tag))) return 'tech';
  const semanticTag = tags.find((tag) => !GENERIC_MARKET_TAGS.has(tag));
  if (semanticTag) return semanticTag;
  if (title.includes('bitcoin') || title.includes('ethereum') || title.includes('solana') || title.includes('xrp') || title.includes('dogecoin')) return 'crypto';
  return category || 'market';
}

function marketTiming(market: MarketListItem, i18n: MarketI18n) {
  if (market.createdAt) return i18n.formatRelativeTime(market.createdAt);
  if (market.lastTradeAt) return i18n.t('atlasMarket.tradeTiming', { time: i18n.formatRelativeTime(market.lastTradeAt) });
  if (market.endDate) return i18n.t('atlasMarket.closeTiming', { time: i18n.formatRelativeTime(market.endDate) });
  return '--';
}

function groupTiming(group: MarketGroupItem, i18n: MarketI18n) {
  if (group.lastActivityAt) return i18n.t('atlasMarket.activeTiming', { time: i18n.formatRelativeTime(group.lastActivityAt) });
  if (group.createdAt) return i18n.t('atlasMarket.listedTiming', { time: i18n.formatRelativeTime(group.createdAt) });
  if (group.endDate) return i18n.t('atlasMarket.closeTiming', { time: i18n.formatRelativeTime(group.endDate) });
  return '--';
}

function marketOutcomeLabel(market: MarketListItem, i18n: MarketI18n) {
  const count = Number(market.outcomeCount || 0);
  if (count > 0) return i18n.t('atlasMarket.outcomes', { count: i18n.formatNumber(count) });
  return i18n.t('atlasMarket.binary');
}

function groupOutcomeLabel(group: MarketGroupItem, i18n: MarketI18n) {
  const count = Number(group.outcomeCount || group.outcomes?.length || 0);
  if (count > 0) return i18n.t('atlasMarket.outcomes', { count: i18n.formatNumber(count) });
  return i18n.t('atlasMarket.event');
}

function marketAccent(market: MarketListItem) {
  const topic = marketTopic(market);
  if (topic.includes('crypto')) return '#f59e0b';
  if (topic.includes('game') || topic.includes('esport')) return '#8b5cf6';
  if (topic.includes('sport')) return '#22c55e';
  if (topic.includes('politic') || topic.includes('election')) return '#60a5fa';
  if (topic.includes('finance') || topic.includes('fed') || topic.includes('macro')) return '#eab308';
  if (topic.includes('tech') || topic.includes('ai')) return '#a78bfa';
  return '#22c55e';
}

function groupAccent(group: MarketGroupItem) {
  const topic = groupTopic(group);
  if (topic.includes('crypto')) return '#f59e0b';
  if (topic.includes('game') || topic.includes('esport')) return '#8b5cf6';
  if (topic.includes('sport')) return '#22c55e';
  if (topic.includes('politic') || topic.includes('election')) return '#60a5fa';
  if (topic.includes('finance') || topic.includes('fed') || topic.includes('macro')) return '#eab308';
  if (topic.includes('tech') || topic.includes('ai')) return '#a78bfa';
  return '#22c55e';
}

function topicClassName(topic: string) {
  const normalized = String(topic || 'market').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  return normalized ? `topic-${normalized}` : 'topic-market';
}

function defaultGroupMarketId(group: MarketGroupItem) {
  const defaultOutcome = groupDefaultOutcome(group);
  if (defaultOutcome?.marketId) return Number(defaultOutcome.marketId);
  return group.defaultMarketId || null;
}

function isTerminalProbability(value?: string | number | null) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return false;
  return numeric <= 0.03 || numeric >= 0.97;
}

function groupOutcomePrice(outcome: MarketGroupOutcome) {
  return firstFiniteValue(outcome.blockCloseYesPrice, outcome.yesPrice);
}

function groupOutcomeIsTerminal(outcome: MarketGroupOutcome) {
  const price = groupOutcomePrice(outcome);
  return price !== null && price !== undefined && isTerminalProbability(price);
}

function groupOutcomeHasActivity(outcome: MarketGroupOutcome) {
  return Number(outcome.tradeCount24h || 0) >= 1 || Number(outcome.volume24h || 0) >= 25;
}

function groupOutcomeIsFocusable(outcome: MarketGroupOutcome, requireActivity = false) {
  if (!outcome.marketId && !outcome.yesTokenId) return false;
  if (groupOutcomeIsTerminal(outcome)) return false;
  if (requireActivity && !groupOutcomeHasActivity(outcome)) return false;
  const price = Number(groupOutcomePrice(outcome));
  if (Number.isFinite(price) && Math.abs(price - 0.5) < 0.0001 && !groupOutcomeHasActivity(outcome)) return false;
  return true;
}

// API snapshots are immutable; selection/sorts/clock ticks reuse this derivation.
const defaultOutcomes = new WeakMap<MarketGroupItem, MarketGroupOutcome | null>();
function groupDefaultOutcome(group: MarketGroupItem) {
  if (defaultOutcomes.has(group)) return defaultOutcomes.get(group)!;
  const outcomes = uniqueGroupOutcomes([...(group.outcomes || []), ...(group.topOutcomes || [])])
    .filter((outcome) => outcome.marketId || outcome.yesTokenId);
  const liveOutcomes = outcomes.filter((outcome) => groupOutcomeIsFocusable(outcome, false));
  const candidates = liveOutcomes.length ? liveOutcomes : outcomes;
  const selected = candidates
    .slice()
    .sort((left, right) => {
      const leftPrice = Number(groupOutcomePrice(left));
      const rightPrice = Number(groupOutcomePrice(right));
      const leftVolume = Number(left.volume24h || 0);
      const rightVolume = Number(right.volume24h || 0);
      const leftTrades = Number(left.tradeCount24h || 0);
      const rightTrades = Number(right.tradeCount24h || 0);
      const leftDistance = Number.isFinite(leftPrice) ? Math.min(1, Math.abs(leftPrice - 0.5) * 2) : 0;
      const rightDistance = Number.isFinite(rightPrice) ? Math.min(1, Math.abs(rightPrice - 0.5) * 2) : 0;
      const leftBlockClose = left.blockCloseYesPrice == null || left.blockCloseYesPrice === '' ? 0 : 1;
      const rightBlockClose = right.blockCloseYesPrice == null || right.blockCloseYesPrice === '' ? 0 : 1;
      const leftScore = Math.min(70, Math.pow(Math.max(leftVolume, 0), 0.35))
        + Math.min(70, Math.max(leftTrades, 0) * 3)
        + leftDistance * 24
        + leftBlockClose * 28
        + (left.marketId ? 12 : 0)
        + (left.yesTokenId ? 8 : 0)
        - (Number.isFinite(leftPrice) && Math.abs(leftPrice - 0.5) < 0.0001 && leftTrades <= 0 && leftVolume < 25 ? 45 : 0);
      const rightScore = Math.min(70, Math.pow(Math.max(rightVolume, 0), 0.35))
        + Math.min(70, Math.max(rightTrades, 0) * 3)
        + rightDistance * 24
        + rightBlockClose * 28
        + (right.marketId ? 12 : 0)
        + (right.yesTokenId ? 8 : 0)
        - (Number.isFinite(rightPrice) && Math.abs(rightPrice - 0.5) < 0.0001 && rightTrades <= 0 && rightVolume < 25 ? 45 : 0);
      return rightScore - leftScore || rightVolume - leftVolume || rightTrades - leftTrades;
    })[0] || null;
  defaultOutcomes.set(group, selected);
  return selected;
}

function groupHasFocusableDefault(group: MarketGroupItem, requireActivity = true) {
  const selected = groupDefaultOutcome(group);
  if (!selected || !groupOutcomeIsFocusable(selected, false)) return false;
  if (!requireActivity || groupOutcomeHasActivity(selected)) return true;
  const outcomes = uniqueGroupOutcomes([...(group.outcomes || []), ...(group.topOutcomes || [])])
    .filter((outcome) => outcome.marketId || outcome.yesTokenId);
  let outcomeVolume = 0;
  let outcomeTrades = 0;
  let hasOutcomeActivityFields = false;
  outcomes.forEach((outcome) => {
    const volume = Number(outcome.volume24h || 0);
    const trades = Number(outcome.tradeCount24h || 0);
    if (volume > 0 || trades > 0) hasOutcomeActivityFields = true;
    if (groupOutcomeIsTerminal(outcome)) return;
    outcomeVolume += volume;
    outcomeTrades += trades;
  });
  if (outcomeTrades >= 1 || outcomeVolume >= 25) return true;
  if (hasOutcomeActivityFields) return false;
  return Number(group.tradeCount24h || 0) >= 1 || Number(group.volume24h || 0) >= 25;
}

function groupHasMarketCoverage(group: MarketGroupItem) {
  if (groupDefaultOutcome(group)) return true;
  if (Number(groupDisplayVolume(group) || 0) > 0) return true;
  if (Number(groupDisplayTradeCount(group) || 0) > 0) return true;
  if (Number(group.outcomeCount || group.outcomes?.length || group.topOutcomes?.length || 0) > 0) return true;
  return false;
}

function marketActivityLabel(
  tradeCountValue: string | number | null | undefined,
  volumeValue: string | number | null | undefined,
  i18n: MarketI18n,
) {
  const tradeCount = Number(tradeCountValue);
  if (tradeCount > 0) return i18n.t('atlasMarket.transactions', { count: localizedCompact(tradeCount, i18n) });
  if (Number(volumeValue) > 0) return i18n.t('atlasMarket.activity24h');
  return null;
}

function groupActivityTimestamp(group: MarketGroupItem) {
  return parseTimestamp(group.lastActivityAt) || parseTimestamp(group.createdAt);
}

function groupActiveRank(group: MarketGroupItem) {
  const now = Date.now();
  const activityTs = groupActivityTimestamp(group);
  const createdTs = parseTimestamp(group.createdAt);
  const activityAgeHours = activityTs ? (now - activityTs) / 36e5 : Number.POSITIVE_INFINITY;
  const createdAgeHours = createdTs ? (now - createdTs) / 36e5 : Number.POSITIVE_INFINITY;
  const volume = Number(groupDisplayVolume(group) || 0);
  const trades = Number(groupDisplayTradeCount(group) || 0);
  const price = Number(groupBestLivePrice(group));
  const tradableSignal = Number.isFinite(price) && price > 0.03 && price < 0.97 ? 1 : 0;
  const staleMidPenalty = Number.isFinite(price) && Math.abs(price - 0.5) < 0.0001 && trades <= 0 && volume < 25 ? 180 : 0;
  const freshness =
    trades > 0 ? 700 :
    volume > 0 && activityAgeHours <= 168 ? 620 :
    volume > 0 && createdAgeHours <= 168 ? 580 :
    volume >= 100000 ? 520 :
    volume > 0 && activityAgeHours <= 336 ? 460 :
    createdAgeHours <= 48 ? 280 :
    activityAgeHours <= 72 ? 240 :
    createdAgeHours <= 168 ? 180 :
    0;
  const activityWeight = Math.log10(Math.max(volume, 0) + 1) * 38 + Math.log10(Math.max(trades, 0) + 1) * 62;
  const multiOutcomeBonus = Number(group.outcomeCount || group.outcomes?.length || 0) > 2 ? 18 : 0;
  return freshness + activityWeight + multiOutcomeBonus + tradableSignal * 24 - staleMidPenalty;
}

function groupBestLivePrice(group: MarketGroupItem) {
  const selectedOutcome = groupDefaultOutcome(group);
  const selectedPrice = selectedOutcome ? Number(groupOutcomePrice(selectedOutcome)) : NaN;
  if (Number.isFinite(selectedPrice)) return selectedPrice;
  const blockClosePrice = Number(group.latestBlockClosePrice);
  if (Number.isFinite(blockClosePrice)) return blockClosePrice;
  const candidates = [...(group.outcomes || []), ...(group.topOutcomes || [])]
    .map((outcome) => Number(outcome.blockCloseYesPrice ?? outcome.yesPrice))
    .filter((value) => Number.isFinite(value));
  if (!candidates.length) return null;
  return candidates
    .slice()
    .sort((left, right) => Math.abs(left - 0.5) - Math.abs(right - 0.5))[0] ?? null;
}

function groupHasTerminalProbability(group: MarketGroupItem) {
  if (isTerminalProbability(group.latestBlockClosePrice)) return true;
  const selected = groupDefaultOutcome(group);
  return selected ? groupOutcomeIsTerminal(selected) : false;
}

function diversifyActiveGroups(groups: MarketGroupItem[]) {
  const firstScreenLimit = Math.min(groups.length, 24);
  const categoryLimit = Math.max(2, Math.min(4, Math.floor(firstScreenLimit / 6) || 1));
  const selected: MarketGroupItem[] = [];
  const deferred: MarketGroupItem[] = [];
  const topicCounts = new Map<string, number>();
  const seen = new Set<string>();
  for (const group of groups) {
    const key = String(group.eventId ?? group.groupId ?? group.slug ?? '');
    if (key && seen.has(key)) continue;
    const topic = groupTopic(group);
    if (selected.length < firstScreenLimit && (topicCounts.get(topic) || 0) >= categoryLimit) {
      deferred.push(group);
      continue;
    }
    selected.push(group);
    if (key) seen.add(key);
    topicCounts.set(topic, (topicCounts.get(topic) || 0) + 1);
  }
  for (const group of deferred) {
    const key = String(group.eventId ?? group.groupId ?? group.slug ?? '');
    if (key && seen.has(key)) continue;
    selected.push(group);
    if (key) seen.add(key);
  }
  return selected;
}

function groupIsExpired(group: MarketGroupItem) {
  const endAt = parseTimestamp(group.endDate);
  return Boolean(endAt && endAt < Date.now());
}

function timestampOrInfinity(value: string | null | undefined) {
  const parsed = parseTimestamp(value);
  return parsed || Number.POSITIVE_INFINITY;
}

function groupMoveScore(group: MarketGroupItem) {
  return Math.max(
    0,
    ...[...(group.outcomes || []), ...(group.topOutcomes || [])]
      .map((outcome) => Math.abs(Number(outcome.change24h || 0)))
      .filter(Number.isFinite),
  );
}

function activeMarketGroupsList(
  groups: MarketGroupItem[],
  selectedMarketId: number | null,
  selectedMarketGroupId: string | null,
  focusMarketGroup: (group: MarketGroupItem, outcomeKey?: string | null, marketId?: number | null) => void,
  prefetchMarketFocus: (marketIds: number[]) => void,
  queueMarketPrefetch: (marketIds: number[]) => void,
  cancelMarketPrefetch: () => void,
  i18n: MarketI18n,
) {
  if (!groups.length) return emptyState(i18n.t('atlasMarket.noGroups'), localizedEmptyCopy(i18n));
  return (
    <div className="wm-poly-market-list">
      {groups.map((group, index) => {
        const defaultOutcome = groupDefaultOutcome(group);
        const outcomeTitle = defaultOutcome?.title || defaultOutcome?.label || null;
        const displaysOutcome = Boolean(defaultOutcome && outcomeTitle);
        const displayTitle = outcomeTitle || group.title;
        const displayVolume = displaysOutcome
          ? firstFiniteValue(defaultOutcome?.volume24h)
          : groupDisplayVolume(group);
        const displayTradeCount = displaysOutcome
          ? firstFiniteValue(defaultOutcome?.tradeCount24h)
          : groupDisplayTradeCount(group);
        const activityLabel = marketActivityLabel(displayTradeCount, displayVolume, i18n);
        const defaultMarketId = defaultOutcome?.marketId ? Number(defaultOutcome.marketId) : defaultGroupMarketId(group);
        const groupEventId = group.eventId != null ? String(group.eventId) : null;
        const selected = (groupEventId != null && selectedMarketGroupId === groupEventId) || (defaultMarketId != null && selectedMarketId === defaultMarketId);
        const adjacentMarketIds = [groups[index - 1], group, groups[index + 1]]
          .map((candidate) => candidate ? defaultGroupMarketId(candidate) : null)
          .filter((marketId): marketId is number => marketId != null && Number.isFinite(marketId));
        return (
          <button
            key={group.groupId}
            type="button"
            className={`wm-poly-market-card ${topicClassName(groupTopic(group))} ${selected ? 'active' : ''}`}
            onClick={() => {
              focusMarketGroup(group, defaultOutcome?.outcomeKey || group.defaultOutcomeKey || null, defaultMarketId);
            }}
            onMouseEnter={() => queueMarketPrefetch(adjacentMarketIds)}
            onMouseLeave={cancelMarketPrefetch}
            onFocus={() => queueMarketPrefetch(adjacentMarketIds)}
            onBlur={cancelMarketPrefetch}
            onPointerDown={() => {
              cancelMarketPrefetch();
              if (defaultMarketId != null) prefetchMarketFocus([defaultMarketId]);
            }}
            aria-pressed={selected}
            title={displayTitle === group.title ? group.title : `${displayTitle}\n${group.title}`}
            style={{ '--wm-market-accent': groupAccent(group), borderLeftColor: groupAccent(group) } as Record<string, string>}
          >
            <div className="wm-poly-market-card-main">
              <div className="wm-poly-market-meta">
                <span className="wm-poly-market-dot" />
                <span>{groupTopic(group)}</span>
                <span>·</span>
                <span><MarketTiming group={group} i18n={i18n} /></span>
                <span>·</span>
                <span>{groupOutcomeLabel(group, i18n)}</span>
              </div>
              <strong className="wm-poly-market-title">{displayTitle}</strong>
              <div className="wm-poly-market-bottom">
                <span className="wm-poly-market-prob">{localizedPercent(groupBestLivePrice(group), i18n)}</span>
                <span className="wm-poly-market-activity">
                  <span className="wm-poly-market-volume">{i18n.t(
                    displaysOutcome ? 'atlasMarket.marketVolume24h' : 'atlasMarket.eventVolume24h',
                    { value: localizedCurrency(displayVolume, i18n) },
                  )}</span>
                  {activityLabel ? <span className="wm-poly-market-trades">{activityLabel}</span> : null}
                </span>
              </div>
            </div>
            <span className="wm-poly-market-star" aria-hidden="true">☆</span>
          </button>
        );
      })}
    </div>
  );
}

function activeMarketsList(
  markets: MarketListItem[],
  selectedMarketId: number | null,
  setSelectedMarketId: (marketId: number | null) => void,
  prefetchMarketFocus: (marketIds: number[]) => void,
  queueMarketPrefetch: (marketIds: number[]) => void,
  cancelMarketPrefetch: () => void,
  i18n: MarketI18n,
) {
  if (!markets.length) return emptyState(i18n.t('atlasMarket.noMarkets'), localizedEmptyCopy(i18n));
  return (
    <div className="wm-poly-market-list">
      {markets.map((market, index) => {
        const activityLabel = marketActivityLabel(market.tradeCount24h, market.volume24h, i18n);
        const adjacentMarketIds = [markets[index - 1]?.id, market.id, markets[index + 1]?.id]
          .filter((marketId): marketId is number => marketId != null && Number.isFinite(marketId));
        return (
          <button
            key={market.id}
            type="button"
            className={`wm-poly-market-card ${topicClassName(marketTopic(market))} ${selectedMarketId === market.id ? 'active' : ''}`}
            onClick={() => setSelectedMarketId(market.id)}
            onMouseEnter={() => queueMarketPrefetch(adjacentMarketIds)}
            onMouseLeave={cancelMarketPrefetch}
            onFocus={() => queueMarketPrefetch(adjacentMarketIds)}
            onBlur={cancelMarketPrefetch}
            onPointerDown={() => {
              cancelMarketPrefetch();
              prefetchMarketFocus([market.id]);
            }}
            aria-pressed={selectedMarketId === market.id}
            title={`${market.title}${market.slug ? ` · ${market.slug}` : ''}`}
            style={{ '--wm-market-accent': marketAccent(market) } as Record<string, string>}
          >
            <div className="wm-poly-market-card-main">
              <div className="wm-poly-market-meta">
                <span className="wm-poly-market-dot" />
                <span>{marketTopic(market)}</span>
                <span>·</span>
                <span><MarketTiming market={market} i18n={i18n} /></span>
                <span>·</span>
                <span>{marketOutcomeLabel(market, i18n)}</span>
              </div>
              <strong className="wm-poly-market-title">{market.title}</strong>
              <div className="wm-poly-market-bottom">
                <span className="wm-poly-market-prob">{localizedPercent(market.latestPrice, i18n)}</span>
                <span className="wm-poly-market-activity">
                  <span className="wm-poly-market-volume">{i18n.t('atlasMarket.volume', { value: localizedCurrency(market.volume24h, i18n) })}</span>
                  {activityLabel ? <span className="wm-poly-market-trades">{activityLabel}</span> : null}
                </span>
              </div>
            </div>
            <span className="wm-poly-market-star" aria-hidden="true">☆</span>
          </button>
        );
      })}
    </div>
  );
}

const CatalogClock = createContext(0);
function MarketTiming({ group, market, i18n }: { group?: MarketGroupItem; market?: MarketListItem; i18n: MarketI18n }) {
  useContext(CatalogClock); // Only changing relative-time text consumes the clock.
  return <>{group ? groupTiming(group, i18n) : marketTiming(market!, i18n)}</>;
}

function ActiveMarketsPanel({
  markets,
  marketGroups,
  marketGroupSort,
  setMarketGroupSort,
  selectedMarketId,
  selectedMarketGroupId,
  setSelectedMarketId,
  prefetchMarketFocus,
  focusMarketGroup,
  marketCatalogRefreshing,
  marketCatalogError,
  refreshMarketCatalog,
}: {
  markets: MarketListItem[];
  marketGroups: MarketGroupItem[];
  marketGroupSort: MarketGroupSort;
  setMarketGroupSort: (sort: MarketGroupSort) => void;
  selectedMarketId: number | null;
  selectedMarketGroupId: string | null;
  setSelectedMarketId: (marketId: number | null) => void;
  prefetchMarketFocus: (marketIds: number[]) => void;
  focusMarketGroup: (group: MarketGroupItem, outcomeKey?: string | null, marketId?: number | null) => void;
  marketCatalogRefreshing: boolean;
  marketCatalogError: string | null;
  refreshMarketCatalog: () => Promise<void>;
}) {
  const i18n = useI18n();
  const { t } = i18n;
  const [search, setSearch] = useState('');
  const [clockNow, setClockNow] = useState(() => Date.now());
  const prefetchTimerRef = useRef<number | undefined>(undefined);

  const cancelMarketPrefetch = useCallback(() => {
    if (prefetchTimerRef.current !== undefined) {
      window.clearTimeout(prefetchTimerRef.current);
      prefetchTimerRef.current = undefined;
    }
  }, []);

  const queueMarketPrefetch = useCallback((marketIds: number[]) => {
    cancelMarketPrefetch();
    const uniqueMarketIds = [...new Set(marketIds.filter((marketId) => Number.isFinite(marketId)))].slice(0, 3);
    if (!uniqueMarketIds.length) return;
    prefetchTimerRef.current = window.setTimeout(() => {
      prefetchTimerRef.current = undefined;
      prefetchMarketFocus(uniqueMarketIds);
    }, 150);
  }, [prefetchMarketFocus, cancelMarketPrefetch]);

  useEffect(() => {
    const timer = window.setInterval(() => setClockNow(Date.now()), 1_000);
    return () => {
      window.clearInterval(timer);
      cancelMarketPrefetch();
    };
  }, []);

  const visibleGroups = useMemo(() => {
    const query = search.trim().toLowerCase();
    const filtered = query
      ? marketGroups.filter((group) => {
          const haystack = [
            group.title,
            group.slug,
            group.category,
            ...(group.tags || []),
            ...(group.outcomes || []).map((outcome) => outcome.label || outcome.title || ''),
          ]
            .filter(Boolean)
            .join(' ')
            .toLowerCase();
          return haystack.includes(query);
        })
      : [...marketGroups];
    const liveFiltered = filtered.filter((group) => (
      query || (!groupIsExpired(group) && !groupHasTerminalProbability(group) && groupHasFocusableDefault(group, true))
    ));
    if (marketGroupSort === 'new') return liveFiltered.sort((a, b) => parseTimestamp(b.createdAt) - parseTimestamp(a.createdAt));
    if (marketGroupSort === 'volume') return liveFiltered.sort((a, b) => Number(groupDisplayVolume(b) || 0) - Number(groupDisplayVolume(a) || 0));
    if (marketGroupSort === 'close') return liveFiltered.sort((a, b) => timestampOrInfinity(a.endDate) - timestampOrInfinity(b.endDate));
    if (marketGroupSort === 'move') return liveFiltered.sort((a, b) => groupMoveScore(b) - groupMoveScore(a));
    if (marketGroupSort === 'trades') return liveFiltered.sort((a, b) => Number(groupDisplayTradeCount(b) || 0) - Number(groupDisplayTradeCount(a) || 0));
    return diversifyActiveGroups(liveFiltered.sort((a, b) => groupActiveRank(b) - groupActiveRank(a)));
  }, [marketGroupSort, marketGroups, search]);

  const visibleMarkets = useMemo(() => {
    const query = search.trim().toLowerCase();
    const filtered = query
      ? markets.filter((market) => {
          const haystack = [
            market.title,
            market.slug,
            market.category,
            market.status,
            ...(market.tags || []),
          ]
            .filter(Boolean)
            .join(' ')
            .toLowerCase();
          return haystack.includes(query);
        })
      : markets.filter((market) => !isDefaultSuppressedMarket(market));
    const ranked = filtered.sort((a, b) => {
      if (marketGroupSort === 'new') return parseTimestamp(b.createdAt) - parseTimestamp(a.createdAt);
      if (marketGroupSort === 'volume') return Number(b.volume24h || 0) - Number(a.volume24h || 0);
      if (marketGroupSort === 'close') return timestampOrInfinity(a.endDate) - timestampOrInfinity(b.endDate);
      if (marketGroupSort === 'move') return Math.abs(Number(b.change24h || 0)) - Math.abs(Number(a.change24h || 0));
      if (marketGroupSort === 'trades') return Number(b.tradeCount24h || 0) - Number(a.tradeCount24h || 0);
      return 0;
    });
    return query ? ranked : ranked;
  }, [marketGroupSort, markets, search]);

  const hasGroups = marketGroups.length > 0 && visibleGroups.some(groupHasMarketCoverage);
  const panelCount = hasGroups ? visibleGroups.length : visibleMarkets.length;
  const catalogGeneratedAt = useMemo(() => marketCatalogGeneratedAt(marketGroups), [marketGroups]);
  const catalogActivityAt = useMemo(() => marketCatalogActivityAt(marketGroups), [marketGroups]);
  const catalogSyncAge = catalogGeneratedAt ? Math.max(0, clockNow - catalogGeneratedAt) : Number.POSITIVE_INFINITY;
  const catalogActivityAge = catalogActivityAt ? Math.max(0, clockNow - catalogActivityAt) : Number.POSITIVE_INFINITY;
  const catalogTone = marketCatalogError
    ? 'error'
    : !catalogGeneratedAt
      ? 'waiting'
      : catalogSyncAge > MARKET_CATALOG_SYNC_DELAYED_MS
        ? 'delayed'
        : catalogActivityAge > MARKET_ACTIVITY_STALE_MS
          ? 'stale'
          : catalogActivityAge > MARKET_ACTIVITY_DELAYED_MS
            ? 'delayed'
            : 'fresh';
  const catalogStatusLabel = marketCatalogRefreshing
    ? t('atlasMarket.catalog.refreshing')
    : catalogTone === 'fresh'
      ? t('atlasMarket.catalog.fresh')
      : catalogTone === 'stale'
        ? t('atlasMarket.catalog.stale')
        : catalogTone === 'error'
          ? t('atlasMarket.catalog.error')
          : catalogTone === 'waiting'
            ? t('atlasMarket.catalog.waiting')
            : t('atlasMarket.catalog.delayed');
  const generatedAtLabel = catalogGeneratedAt
    ? i18n.formatRelativeTime(new Date(catalogGeneratedAt).toISOString())
    : '--';
  const activityAtLabel = catalogActivityAt
    ? i18n.formatRelativeTime(new Date(catalogActivityAt).toISOString())
    : '--';
  const sortHelp = t(MARKET_SORT_HELP_KEYS[marketGroupSort]);
  const rows = useMemo(() => hasGroups
    ? activeMarketGroupsList(visibleGroups, selectedMarketId, selectedMarketGroupId, focusMarketGroup, prefetchMarketFocus, queueMarketPrefetch, cancelMarketPrefetch, i18n)
    : activeMarketsList(visibleMarkets, selectedMarketId, setSelectedMarketId, prefetchMarketFocus, queueMarketPrefetch, cancelMarketPrefetch, i18n),
    [hasGroups, visibleGroups, visibleMarkets, selectedMarketId, selectedMarketGroupId, focusMarketGroup,
      setSelectedMarketId, prefetchMarketFocus, queueMarketPrefetch, cancelMarketPrefetch, i18n]);


  return (
    <Panel
      title={t('atlasMarket.markets')}
      badge={catalogStatusLabel}
      status={catalogTone === 'fresh' ? 'live' : 'muted'}
      count={panelCount}
      className={`wm-market-panel wm-market-catalog-${catalogTone}`}
      controls={
        <div className="wm-market-panel-controls">
          <select
            className="wm-market-sort"
            value={marketGroupSort}
            onInput={(event) => setMarketGroupSort(event.currentTarget.value as MarketGroupSort)}
            aria-label={t('atlasMarket.sort')}
          >
            {MARKET_SORT_OPTIONS.map(({ value, label }) => <option key={value} value={value}>{t(label)}</option>)}
          </select>
          <span className="wm-market-sort-caption" aria-hidden="true">
            {t(MARKET_SORT_OPTIONS.find(option => option.value === marketGroupSort)!.label)}
          </span>
        </div>
      }
    >
      <label className="wm-market-search wm-market-search-body" aria-label={t('atlasMarket.search')}>
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
          <circle cx="7" cy="7" r="4.8" />
          <path d="M10.8 10.8 14 14" />
        </svg>
        <input
          type="search"
          value={search}
          onInput={(event) => setSearch(event.currentTarget.value)}
          placeholder={t('atlasMarket.searchPlaceholder')}
        />
      </label>
      <div className={`wm-market-catalog-health is-${catalogTone}`} role="status" aria-live="polite">
        <div>
          <span className="wm-market-catalog-dot" aria-hidden="true" />
          <strong>{catalogStatusLabel}</strong>
          <span>{t('atlasMarket.catalog.activity', { time: activityAtLabel })}</span>
        </div>
        <button
          type="button"
          className="wm-market-refresh"
          onClick={() => void refreshMarketCatalog()}
          disabled={marketCatalogRefreshing}
          title={marketCatalogError || t('atlasMarket.catalog.refreshTitle')}
        >
          {marketCatalogRefreshing ? t('atlasMarket.catalog.refreshingShort') : t('atlasMarket.catalog.refresh')}
        </button>
      </div>
      <div className="wm-market-sort-explainer">
        <span>{sortHelp}</span>
        <em>{t('atlasMarket.catalog.sync', { time: generatedAtLabel })} · {t('atlasMarket.catalog.auto', { seconds: MARKET_CATALOG_AUTO_REFRESH_MS / 1000 })}</em>
      </div>
      <CatalogClock.Provider value={clockNow}>{rows}</CatalogClock.Provider>
    </Panel>
  );
}

const renderers: PanelRenderMap<'bootstrap' | 'focusMarketGroup' | 'marketCatalogError' | 'marketCatalogRefreshing' | 'marketGroupSort' | 'marketGroups' | 'markets' | 'prefetchMarketFocus' | 'refreshMarketCatalog' | 'selectedMarketGroupId' | 'selectedMarketId' | 'setMarketGroupSort' | 'setSelectedMarketId'> = {
  'active-markets': {
    render: (ctx) => (
      <ActiveMarketsPanel
        markets={globalMarkets(ctx)}
        marketGroups={ctx.marketGroups}
        marketGroupSort={ctx.marketGroupSort}
        setMarketGroupSort={ctx.setMarketGroupSort}
        selectedMarketId={ctx.selectedMarketId}
        selectedMarketGroupId={ctx.selectedMarketGroupId}
        setSelectedMarketId={ctx.setSelectedMarketId}
        prefetchMarketFocus={ctx.prefetchMarketFocus}
        focusMarketGroup={ctx.focusMarketGroup}
        marketCatalogRefreshing={ctx.marketCatalogRefreshing}
        marketCatalogError={ctx.marketCatalogError}
        refreshMarketCatalog={ctx.refreshMarketCatalog}
      />
    ),
  },
};

export const panel = panelFromRenderer(renderers, {
  contextKeys: ['bootstrap', 'focusMarketGroup', 'marketCatalogError', 'marketCatalogRefreshing', 'marketGroupSort', 'marketGroups', 'markets', 'prefetchMarketFocus', 'refreshMarketCatalog', 'selectedMarketGroupId', 'selectedMarketId', 'setMarketGroupSort', 'setSelectedMarketId'],
  id: 'active-markets',
  title: 'Active Markets',
  eyebrow: 'market',
  description: 'Live active market list.',
  defaultEnabled: true,
});
