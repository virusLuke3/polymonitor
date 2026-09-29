import type { MarketListItem, MarketGroupItem, MarketGroupDetail, MarketGroupOutcome, MarketSummary, WorkspaceBundle } from '@/types';

function isLiveStatus(status?: string | null) {
  const normalized = String(status || '').trim().toLowerCase();
  return normalized === 'active' || normalized === 'proposed';
}

type DefaultMarketCandidate = Pick<MarketSummary, 'id' | 'slug' | 'title' | 'category' | 'tags' | 'status'>;

export function isSuppressedDefaultMarket(market?: Partial<DefaultMarketCandidate> | null) {
  const text = [
    market?.title,
    market?.slug,
    market?.category,
    ...(market?.tags || []),
  ].filter(Boolean).join(' ').toLowerCase();
  return (
    text.includes(' up or down - ')
    || text.includes('updown-5m')
    || text.includes('updown-15m')
    || text.includes('recurring')
    || text.includes('hide-from-new')
    || text.includes('onchain-registry')
    || text.includes('on-chain recovered market')
  );
}

export function pickDefaultMarketId(markets: MarketListItem[], featured?: MarketSummary | null) {
  const firstLive = markets.find((market) => isLiveStatus(market.status) && !isSuppressedDefaultMarket(market));
  if (firstLive) return firstLive.id;
  const firstEligible = markets.find((market) => !isSuppressedDefaultMarket(market));
  if (firstEligible) return firstEligible.id;
  if (featured && !isSuppressedDefaultMarket(featured)) return featured.id;
  return markets[0]?.id ?? featured?.id ?? null;
}

function groupHasTerminalProbability(group: MarketGroupItem) {
  const values = [
    group.latestBlockClosePrice,
    ...(group.outcomes || []).flatMap((outcome) => [outcome.blockCloseYesPrice, outcome.yesPrice, outcome.noPrice]),
    ...(group.topOutcomes || []).flatMap((outcome) => [outcome.blockCloseYesPrice, outcome.yesPrice, outcome.noPrice]),
  ];
  return values.some((value) => {
    const numeric = Number(value);
    return Number.isFinite(numeric) && (numeric <= 0.03 || numeric >= 0.97);
  });
}

function groupOutcomePrice(outcome: { blockCloseYesPrice?: string | number | null; yesPrice?: string | number | null }) {
  const blockClose = Number(outcome.blockCloseYesPrice);
  if (Number.isFinite(blockClose)) return blockClose;
  const yes = Number(outcome.yesPrice);
  return Number.isFinite(yes) ? yes : null;
}

function groupOutcomeIsTerminal(outcome: { blockCloseYesPrice?: string | number | null; yesPrice?: string | number | null }) {
  const price = groupOutcomePrice(outcome);
  return price != null && (price <= 0.03 || price >= 0.97);
}

export function pickDefaultGroupOutcome(group: MarketGroupItem, outcomeKey?: string | null, marketId?: number | null) {
  const seen = new Set<string>();
  const candidates = [...(group.outcomes || []), ...(group.topOutcomes || [])].filter((outcome, index) => {
    if (!outcome.marketId && !outcome.yesTokenId) return false;
    const key = String(outcome.marketId ?? outcome.outcomeKey ?? outcome.gammaMarketId ?? index);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const liveCandidates = candidates.filter((outcome) => !groupOutcomeIsTerminal(outcome));
  const eligible = liveCandidates.length ? liveCandidates : candidates;
  const requestedMarketId = marketId != null ? Number(marketId) : null;
  if (requestedMarketId != null && Number.isFinite(requestedMarketId)) {
    const matched = eligible.find((outcome) => Number(outcome.marketId) === requestedMarketId);
    if (matched) return matched;
  }
  if (outcomeKey) {
    const matched = eligible.find((outcome) => outcome.outcomeKey === outcomeKey);
    if (matched) return matched;
  }
  if (group.defaultOutcomeKey) {
    const matched = eligible.find((outcome) => outcome.outcomeKey === group.defaultOutcomeKey);
    if (matched) return matched;
  }
  return eligible
    .slice()
    .sort((left, right) => {
      const leftPrice = groupOutcomePrice(left);
      const rightPrice = groupOutcomePrice(right);
      const leftVolume = Number(left.volume24h || 0);
      const rightVolume = Number(right.volume24h || 0);
      const leftTrades = Number(left.tradeCount24h || 0);
      const rightTrades = Number(right.tradeCount24h || 0);
      const leftDistance = leftPrice == null ? 0 : Math.min(1, Math.abs(leftPrice - 0.5) * 2);
      const rightDistance = rightPrice == null ? 0 : Math.min(1, Math.abs(rightPrice - 0.5) * 2);
      const leftBlockClose = left.blockCloseYesPrice == null || left.blockCloseYesPrice === '' ? 0 : 1;
      const rightBlockClose = right.blockCloseYesPrice == null || right.blockCloseYesPrice === '' ? 0 : 1;
      const leftScore = Math.min(70, Math.pow(Math.max(leftVolume, 0), 0.35))
        + Math.min(70, Math.max(leftTrades, 0) * 3)
        + leftDistance * 24
        + leftBlockClose * 28
        + (left.marketId ? 12 : 0)
        + (left.yesTokenId ? 8 : 0)
        - (leftPrice != null && Math.abs(leftPrice - 0.5) < 0.0001 && leftTrades <= 0 && leftVolume < 25 ? 45 : 0);
      const rightScore = Math.min(70, Math.pow(Math.max(rightVolume, 0), 0.35))
        + Math.min(70, Math.max(rightTrades, 0) * 3)
        + rightDistance * 24
        + rightBlockClose * 28
        + (right.marketId ? 12 : 0)
        + (right.yesTokenId ? 8 : 0)
        - (rightPrice != null && Math.abs(rightPrice - 0.5) < 0.0001 && rightTrades <= 0 && rightVolume < 25 ? 45 : 0);
      return rightScore - leftScore || rightVolume - leftVolume || rightTrades - leftTrades;
    })[0] || null;
}

export function pickDefaultMarketGroup(groups: MarketGroupItem[]) {
  const eligibleGroups = groups.filter((group) => !groupHasTerminalProbability(group) || pickDefaultGroupOutcome(group));
  const liveGroups = eligibleGroups.filter((group) => Number(group.tradeCount24h || 0) > 0);
  return (
    liveGroups.find((group) => Number(group.volume24h || 0) > 0 && Number(group.outcomeCount || 0) > 1)
    || liveGroups.find((group) => Number(group.outcomeCount || 0) > 1)
    || liveGroups[0]
    || eligibleGroups[0]
    || null
  );
}

export function findGroupForMarketId(groups: MarketGroupItem[], marketId: number | null) {
  if (!marketId) return null;
  return groups.find((group) => (group.outcomes || []).some((outcome) => Number(outcome.marketId) === marketId)) || null;
}

export function outcomeKeyForGroupMarket(group: MarketGroupItem, marketId?: number | null, fallbackKey?: string | null) {
  const numericMarketId = marketId != null ? Number(marketId) : null;
  if (numericMarketId != null && Number.isFinite(numericMarketId)) {
    const matchedOutcome = [...(group.outcomes || []), ...(group.topOutcomes || [])]
      .find((outcome) => Number(outcome.marketId) === numericMarketId);
    if (matchedOutcome?.outcomeKey) return matchedOutcome.outcomeKey;
  }
  return fallbackKey || group.defaultOutcomeKey || null;
}

export function optimisticBundleFromMarket(market: MarketListItem): WorkspaceBundle {
  const latest = market.latestPrice ?? null;
  const numericLatest = Number(latest);
  const latestNo = Number.isFinite(numericLatest) ? String(1 - numericLatest) : null;
  const timestamp = market.lastTradeAt || market.createdAt || new Date().toISOString();
  return {
    market: {
      id: market.id,
      slug: market.slug,
      title: market.title,
      conditionId: market.conditionId,
      questionId: market.questionId,
      status: market.status,
      latestPrice: latest,
      latestYesPrice: latest,
      latestNoPrice: latestNo,
      endDate: market.endDate,
      createdAt: market.createdAt,
      category: market.category,
      tags: market.tags,
      yesTokenId: market.yesTokenId,
      noTokenId: market.noTokenId,
    },
    identity: {
      localMarketId: market.id,
      marketId: market.id,
      gammaMarketId: market.gammaMarketId,
      slug: market.slug,
      conditionId: market.conditionId,
      questionId: market.questionId,
      yesTokenId: market.yesTokenId,
      noTokenId: market.noTokenId,
    },
    diagnostics: null,
    health: null,
    group: null,
    selectedOutcome: null,
    trades: [],
    oracle: null,
    price: {
      marketId: market.id,
      latestPrice: latest == null ? null : String(latest),
      latestYesPrice: latest == null ? null : String(latest),
      latestNoPrice: latestNo,
      change24h: market.change24h == null ? null : String(market.change24h),
      volume24h: market.volume24h == null ? null : String(market.volume24h),
      tradeCount24h: Number(market.tradeCount24h || 0),
      updatedAt: timestamp,
    },
    chart: latest == null
      ? null
      : {
          marketId: market.id,
          range: 'snapshot',
          interval: 'snapshot',
          kind: 'probability',
          points: [
            { timestamp, yesPrice: latest, noPrice: latestNo },
            { timestamp: new Date().toISOString(), yesPrice: latest, noPrice: latestNo },
          ],
        },
    content: null,
    lob: null,
  };
}

export function optimisticBundleFromGroup(group: MarketGroupItem, marketId: number | null, outcomeKey?: string | null): WorkspaceBundle {
  const selectedOutcome = pickDefaultGroupOutcome(group, outcomeKey, marketId);
  const selectedMarketId = Number(selectedOutcome?.marketId ?? marketId ?? group.defaultMarketId ?? 0);
  const price = selectedOutcome?.blockCloseYesPrice ?? selectedOutcome?.yesPrice ?? group.latestBlockClosePrice ?? null;
  const numericPrice = Number(price);
  const noPrice = selectedOutcome?.noPrice ?? (Number.isFinite(numericPrice) ? String(1 - numericPrice) : null);
  const timestamp = selectedOutcome?.lastTradeAt || group.lastActivityAt || group.createdAt || new Date().toISOString();
  const marketSlug = selectedOutcome?.slug || group.slug || `market-${selectedMarketId || group.groupId}`;
  const optimisticGroup: MarketGroupDetail = {
    ...group,
    generatedAt: group.generatedAt || new Date().toISOString(),
    status: 'optimistic',
  };
  return {
    market: selectedMarketId ? {
      id: selectedMarketId,
      slug: marketSlug,
      title: selectedOutcome?.title || selectedOutcome?.label || group.title,
      status: 'OPEN',
      latestPrice: price == null ? null : String(price),
      latestYesPrice: price == null ? null : String(price),
      latestNoPrice: noPrice == null ? null : String(noPrice),
      endDate: group.endDate || null,
      createdAt: group.createdAt || null,
      category: group.category || undefined,
      tags: group.tags || [],
      yesTokenId: selectedOutcome?.yesTokenId ?? null,
      noTokenId: selectedOutcome?.noTokenId ?? null,
    } : null,
    identity: {
      localMarketId: selectedMarketId || null,
      marketId: selectedMarketId || null,
      gammaMarketId: selectedOutcome?.gammaMarketId ?? null,
      slug: marketSlug,
      conditionId: selectedOutcome?.conditionId ?? null,
      eventId: group.eventId == null ? null : String(group.eventId),
      selectedOutcomeKey: selectedOutcome?.outcomeKey ?? outcomeKey ?? group.defaultOutcomeKey ?? null,
      yesTokenId: selectedOutcome?.yesTokenId ?? null,
      noTokenId: selectedOutcome?.noTokenId ?? null,
    },
    diagnostics: null,
    health: null,
    group: optimisticGroup,
    selectedOutcome,
    trades: [],
    oracle: null,
    price: {
      marketId: selectedMarketId || 0,
      latestPrice: price == null ? null : String(price),
      latestYesPrice: price == null ? null : String(price),
      latestNoPrice: noPrice == null ? null : String(noPrice),
      change24h: selectedOutcome?.change24h == null ? null : String(selectedOutcome.change24h),
      volume24h: selectedOutcome?.volume24h == null
        ? (group.volume24h == null ? null : String(group.volume24h))
        : String(selectedOutcome.volume24h),
      tradeCount24h: Number(selectedOutcome?.tradeCount24h ?? group.tradeCount24h ?? 0),
      updatedAt: timestamp,
    },
    chart: Number.isFinite(numericPrice) && selectedMarketId
      ? {
          marketId: selectedMarketId,
          range: 'snapshot',
          interval: 'snapshot',
          kind: 'probability',
          points: [
            { timestamp, yesPrice: String(price), noPrice },
            { timestamp: new Date().toISOString(), yesPrice: String(price), noPrice },
          ],
        }
      : null,
    content: null,
    lob: null,
  };
}

export function emptyWorkspaceBundle(): WorkspaceBundle {
  return {
    market: null,
    identity: null,
    diagnostics: null,
    health: null,
    group: null,
    selectedOutcome: null,
    trades: [],
    oracle: null,
    price: null,
    chart: null,
    content: null,
    lob: null,
  };
}

function isSnapshotChart(chart: WorkspaceBundle['chart']) {
  if (!chart) return false;
  return chart.range === 'snapshot' || chart.interval === 'snapshot' || (chart.points || []).length <= 2;
}

function chooseWorkspaceChart(current: WorkspaceBundle['chart'], patch: WorkspaceBundle['chart']) {
  const patchPoints = patch?.points || [];
  if (!patchPoints.length) return current;
  if (!patch) return current;
  const currentPoints = current?.points || [];
  if (!currentPoints.length) return patch;
  const patchIsSnapshot = isSnapshotChart(patch);
  const currentIsSnapshot = isSnapshotChart(current);
  if (patchIsSnapshot && !currentIsSnapshot) return current;
  if (!patchIsSnapshot && currentIsSnapshot) return patch;
  if (patch.range !== current?.range && !patchIsSnapshot) return patch;
  return patchPoints.length >= currentPoints.length ? patch : current;
}

function lobHasLevels(lob: WorkspaceBundle['lob']) {
  const yesLevels = (lob?.yes?.bids?.length || 0) + (lob?.yes?.asks?.length || 0);
  const noLevels = (lob?.no?.bids?.length || 0) + (lob?.no?.asks?.length || 0);
  return yesLevels + noLevels > 0;
}

function chooseWorkspaceLob(current: WorkspaceBundle['lob'], patch: WorkspaceBundle['lob']) {
  if (!patch) return current;
  if (lobHasLevels(patch)) return patch;
  if (lobHasLevels(current)) return current;
  return patch;
}

export function bundleMatchesMarket(bundle: WorkspaceBundle | null, marketId: number) {
  if (!bundle) return false;
  const ids = [
    bundle.market?.id,
    bundle.identity?.localMarketId,
    bundle.identity?.marketId,
    bundle.price?.marketId,
    bundle.oracle?.localMarketId,
    bundle.oracle?.marketId,
    bundle.chart?.localMarketId,
    bundle.chart?.marketId,
    bundle.content?.marketId,
    bundle.lob?.localMarketId,
    bundle.lob?.marketId,
    bundle.selectedOutcome?.marketId,
    bundle.trades?.[0]?.marketId,
  ];
  const knownIds = ids.filter((id) => id != null && String(id).trim() !== '').map(Number);
  return knownIds.length > 0 && knownIds.every((id) => Number.isFinite(id) && id === marketId);
}

export function mergeWorkspaceBundle(base: WorkspaceBundle | null, patch: WorkspaceBundle): WorkspaceBundle {
  const patchId = patch.market?.id ?? patch.identity?.localMarketId ?? patch.identity?.marketId;
  const current = base && (patchId == null || bundleMatchesMarket(base, Number(patchId)))
    ? base : emptyWorkspaceBundle();
  return {
    market: patch.market || current.market,
    identity: patch.identity || current.identity,
    diagnostics: patch.diagnostics || current.diagnostics,
    health: patch.health || current.health,
    evidence: patch.evidence || current.evidence,
    group: patch.group || current.group,
    selectedOutcome: patch.selectedOutcome || current.selectedOutcome,
    price: patch.price || current.price,
    chart: chooseWorkspaceChart(current.chart, patch.chart),
    trades: patch.trades?.length ? patch.trades : current.trades,
    oracle: patch.oracle || current.oracle,
    content: patch.content?.items?.length ? patch.content : current.content,
    lob: chooseWorkspaceLob(current.lob, patch.lob),
    servingSource: patch.servingSource || current.servingSource,
    servingUpdatedAt: patch.servingUpdatedAt || current.servingUpdatedAt,
    generatedAt: patch.generatedAt || current.generatedAt,
    focusStatus: patch.focusStatus || current.focusStatus,
    cacheLayers: patch.cacheLayers || current.cacheLayers,
  };
}

export function selectedWorkspaceOutcome(bundle: WorkspaceBundle | null): MarketGroupOutcome | null {
  if (!bundle) return null;
  if (bundle.selectedOutcome) return bundle.selectedOutcome;
  const marketId = bundle.market?.id || bundle.identity?.localMarketId;
  return (bundle.group?.outcomes || []).find((outcome) => Number(outcome.marketId) === Number(marketId)) || null;
}
