import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import {
  createQuantBacktestRun,
  fetchQuantBacktestEquity,
  fetchQuantBacktestMetrics,
  fetchQuantBacktestRun,
  fetchQuantBacktestTrades,
  fetchQuantBuildStatus,
  fetchQuantEventPriceHead,
  fetchQuantEventPriceSeries,
  fetchQuantMarketPriceSeries,
  fetchQuantPriceEvents,
  fetchQuantPriceMarkets,
  isAbortLikeError,
  quantEventPriceStreamUrl,
  type QuantPriceQuery,
} from '@/services/api';
import type { QuantBacktestRun, QuantBlockClosePoint, QuantBuildRun, QuantFrontendPricePoint, QuantMarketSeriesOutcome, QuantMarketSeriesPayload, QuantMarketSeriesPoint, QuantPriceMarket } from '@/types';
import { PriceChartPanel } from './components/PriceChartPanel';
import { StrategyTesterPanel } from './components/StrategyTesterPanel';
import { WorkspaceHeader } from './components/WorkspaceHeader';
import type { BacktestEngine, BacktestResult, DataStatus, MarketInfo, PerformanceSortKey, PricePoint, PriceSource, Signal, SortDirection, StrategyParameters, TesterTab, TradeFilter } from './types';
import { backtestApiToResult, blockToPrices, emptyBacktestResult, frontendToPrices, marketSeriesToPrices } from './utils/apiAdapters';
import { deriveEventOutcomeLabel, downloadText, fmtPrice } from './utils/formatters';

function rowSortValue(value: string) {
  const numeric = Number(value.replace(/[^0-9.-]/g, ''));
  return Number.isFinite(numeric) && value.match(/[0-9]/) ? numeric : value.toLowerCase();
}

function tradesToCsv(trades: BacktestResult['trades']) {
  const headers = ['id', 'entryTime', 'exitTime', 'market', 'outcome', 'side', 'entryPrice', 'exitPrice', 'size', 'notional', 'pnl', 'pnlPct', 'holdingTime', 'exitReason'];
  const rows = trades.map((trade) => headers.map((key) => JSON.stringify(String(trade[key as keyof typeof trade] ?? ''))).join(','));
  return [headers.join(','), ...rows].join('\n');
}

function backendPriceSource(priceSource: PriceSource) {
  return priceSource === 'orderfilled' ? 'orderfilled_block_close' : 'frontend';
}

const DEFAULT_QUANT_EVENT_SLUG = '2026-fifa-world-cup-winner-595';
const DEFAULT_QUANT_EVENT_TITLE = '2026 FIFA World Cup Winner';
const EVENT_TILE_OUTCOME_LIMIT = 12;
const EVENT_TILE_MAX_POINTS = 240;
const EVENT_TILE_FULL_MAX_POINTS = 900;
const DEFAULT_STRATEGY_PARAMETERS: StrategyParameters = {
  entryThreshold: 0.58,
  exitThreshold: 0.44,
  stopLoss: 0.075,
  takeProfit: 0.16,
  maxHoldingBars: 96,
  initialCapital: 100000,
  positionSize: 100,
  feeBps: 0,
  slippageBps: 0,
  liquidityCapPct: 100,
};

function defaultMarketSlug() {
  const params = new URLSearchParams(window.location.search);
  return params.get('event_slug') || params.get('event') || params.get('market') || params.get('market_slug') || params.get('slug') || DEFAULT_QUANT_EVENT_SLUG;
}

function defaultEntityKind() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('event_slug') || params.get('event')) return 'event';
  if (params.get('market') || params.get('market_slug') || params.get('slug')) return params.get('kind') === 'event' ? 'event' : 'market';
  return 'event';
}

function defaultPriceSource(): PriceSource {
  const params = new URLSearchParams(window.location.search);
  const source = `${params.get('source') || params.get('price_source') || ''}`.toLowerCase();
  if (source.includes('frontend')) return 'frontend';
  return 'orderfilled';
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function chartRangeFromTimeframe(timeframe: string) {
  return timeframe === '25000' ? 'full' : 'latest';
}

function isSeriesWarming(payload: QuantMarketSeriesPayload | null | undefined) {
  const status = String(payload?.status || payload?.cacheStatus || '').toLowerCase();
  return Boolean(payload?.warming) || ['warming', 'partial'].includes(status);
}

function retryDelayFromSeries(payload: QuantMarketSeriesPayload | null | undefined) {
  const value = Number(payload?.retryAfterMs);
  return Number.isFinite(value) && value > 0 ? Math.max(750, Math.min(8000, value)) : 1800;
}

async function waitForRun(runId: number, onStatus: (run: QuantBacktestRun) => void) {
  for (let attempt = 0; attempt < 90; attempt += 1) {
    const response = await fetchQuantBacktestRun(runId);
    onStatus(response.item);
    if (!['queued', 'running'].includes(response.item.status)) return response.item;
    await sleep(1000);
  }
  const response = await fetchQuantBacktestRun(runId);
  onStatus(response.item);
  return response.item;
}

function signalsFromTrades(result: BacktestResult): Signal[] {
  return result.trades.flatMap((trade) => {
    if (!trade.entryX || !trade.exitX) return [];
    return [
      {
        id: `${trade.id}-entry`,
        timestamp: trade.entryX,
        action: 'OPEN' as const,
        outcome: trade.outcome,
        price: trade.entryPrice,
        size: trade.size,
        notional: trade.notional,
        reason: 'entry threshold reached',
        tradeId: trade.id,
      },
      {
        id: `${trade.id}-exit`,
        timestamp: trade.exitX,
        action: 'CLOSE' as const,
        outcome: trade.outcome,
        price: trade.exitPrice,
        size: trade.size,
        notional: trade.notional,
        reason: trade.exitReason,
        tradeId: trade.id,
      },
    ];
  });
}

function toNumber(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function persistedBoolean(key: string, fallback: boolean) {
  try {
    const value = window.localStorage.getItem(key);
    if (value === 'true') return true;
    if (value === 'false') return false;
  } catch {
    // Keep the workspace usable when browser storage is blocked.
  }
  return fallback;
}

function persistedStringArray(key: string) {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) || '[]');
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === 'string') : [];
  } catch {
    return [];
  }
}

function clampNumber(value: unknown, fallback: number, min: number, max: number) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.max(min, Math.min(max, numeric));
}

function normalizeStrategyParameters(value: Partial<StrategyParameters> | null | undefined): StrategyParameters {
  return {
    entryThreshold: clampNumber(value?.entryThreshold, DEFAULT_STRATEGY_PARAMETERS.entryThreshold, 0.001, 0.999),
    exitThreshold: clampNumber(value?.exitThreshold, DEFAULT_STRATEGY_PARAMETERS.exitThreshold, 0.001, 0.999),
    stopLoss: clampNumber(value?.stopLoss, DEFAULT_STRATEGY_PARAMETERS.stopLoss, 0.001, 0.95),
    takeProfit: clampNumber(value?.takeProfit, DEFAULT_STRATEGY_PARAMETERS.takeProfit, 0.001, 5),
    maxHoldingBars: Math.round(clampNumber(value?.maxHoldingBars, DEFAULT_STRATEGY_PARAMETERS.maxHoldingBars, 1, 10000)),
    initialCapital: clampNumber(value?.initialCapital, DEFAULT_STRATEGY_PARAMETERS.initialCapital, 1, 1000000000),
    positionSize: clampNumber(value?.positionSize, DEFAULT_STRATEGY_PARAMETERS.positionSize, 1, 1000000000),
    feeBps: clampNumber(value?.feeBps, DEFAULT_STRATEGY_PARAMETERS.feeBps, 0, 1000),
    slippageBps: clampNumber(value?.slippageBps, DEFAULT_STRATEGY_PARAMETERS.slippageBps, 0, 1000),
    liquidityCapPct: clampNumber(value?.liquidityCapPct, DEFAULT_STRATEGY_PARAMETERS.liquidityCapPct, 0, 100),
  };
}

function persistedStrategyParameters() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem('polydata.quant.strategyParameters') || '{}');
    return normalizeStrategyParameters(parsed);
  } catch {
    return DEFAULT_STRATEGY_PARAMETERS;
  }
}

function chartOutcomeKey(outcome: QuantMarketSeriesOutcome | null | undefined, label: string, side: BacktestAction = 'YES') {
  const base = outcome?.outcomeKey || outcome?.marketSlug || outcome?.marketId || outcome?.outcomeLabel || label || outcome?.tokenId || 'outcome';
  return `${base}:${side}`;
}

function persistedInspectorTab() {
  try {
    const value = window.localStorage.getItem('polydata.quant.inspectorTab') as InspectorTab | null;
    if (value && ['watchlist', 'market', 'outcomes', 'book', 'trades', 'dataQuality'].includes(value)) return value;
  } catch {
    // Keep the default tab.
  }
  return 'market';
}

function blockRangeLabel(prices: Array<{ timestamp: number }>) {
  const first = prices[0]?.timestamp;
  const last = prices[prices.length - 1]?.timestamp;
  if (typeof first !== 'number' || typeof last !== 'number' || !Number.isFinite(first) || !Number.isFinite(last)) return '--';
  return `${Math.floor(first).toLocaleString('en-US')} -> ${Math.floor(last).toLocaleString('en-US')}`;
}

function formatBuildTime(value: string | null | undefined) {
  if (!value) return '--';
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return value;
  return new Date(time).toLocaleString();
}

function buildRunStatusClass(run: QuantBuildRun) {
  const status = String(run.status || '').toLowerCase();
  if (status.includes('success') || status.includes('complete') || status === 'ready') return 'ready';
  if (status.includes('run') || status.includes('queue') || status.includes('warm')) return 'running';
  if (status.includes('fail') || status.includes('error') || toNumber(run.errorCount) > 0) return 'error';
  return 'review';
}

function dataQualitySummary(prices: PricePoint[], source: string, outcomes: QuantMarketSeriesOutcome[], dataStatus: DataStatus) {
  const sorted = prices
    .filter((point) => Number.isFinite(point.timestamp) && Number.isFinite(point.close))
    .slice()
    .sort((left, right) => left.timestamp - right.timestamp);
  const deltas = sorted.slice(1).map((point, index) => {
    const previous = sorted[index];
    return previous ? point.timestamp - previous.timestamp : 0;
  }).filter((delta) => delta > 0);
  const medianDelta = quantile(deltas, 0.5);
  const gapCount = medianDelta > 0 ? deltas.filter((delta) => delta > medianDelta * 4).length : 0;
  const spikeCount = sorted.slice(1).filter((point, index) => {
    const previous = sorted[index];
    return previous ? Math.abs(point.close - previous.close) > 0.18 : false;
  }).length;
  const directYesRows = sorted.filter((point) => point.yesPriceKind === 'direct' || !point.yesPriceKind).length;
  const impliedNoRows = sorted.filter((point) => point.noPriceKind === 'implied').length;
  const directNoRows = sorted.filter((point) => point.noPriceKind === 'direct').length;
  const outcomeRows = outcomes.reduce((sum, outcome) => sum + toNumber(outcome.rows) + toNumber(outcome.complementRows), 0);
  const firstBlock = sorted[0]?.timestamp || 0;
  const latestBlock = sorted[sorted.length - 1]?.timestamp || 0;
  const warnings = [
    !sorted.length ? 'No price rows loaded for the selected source/window.' : '',
    gapCount ? `${gapCount} block gaps larger than the median spacing.` : '',
    spikeCount ? `${spikeCount} large adjacent price jumps detected.` : '',
    impliedNoRows > directNoRows ? 'NO side is mostly implied from YES prices.' : '',
    dataStatus === 'partial' ? 'Showing cached or partial coverage while refresh continues.' : '',
  ].filter(Boolean);
  return {
    rows: sorted.length,
    outcomeRows,
    firstBlock,
    latestBlock,
    medianDelta,
    gapCount,
    spikeCount,
    directYesRows,
    directNoRows,
    impliedNoRows,
    source,
    health: !sorted.length ? 'empty' : warnings.length ? 'review' : 'ready',
    warnings,
  };
}

function pointBlock(point: QuantMarketSeriesPoint | null | undefined) {
  return toNumber(point?.x ?? point?.blockNumber ?? point?.timestamp);
}

function outcomePointStats(points: QuantMarketSeriesPoint[] | undefined) {
  const sorted = (points || [])
    .map((point) => ({
      block: pointBlock(point),
      price: toNumber(point.price ?? point.yesProbabilityClose),
      implied: Boolean(point.isImplied),
    }))
    .filter((point) => Number.isFinite(point.block) && point.block > 0)
    .sort((left, right) => left.block - right.block);
  const deltas = sorted.slice(1).map((point, index) => {
    const previous = sorted[index];
    return previous ? point.block - previous.block : 0;
  }).filter((delta) => delta > 0);
  const medianDelta = quantile(deltas, 0.5);
  const gaps = medianDelta > 0 ? deltas.filter((delta) => delta > medianDelta * 4).length : 0;
  const spikes = sorted.slice(1).filter((point, index) => {
    const previous = sorted[index];
    return previous ? Math.abs(point.price - previous.price) > 0.18 : false;
  }).length;
  return {
    rows: sorted.length,
    firstBlock: sorted[0]?.block || 0,
    lastBlock: sorted[sorted.length - 1]?.block || 0,
    medianDelta,
    gaps,
    spikes,
    impliedRows: sorted.filter((point) => point.implied).length,
  };
}

function quantile(values: number[], ratio: number) {
  if (!values.length) return 0;
  const sorted = values.slice().sort((left, right) => left - right);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.floor((sorted.length - 1) * ratio)));
  return sorted[index] ?? 0;
}

function strategyDefaults(prices: Array<{ close: number }>) {
  const closes = prices.map((price) => price.close).filter((value) => Number.isFinite(value) && value > 0);
  const entry = Math.max(0.01, Math.min(0.95, quantile(closes, 0.68) || 0.58));
  const rawExit = Math.max(0.001, Math.min(0.94, quantile(closes, 0.42) || entry * 0.82));
  const exit = rawExit >= entry ? Math.max(0.001, entry * 0.82) : rawExit;
  return {
    entryThreshold: Number(entry.toFixed(4)),
    exitThreshold: Number(exit.toFixed(4)),
  };
}

type BacktestAction = 'YES' | 'NO';
type OutcomeSortKey = 'order' | 'probability' | 'rows' | 'volume';
type InspectorTab = 'watchlist' | 'market' | 'outcomes' | 'book' | 'trades' | 'dataQuality';
type RefreshQuantRowsOptions = {
  silent?: boolean;
};
type EventPriceStreamOutcome = {
  tokenId?: string | null;
  outcomeLabel?: string | null;
  buyYesPrice?: string | number | null;
  buyNoPrice?: string | number | null;
  latestPrice?: string | number | null;
  lastX?: string | number | null;
  rows?: string | number | null;
};
type EventPriceStreamPayload = {
  eventSlug?: string;
  priceSource?: string;
  updatedAt?: string;
  outcomes?: EventPriceStreamOutcome[];
};

function outcomePricePoints(outcome: QuantMarketSeriesOutcome | null | undefined, action: BacktestAction = 'YES') {
  const points = action === 'NO' ? outcome?.complementPoints || [] : outcome?.points || [];
  return points.map((point) => ({
    timestamp: Number(point.x ?? point.blockNumber ?? point.timestamp),
    close: toNumber(point.price),
    volume: toNumber(point.volume),
    source: action === 'NO' ? 'selected_outcome_no' : 'selected_outcome_yes',
    tokenId: action === 'NO' ? outcome?.buyNoTokenId || undefined : outcome?.buyYesTokenId || outcome?.tokenId,
    tokenSide: action === 'NO' ? outcome?.buyNoTokenSide || undefined : outcome?.buyYesTokenSide || outcome?.tokenSide,
    outcomeLabel: action === 'NO' ? outcome?.buyNoLabel || `${outcome?.outcomeLabel || 'Outcome'} No` : outcome?.buyYesLabel || outcome?.outcomeLabel,
  })).filter((point) => point.timestamp && Number.isFinite(point.close));
}

function defaultOutcomeTokenId(outcomes: QuantMarketSeriesOutcome[]) {
  const sorted = outcomes.slice().sort((left, right) => toNumber(right.latestPrice) - toNumber(left.latestPrice));
  return sorted[0]?.tokenId || outcomes[0]?.tokenId || '';
}

function appendStreamPoint(points: QuantMarketSeriesPoint[] | undefined, x: number, price: string | number | null | undefined, tokenId: string | null | undefined, tokenSide: string | null | undefined) {
  if (!Number.isFinite(x) || price === null || price === undefined) return points || [];
  const current = points || [];
  const last = current[current.length - 1];
  const lastX = Number(last?.x ?? last?.blockNumber ?? last?.timestamp);
  if (Number.isFinite(lastX) && x < lastX) return current;
  if (Number.isFinite(lastX) && x === lastX) {
    return current.map((point, index) => (index === current.length - 1 ? {
      ...point,
      price,
      volume: toNumber(point.volume),
      tokenId: tokenId || point.tokenId,
      tokenSide: tokenSide || point.tokenSide,
    } : point));
  }
  return [
    ...current,
    {
      x,
      blockNumber: x,
      tokenId,
      tokenSide,
      price,
      volume: 0,
      isImplied: false,
    },
  ];
}

function mergeEventPriceStream(current: QuantMarketSeriesPayload | null, update: EventPriceStreamPayload): QuantMarketSeriesPayload | null {
  if (!current?.outcomes?.length || !update.outcomes?.length) return current;
  const latestByToken = new Map(update.outcomes.map((outcome) => [String(outcome.tokenId || ''), outcome]));
  return {
    ...current,
    outcomes: current.outcomes.map((outcome) => {
      const latest = latestByToken.get(String(outcome.tokenId || ''));
      if (!latest) return outcome;
      const lastX = Number(latest.lastX);
      const nextPoints = appendStreamPoint(outcome.points, lastX, latest.latestPrice ?? latest.buyYesPrice, outcome.buyYesTokenId || outcome.tokenId, outcome.buyYesTokenSide || outcome.tokenSide);
      const nextComplementPoints = appendStreamPoint(outcome.complementPoints, lastX, latest.buyNoPrice, outcome.buyNoTokenId, outcome.buyNoTokenSide || 'NO');
      return {
        ...outcome,
        buyYesPrice: latest.buyYesPrice ?? outcome.buyYesPrice,
        buyNoPrice: latest.buyNoPrice ?? outcome.buyNoPrice,
        latestPrice: latest.latestPrice ?? latest.buyYesPrice ?? outcome.latestPrice,
        lastX: latest.lastX ?? outcome.lastX,
        rows: toNumber(latest.rows ?? outcome.rows),
        points: nextPoints,
        complementPoints: nextComplementPoints,
        complementRows: nextComplementPoints.length || outcome.complementRows,
      };
    }),
  };
}

function isClosedStatus(status: unknown) {
  const text = String(status || '').toLowerCase();
  return Boolean(text) && ['closed', 'resolved', 'settled', 'finalized', 'ended', 'archived'].some((word) => text.includes(word));
}

function isSelectionLive(market: QuantPriceMarket | null | undefined, series: QuantMarketSeriesPayload | null | undefined) {
  const status = (market as (QuantPriceMarket & { status?: string | null }) | null | undefined)?.status || series?.event?.status;
  if (isClosedStatus(status)) return false;
  const endDate = market?.endDate || series?.market?.endDate;
  if (!endDate) return true;
  const endTs = Date.parse(String(endDate));
  if (!Number.isFinite(endTs)) return true;
  return endTs > Date.now() - 12 * 60 * 60 * 1000;
}

function defaultEventMeta(): QuantPriceMarket {
  return {
    itemKind: 'event',
    eventSlug: DEFAULT_QUANT_EVENT_SLUG,
    eventTitle: DEFAULT_QUANT_EVENT_TITLE,
    groupingConfidence: 'official',
    source: 'default',
    outcomeCount: 60,
    totalMembers: 60,
    readyMembers: 0,
    marketSlug: DEFAULT_QUANT_EVENT_SLUG,
    marketTitle: DEFAULT_QUANT_EVENT_TITLE,
    tokenSide: 'EVENT',
    blockRows: 0,
    frontendRows: 0,
  };
}

function marketInfoFromSelection(slug: string, market?: QuantPriceMarket): MarketInfo {
  const isEvent = market?.itemKind === 'event';
  return {
    id: String(market?.marketId || slug || 'quant-market'),
    conditionId: market?.conditionId || '-',
    title: market?.marketTitle || slug || 'Select a Polymarket market',
    category: isEvent ? 'Polymarket Event' : 'Polymarket',
    slug: market?.marketSlug || slug,
    startTime: market?.firstTs ? new Date(toNumber(market.firstTs) * 1000).toISOString() : '-',
    endTime: market?.endDate || '-',
    resolutionTime: market?.endDate || '-',
    resolvedOutcome: 'PENDING',
    yesTokenId: 'YES',
    noTokenId: 'NO',
    liquidity: '-',
    volume: isEvent
      ? `${toNumber(market?.readyMembers).toLocaleString('en-US')} / ${toNumber(market?.totalMembers || market?.outcomeCount).toLocaleString('en-US')} members ready`
      : `${toNumber(market?.blockRows).toLocaleString('en-US')} block rows`,
  };
}

export function QuantWorkspace() {
  const [frontendRows, setFrontendRows] = useState<QuantFrontendPricePoint[]>([]);
  const [blockRows, setBlockRows] = useState<QuantBlockClosePoint[]>([]);
  const [marketSeries, setMarketSeries] = useState<QuantMarketSeriesPayload | null>(null);
  const [selectedOutcomeTokenId, setSelectedOutcomeTokenId] = useState('');
  const [selectedBacktestAction, setSelectedBacktestAction] = useState<BacktestAction>('YES');
  const [runs, setRuns] = useState<QuantBuildRun[]>([]);
  const [quantMarkets, setQuantMarkets] = useState<QuantPriceMarket[]>([]);
  const [marketSearchStatus, setMarketSearchStatus] = useState<DataStatus>('idle');
  const [selectedMarketMeta, setSelectedMarketMeta] = useState<QuantPriceMarket | null>(() => (
    defaultMarketSlug() === DEFAULT_QUANT_EVENT_SLUG ? defaultEventMeta() : null
  ));
  const [dataStatus, setDataStatus] = useState<DataStatus>('idle');
  const [loadingMessage, setLoadingMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [timeframe, setTimeframe] = useState('2500');
  const [viewportMode, setViewportMode] = useState<'preset' | 'custom'>('preset');
  const [viewportResetSeq, setViewportResetSeq] = useState(0);
  const [priceSource, setPriceSource] = useState<PriceSource>(defaultPriceSource);
  const [backtestEngine, setBacktestEngine] = useState<BacktestEngine>('backtrader');
  const [testerTab, setTesterTab] = useState<TesterTab>('overview');
  const [deepBacktest, setDeepBacktest] = useState(false);
  const [selectedTradeId, setSelectedTradeId] = useState<string | null>(null);
  const [marketSlug, setMarketSlug] = useState(defaultMarketSlug);
  const [selectedEntityKindHint, setSelectedEntityKindHint] = useState<'market' | 'event'>(defaultEntityKind);
  const [marketSearchQuery, setMarketSearchQuery] = useState('');
  const [marketReloadKey, setMarketReloadKey] = useState(0);
  const [backtestStatus, setBacktestStatus] = useState('idle');
  const [performanceSearch, setPerformanceSearch] = useState('');
  const [performanceSortKey, setPerformanceSortKey] = useState<PerformanceSortKey>('metric');
  const [performanceSortDirection, setPerformanceSortDirection] = useState<SortDirection>('asc');
  const [tradeFilters, setTradeFilters] = useState<Set<TradeFilter>>(new Set());
  const [workspaceNotice, setWorkspaceNotice] = useState('');
  const [outcomeSortKey, setOutcomeSortKey] = useState<OutcomeSortKey>('probability');
  const [lastPriceRefreshAt, setLastPriceRefreshAt] = useState('');
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>(persistedInspectorTab);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(() => persistedBoolean('polydata.quant.inspectorCollapsed', false));
  const [strategyDrawerCollapsed, setStrategyDrawerCollapsed] = useState(() => persistedBoolean('polydata.quant.strategyDrawerCollapsed', false));
  const [watchlistKeys, setWatchlistKeys] = useState<string[]>(() => persistedStringArray('polydata.quant.watchlistKeys'));
  const [chartPinnedOutcomeKeys, setChartPinnedOutcomeKeys] = useState<string[]>(() => persistedStringArray('polydata.quant.chart.pinnedOutcomes'));
  const [chartHiddenOutcomeKeys, setChartHiddenOutcomeKeys] = useState<string[]>(() => persistedStringArray('polydata.quant.chart.hiddenOutcomes'));
  const [chartSoloOutcomeKey, setChartSoloOutcomeKey] = useState('');
  const [strategyParameters, setStrategyParameters] = useState<StrategyParameters>(persistedStrategyParameters);
  const marketSearchSeq = useRef(0);
  const priceLoadSeq = useRef(0);
  const marketSlugRef = useRef(marketSlug);
  const autoSelectedDefaultRef = useRef(Boolean(defaultMarketSlug()));
  const marketSearchCacheRef = useRef(new Map<string, QuantPriceMarket[]>());
  const priceSeriesCacheRef = useRef(new Map<string, QuantMarketSeriesPayload>());
  const pricePrefetchingRef = useRef(new Set<string>());
  const liveRefreshInFlightRef = useRef(false);
  const priceRetryTimerRef = useRef<number | null>(null);

  const activePrices = useMemo(() => {
    const semanticPrices = marketSeriesToPrices(marketSeries);
    if (semanticPrices.length) return semanticPrices;
    if (priceSource === 'orderfilled') return blockToPrices(blockRows);
    if (priceSource === 'frontend') return frontendToPrices(frontendRows);
    return [];
  }, [blockRows, frontendRows, marketSeries, priceSource]);
  const [backtestResult, setBacktestResult] = useState<BacktestResult>(() => emptyBacktestResult());
  const strategySignals = useMemo(() => signalsFromTrades(backtestResult), [backtestResult]);
  const latestPrice = activePrices[activePrices.length - 1]?.close || 0;
  const displayedPriceRows = activePrices.length;
  const selectedOutcome = useMemo(() => {
    const outcomes = marketSeries?.outcomes || [];
    if (!outcomes.length) return null;
    return outcomes.find((outcome) => outcome.tokenId === selectedOutcomeTokenId) || outcomes[0] || null;
  }, [marketSeries, selectedOutcomeTokenId]);
  const selectedMarket = useMemo(
    () => (
      (selectedMarketMeta?.marketSlug === marketSlug ? selectedMarketMeta : undefined)
      || quantMarkets.find((market) => market.marketSlug === marketSlug && market.itemKind === 'event')
      || quantMarkets.find((market) => market.marketSlug === marketSlug && market.tokenSide === 'YES')
      || quantMarkets.find((market) => market.marketSlug === marketSlug)
    ),
    [marketSlug, quantMarkets, selectedMarketMeta],
  );
  const selectedEntityKind = selectedMarket?.itemKind === 'event' || selectedEntityKindHint === 'event' ? 'event' : 'market';
  const marketInfo = useMemo(() => marketInfoFromSelection(marketSlug, selectedMarket), [marketSlug, selectedMarket]);
  const livePriceRefreshEnabled = useMemo(
    () => Boolean(marketSlug.trim()) && isSelectionLive(selectedMarket, marketSeries),
    [marketSeries, marketSlug, selectedMarket],
  );
  const marketCoverageRows = toNumber(selectedMarket?.blockRows || selectedMarket?.frontendRows || marketSeries?.outcomes?.reduce((sum, outcome) => sum + toNumber(outcome.rows), 0));
  const chartLimit = useMemo(() => {
    const parsed = Number(timeframe);
    return Number.isFinite(parsed) ? Math.max(100, Math.min(25000, parsed)) : 2500;
  }, [timeframe]);
  const chartRange = chartRangeFromTimeframe(timeframe);
  const chartRequestLimit = selectedEntityKind === 'event' && chartRange === 'full' ? 250000 : chartLimit;
  const semanticChartQuery: QuantPriceQuery & { priceSource: string; scope: string; maxOutcomes: number; topN?: number; maxPoints?: number } = {
    marketSlug,
    priceSource: backendPriceSource(priceSource),
    scope: 'auto',
    limit: chartRequestLimit,
    maxOutcomes: selectedEntityKind === 'event' ? EVENT_TILE_OUTCOME_LIMIT : 24,
    topN: selectedEntityKind === 'event' ? EVENT_TILE_OUTCOME_LIMIT : undefined,
    maxPoints: selectedEntityKind === 'event' ? (chartRange === 'full' ? EVENT_TILE_FULL_MAX_POINTS : EVENT_TILE_MAX_POINTS) : undefined,
    range: selectedEntityKind === 'event' ? chartRange : undefined,
    resolution: selectedEntityKind === 'event' ? 'auto' : undefined,
    live: false,
  };
  const priceRequestKey = [
    selectedEntityKind,
    marketSlug.trim(),
    backendPriceSource(priceSource),
    timeframe,
  ].join('|');

  const seriesKeyForSlug = (slug: string, itemKind = selectedEntityKind) => [
    itemKind,
    slug.trim(),
    backendPriceSource(priceSource),
    timeframe,
  ].join('|');

  const refreshQuantRows = async (requestSeq = priceLoadSeq.current, options: RefreshQuantRowsOptions = {}) => {
    const silent = Boolean(options.silent);
    const hasMarketSlug = Boolean(marketSlug.trim());
    const cacheKey = priceRequestKey;
    if (hasMarketSlug) {
      const cached = priceSeriesCacheRef.current.get(cacheKey);
      if (cached) {
        setMarketSeries(cached);
        if (!silent) {
          setDataStatus('partial');
          setLoadingMessage('Refreshing cached price series...');
        }
      } else {
        if (!silent) {
          setDataStatus(selectedMarket ? 'price_loading' : 'metadata_loading');
          setLoadingMessage(selectedMarket ? 'Loading price series...' : 'Loading market metadata...');
        }
      }
      if (import.meta.env.DEV) {
        console.debug('[quant] price load start', { cacheKey, cached: Boolean(cached), marketSlug, priceSource, timeframe, silent });
      }
    }
    const priceQuery = {
      ...semanticChartQuery,
      live: livePriceRefreshEnabled && silent && selectedEntityKind !== 'event',
    };
    const [seriesResult, statusResult] = await Promise.allSettled([
      hasMarketSlug
        ? (selectedEntityKind === 'event'
          ? fetchQuantEventPriceSeries({ ...priceQuery, eventSlug: marketSlug })
          : fetchQuantMarketPriceSeries(priceQuery))
        : Promise.resolve(null),
      fetchQuantBuildStatus('', 12),
    ]);
    if (requestSeq !== priceLoadSeq.current) {
      if (import.meta.env.DEV) console.debug('[quant] stale price response ignored', { cacheKey });
      return {
        frontendRows,
        blockRows,
        marketSeries,
      };
    }
    const fulfilledSeries = seriesResult.status === 'fulfilled' ? seriesResult.value : null;
    const warmingSeries = isSeriesWarming(fulfilledSeries);
    const fulfilledPointCount = marketSeriesToPrices(fulfilledSeries).length;
    const currentPointCount = marketSeriesToPrices(marketSeries).length;
    const keepCurrentWhileWarming = Boolean(warmingSeries && marketSeries && currentPointCount > fulfilledPointCount);
    const nextMarketSeries = fulfilledSeries && !keepCurrentWhileWarming ? fulfilledSeries : marketSeries;
    const nextFrontendRows = priceSource === 'frontend' ? frontendRows : [];
    const nextBlockRows = priceSource === 'orderfilled' ? blockRows : [];
    if (seriesResult.status === 'fulfilled') {
      if (fulfilledSeries && (!warmingSeries || !keepCurrentWhileWarming)) priceSeriesCacheRef.current.set(cacheKey, fulfilledSeries);
      if (nextMarketSeries && nextMarketSeries !== marketSeries) priceSeriesCacheRef.current.set(cacheKey, nextMarketSeries);
      setMarketSeries(nextMarketSeries);
      setLastPriceRefreshAt(new Date().toLocaleTimeString());
      if (warmingSeries && !silent && selectedEntityKind === 'event') {
        if (priceRetryTimerRef.current) window.clearTimeout(priceRetryTimerRef.current);
        const retryMs = retryDelayFromSeries(fulfilledSeries);
        priceRetryTimerRef.current = window.setTimeout(() => {
          if (requestSeq !== priceLoadSeq.current) return;
          setMarketReloadKey((current) => current + 1);
        }, retryMs);
      }
    }
    if (priceSource !== 'frontend') setFrontendRows([]);
    if (priceSource !== 'orderfilled') setBlockRows([]);
    if (statusResult.status === 'fulfilled') setRuns(statusResult.value.items || []);
    const activeRowCount = marketSeriesToPrices(nextMarketSeries).length || (priceSource === 'orderfilled' ? nextBlockRows.length : nextFrontendRows.length);
    if (hasMarketSlug) {
      if (!silent) {
        setDataStatus(warmingSeries ? 'warming' : activeRowCount ? 'ready' : 'empty');
        setLoadingMessage(warmingSeries
          ? (keepCurrentWhileWarming
            ? 'Historical price tile is warming; keeping the previous chart until the full series is ready.'
            : (fulfilledSeries?.message || 'Historical price tile is warming; showing latest outcome snapshot.'))
          : activeRowCount ? '' : 'No price rows found for this source/window');
      } else if (activeRowCount) {
        setDataStatus('ready');
      }
      if (import.meta.env.DEV) console.debug('[quant] price load complete', { cacheKey, activeRowCount });
    }
    if (hasMarketSlug && seriesResult.status === 'rejected') {
      const hasCached = priceSeriesCacheRef.current.has(cacheKey);
      if (!silent) {
        setDataStatus(hasCached ? 'partial' : 'error');
        setLoadingMessage(hasCached ? 'Showing cached data; refresh failed.' : 'Price request failed.');
      }
      throw seriesResult.reason instanceof Error ? seriesResult.reason : new Error('Quant API unavailable');
    }
    return {
      frontendRows: nextFrontendRows,
      blockRows: nextBlockRows,
      marketSeries: nextMarketSeries,
    };
  };

  const runBacktest = async () => {
    setLoading(true);
    setError('');
    setBacktestStatus('submitting');
    try {
      if (!marketSlug.trim()) {
        throw new Error('market_slug is required for real backtest');
      }
      const loadedSeriesPrices = outcomePricePoints(selectedOutcome, selectedBacktestAction);
      const loadedBlockRows = blockRows.filter((row) => String(row.tokenSide || '').toUpperCase() === 'YES');
      const hasLoadedRows = loadedSeriesPrices.length > 0 || (priceSource === 'orderfilled' ? loadedBlockRows.length > 0 : frontendRows.length > 0);
      const nextRows = hasLoadedRows
        ? { frontendRows, blockRows, marketSeries }
        : await refreshQuantRows();
      const nextSelectedOutcome = (
        nextRows.marketSeries?.outcomes?.find((outcome) => outcome.tokenId === selectedOutcomeTokenId)
        || nextRows.marketSeries?.outcomes?.[0]
        || selectedOutcome
      );
      const seriesPrices = outcomePricePoints(nextSelectedOutcome, selectedBacktestAction);
      const backtestBlockRows = nextRows.blockRows.filter((row) => String(row.tokenSide || '').toUpperCase() === 'YES');
      const sourceRows = seriesPrices.length ? seriesPrices : (priceSource === 'orderfilled' ? blockToPrices(backtestBlockRows) : frontendToPrices(nextRows.frontendRows));
      if (!sourceRows.length) {
        throw new Error(`No ${backendPriceSource(priceSource)} rows for ${marketSlug.trim()}`);
      }
      const firstX = sourceRows[0]?.timestamp;
      const lastX = sourceRows[sourceRows.length - 1]?.timestamp;
      const firstBlock = priceSource === 'orderfilled' ? firstX : backtestBlockRows[0]?.blockNumber;
      const lastBlock = priceSource === 'orderfilled' ? lastX : backtestBlockRows[backtestBlockRows.length - 1]?.blockNumber;
      const firstTs = priceSource === 'frontend' ? firstX : nextRows.frontendRows[0]?.timestamp;
      const lastTs = priceSource === 'frontend' ? lastX : nextRows.frontendRows[nextRows.frontendRows.length - 1]?.timestamp;
      const selectedTokenId = selectedBacktestAction === 'NO'
        ? nextSelectedOutcome?.buyNoTokenId
        : nextSelectedOutcome?.buyYesTokenId || nextSelectedOutcome?.tokenId;
      const selectedTokenSide = selectedBacktestAction === 'NO'
        ? nextSelectedOutcome?.buyNoTokenSide
        : nextSelectedOutcome?.buyYesTokenSide || nextSelectedOutcome?.tokenSide;
      const selectedOutcomeLabel = selectedBacktestAction === 'NO'
        ? nextSelectedOutcome?.buyNoLabel || `${nextSelectedOutcome?.outcomeLabel || 'Outcome'} No`
        : nextSelectedOutcome?.buyYesLabel || nextSelectedOutcome?.outcomeLabel;
      const created = await createQuantBacktestRun({
        marketSlug: (nextSelectedOutcome?.marketSlug || marketSlug).trim(),
        tokenSide: selectedTokenSide || 'YES',
        tokenId: selectedTokenId || undefined,
        outcomeLabel: selectedOutcomeLabel,
        priceSource: backendPriceSource(priceSource),
        backtestEngine,
        ...(priceSource === 'orderfilled' && firstBlock && lastBlock ? { fromBlock: String(firstBlock), toBlock: String(lastBlock) } : {}),
        ...(priceSource === 'frontend' && firstTs && lastTs ? { from: String(firstTs), to: String(lastTs) } : {}),
        entryThreshold: strategyParameters.entryThreshold,
        exitThreshold: strategyParameters.exitThreshold,
        stopLoss: strategyParameters.stopLoss,
        takeProfit: strategyParameters.takeProfit,
        maxHoldingBars: strategyParameters.maxHoldingBars,
        initialCapital: strategyParameters.initialCapital,
        positionSize: strategyParameters.positionSize,
        feeBps: strategyParameters.feeBps,
        slippageBps: strategyParameters.slippageBps,
        liquidityCapPct: strategyParameters.liquidityCapPct,
      });
      setBacktestStatus(created.item.status);
      const completedRun = ['queued', 'running'].includes(created.item.status)
        ? await waitForRun(created.runId, (run) => setBacktestStatus(run.status))
        : created.item;
      if (completedRun.status === 'failed') {
        throw new Error(completedRun.error || 'Backtest failed');
      }
      if (['queued', 'running'].includes(completedRun.status)) {
        throw new Error(`Backtest ${completedRun.status}; try refresh in a moment`);
      }
      const [metricsResult, equityResult, tradesResult] = await Promise.all([
        fetchQuantBacktestMetrics(completedRun.runId),
        fetchQuantBacktestEquity(completedRun.runId),
        fetchQuantBacktestTrades(completedRun.runId),
      ]);
      const result = backtestApiToResult(completedRun, metricsResult.items || [], equityResult.items || [], tradesResult.items || [], priceSource);
      setBacktestResult(result);
      setSelectedTradeId(result.trades[0]?.id ?? null);
      setBacktestStatus(completedRun.status);
      if (!nextRows.frontendRows.length && !nextRows.blockRows.length) setError('');
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : 'Quant API unavailable');
      setBacktestStatus('failed');
    } finally {
      setLoading(false);
    }
  };

  const selectMarketSlug = (slug: string) => {
    const nextSlug = slug.trim();
    if (priceRetryTimerRef.current) {
      window.clearTimeout(priceRetryTimerRef.current);
      priceRetryTimerRef.current = null;
    }
    const nextMarket = quantMarkets.find((market) => market.marketSlug === nextSlug && market.itemKind === 'event')
      || quantMarkets.find((market) => market.marketSlug === nextSlug && market.tokenSide === 'YES')
      || quantMarkets.find((market) => market.marketSlug === nextSlug)
      || null;
    setMarketSlug(nextSlug);
    setMarketSearchQuery('');
    setMarketReloadKey((current) => current + 1);
    setViewportMode('preset');
    setViewportResetSeq((current) => current + 1);
    setSelectedMarketMeta(nextMarket);
    setSelectedEntityKindHint(nextMarket?.itemKind === 'event' ? 'event' : 'market');
    const cached = nextSlug ? priceSeriesCacheRef.current.get(seriesKeyForSlug(nextSlug, nextMarket?.itemKind === 'event' ? 'event' : 'market')) : null;
    setFrontendRows([]);
    setBlockRows([]);
    setMarketSeries(cached || null);
    setSelectedOutcomeTokenId('');
    setSelectedBacktestAction('YES');
    setBacktestResult(emptyBacktestResult());
    setSelectedTradeId(null);
    setError('');
    autoSelectedDefaultRef.current = true;
    if (nextSlug) {
      setDataStatus(cached ? 'partial' : 'metadata_loading');
      setLoadingMessage(cached ? 'Rendering cached data...' : 'Loading market metadata...');
    }
  };

  const changeTimeframePreset = (value: string) => {
    setTimeframe(value);
    setViewportMode('preset');
    setViewportResetSeq((current) => current + 1);
  };

  const changePriceSource = (value: PriceSource) => {
    setPriceSource(value);
    setViewportMode('preset');
    setViewportResetSeq((current) => current + 1);
  };

  const updateViewportMode = (mode: 'preset' | 'custom') => {
    setViewportMode((current) => (current === mode ? current : mode));
  };

  useEffect(() => {
    marketSlugRef.current = marketSlug;
  }, [marketSlug]);

  const prefetchMarketSlug = (slug: string) => {
    const nextSlug = slug.trim();
    const nextMarket = quantMarkets.find((market) => market.marketSlug === nextSlug && market.itemKind === 'event')
      || quantMarkets.find((market) => market.marketSlug === nextSlug);
    const nextKind = nextMarket?.itemKind === 'event' ? 'event' : 'market';
    const cacheKey = seriesKeyForSlug(nextSlug, nextKind);
    if (!nextSlug || priceSeriesCacheRef.current.has(cacheKey) || pricePrefetchingRef.current.has(cacheKey)) return;
    pricePrefetchingRef.current.add(cacheKey);
    const request = {
      marketSlug: nextSlug,
      priceSource: backendPriceSource(priceSource),
      scope: 'auto',
      limit: chartLimit,
      maxOutcomes: nextKind === 'event' ? EVENT_TILE_OUTCOME_LIMIT : 24,
      topN: nextKind === 'event' ? EVENT_TILE_OUTCOME_LIMIT : undefined,
      maxPoints: nextKind === 'event' ? EVENT_TILE_MAX_POINTS : undefined,
    };
    void (nextKind === 'event' ? fetchQuantEventPriceHead({ ...request, eventSlug: nextSlug }) : fetchQuantMarketPriceSeries(request))
      .then((payload) => {
        priceSeriesCacheRef.current.set(cacheKey, payload);
        if (import.meta.env.DEV) console.debug('[quant] prefetched price series', { cacheKey });
      })
      .catch((prefetchError) => {
        if (import.meta.env.DEV && !isAbortLikeError(prefetchError)) console.debug('[quant] prefetch failed', { cacheKey, prefetchError });
      })
      .finally(() => {
        pricePrefetchingRef.current.delete(cacheKey);
      });
  };

  useEffect(() => {
    const text = marketSearchQuery.trim();
    const cacheKey = text.toLowerCase();
    const cached = marketSearchCacheRef.current.get(cacheKey);
    const seq = marketSearchSeq.current + 1;
    marketSearchSeq.current = seq;
    if (cached) {
      setQuantMarkets(cached);
      setMarketSearchStatus(cached.length ? 'ready' : 'empty');
    } else {
      setMarketSearchStatus('loading');
    }
    const timer = window.setTimeout(() => {
      let events: QuantPriceMarket[] | null = null;
      let markets: QuantPriceMarket[] | null = null;
      let failures = 0;
      const publish = () => {
        if (seq !== marketSearchSeq.current) return;
        const eventItems = events || [];
        const marketItems = markets || [];
        const bothSearchesComplete = events !== null && markets !== null;
        const seen = new Set<string>();
        const items = [...eventItems, ...marketItems].filter((item) => {
          const key = `${item.itemKind || 'market'}:${item.marketSlug}`;
          if (seen.has(key)) return false;
          seen.add(key);
          if (item.itemKind !== 'event' && eventItems.some((event) => event.marketSlug === item.marketSlug)) return false;
          return true;
        });
        if (items.length) {
          setQuantMarkets(items);
          setMarketSearchStatus(bothSearchesComplete ? 'ready' : 'partial');
          marketSearchCacheRef.current.set(cacheKey, items);
          if (
            bothSearchesComplete
            && !autoSelectedDefaultRef.current
            && !marketSlugRef.current.trim()
            && !text
            && items[0]?.marketSlug
          ) {
            autoSelectedDefaultRef.current = true;
            setMarketSlug(items[0].marketSlug);
            setSelectedMarketMeta(items[0]);
            setSelectedEntityKindHint(items[0].itemKind === 'event' ? 'event' : 'market');
          }
          return;
        }
        if (events !== null && markets !== null) {
          setQuantMarkets([]);
          setMarketSearchStatus(failures >= 2 ? 'error' : 'empty');
        }
      };
      void fetchQuantPriceMarkets(text, text ? 120 : 80)
        .then((payload) => {
          markets = payload.items || [];
          publish();
        })
        .catch((searchError) => {
          markets = [];
          failures += 1;
          publish();
          if (!isAbortLikeError(searchError)) console.warn('quant market search failed', searchError);
        });
      void fetchQuantPriceEvents(text, text ? 48 : 32)
        .then((payload) => {
          events = payload.items || [];
          publish();
        })
        .catch((searchError) => {
          events = [];
          failures += 1;
          publish();
          if (!isAbortLikeError(searchError)) console.warn('quant event search failed', searchError);
        });
    }, text ? 180 : 0);
    return () => window.clearTimeout(timer);
  }, [marketSearchQuery]);

  useEffect(() => {
    if (!marketSlug.trim()) return;
    const seq = priceLoadSeq.current + 1;
    priceLoadSeq.current = seq;
    const timer = window.setTimeout(() => {
      void refreshQuantRows(seq).catch((loadError) => {
        if (seq !== priceLoadSeq.current) return;
        setError(loadError instanceof Error ? loadError.message : 'Quant API unavailable');
      });
    }, 60);
    return () => window.clearTimeout(timer);
  }, [marketReloadKey, marketSlug, priceSource, timeframe, selectedEntityKind]);

  useEffect(() => {
    return () => {
      if (priceRetryTimerRef.current) window.clearTimeout(priceRetryTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!livePriceRefreshEnabled) return undefined;
    const intervalMs = priceSource === 'frontend' ? 30000 : 8000;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'visible' || liveRefreshInFlightRef.current) return;
      const seq = priceLoadSeq.current + 1;
      priceLoadSeq.current = seq;
      liveRefreshInFlightRef.current = true;
      void refreshQuantRows(seq, { silent: true })
        .catch((loadError) => {
          if (import.meta.env.DEV && !isAbortLikeError(loadError)) console.debug('[quant] live price refresh failed', loadError);
        })
        .finally(() => {
          liveRefreshInFlightRef.current = false;
        });
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [livePriceRefreshEnabled, marketSlug, priceSource, timeframe, selectedEntityKind]);

  useEffect(() => {
    if (!livePriceRefreshEnabled || selectedEntityKind !== 'event' || !marketSlug.trim() || typeof EventSource === 'undefined') return undefined;
    const stream = new EventSource(quantEventPriceStreamUrl({
      eventSlug: marketSlug,
      priceSource: backendPriceSource(priceSource),
      maxOutcomes: EVENT_TILE_OUTCOME_LIMIT,
      interval: priceSource === 'frontend' ? 10 : 2,
    }));
    const onPrice = (event: MessageEvent) => {
      try {
        const update = JSON.parse(String(event.data || '{}')) as EventPriceStreamPayload;
        setMarketSeries((current) => {
          const merged = mergeEventPriceStream(current, update);
          if (merged) priceSeriesCacheRef.current.set(priceRequestKey, merged);
          return merged;
        });
        setLastPriceRefreshAt(new Date().toLocaleTimeString());
      } catch (streamError) {
        if (import.meta.env.DEV) console.debug('[quant] event price stream parse failed', streamError);
      }
    };
    stream.addEventListener('price', onPrice as EventListener);
    stream.onerror = () => {
      if (import.meta.env.DEV) console.debug('[quant] event price stream disconnected');
    };
    return () => {
      stream.removeEventListener('price', onPrice as EventListener);
      stream.close();
    };
  }, [livePriceRefreshEnabled, marketSlug, priceRequestKey, priceSource, selectedEntityKind]);

  useEffect(() => {
    const outcomes = marketSeries?.outcomes || [];
    if (!outcomes.length) {
      setSelectedOutcomeTokenId('');
      return;
    }
    if (!outcomes.some((outcome) => outcome.tokenId === selectedOutcomeTokenId)) {
      setSelectedOutcomeTokenId(defaultOutcomeTokenId(outcomes));
    }
  }, [marketSeries, selectedOutcomeTokenId]);

  const filteredPerformanceRows = useMemo(() => {
    const queryText = performanceSearch.trim().toLowerCase();
    const filtered = backtestResult.performanceRows.filter((row) => (
      !queryText || row.metric.toLowerCase().includes(queryText) || row.description.toLowerCase().includes(queryText)
    ));
    return filtered.slice().sort((a, b) => {
      const left = rowSortValue(a[performanceSortKey]);
      const right = rowSortValue(b[performanceSortKey]);
      const order = left > right ? 1 : left < right ? -1 : 0;
      return performanceSortDirection === 'asc' ? order : -order;
    });
  }, [backtestResult.performanceRows, performanceSearch, performanceSortDirection, performanceSortKey]);

  const filteredTrades = useMemo(() => {
    return backtestResult.trades.filter((trade) => {
      if (tradeFilters.has('profitable') && trade.pnl <= 0) return false;
      if (tradeFilters.has('losing') && trade.pnl >= 0) return false;
      if (tradeFilters.has('yes') && trade.outcome !== 'YES') return false;
      if (tradeFilters.has('no') && trade.outcome !== 'NO') return false;
      if (tradeFilters.has('longHolding') && trade.holdingBars < 12) return false;
      if (tradeFilters.has('shortHolding') && trade.holdingBars >= 12) return false;
      return true;
    });
  }, [backtestResult.trades, tradeFilters]);

  const sortedOutcomeRows = useMemo(() => {
    const eventTitle = marketSeries?.event?.eventTitle || marketSeries?.market?.marketTitle || '';
    return (marketSeries?.outcomes || []).map((outcome, index) => ({
      outcome,
      index,
      label: deriveEventOutcomeLabel(eventTitle, outcome.marketTitle, outcome.outcomeLabel),
      fullLabel: outcome.marketTitle || outcome.outcomeLabel,
      yes: toNumber(outcome.buyYesPrice ?? outcome.latestPrice),
      no: toNumber(outcome.buyNoPrice ?? outcome.complementLatestPrice),
      rows: toNumber(outcome.rows) + toNumber(outcome.complementRows),
      volume: [...(outcome.points || []), ...(outcome.complementPoints || [])].reduce((sum, point) => sum + toNumber(point.volume), 0),
    })).map((row) => ({
      ...row,
      yesKey: chartOutcomeKey(row.outcome, row.label, 'YES'),
      noKey: chartOutcomeKey(row.outcome, row.label, 'NO'),
    })).sort((left, right) => {
      if (outcomeSortKey === 'order') return left.index - right.index;
      if (outcomeSortKey === 'rows') return right.rows - left.rows;
      if (outcomeSortKey === 'volume') return right.volume - left.volume;
      return right.yes - left.yes;
    });
  }, [marketSeries, outcomeSortKey]);
  const displayedOutcomeCount = useMemo(() => {
    const outcomes = marketSeries?.outcomes || [];
    if (selectedEntityKind === 'event' && outcomes.length === 1 && outcomes[0]?.buyNoTokenId) return 2;
    return outcomes.length;
  }, [marketSeries?.outcomes, selectedEntityKind]);
  const selectedOutcomeRow = useMemo(
    () => sortedOutcomeRows.find(({ outcome }) => outcome.tokenId === selectedOutcome?.tokenId) || sortedOutcomeRows[0] || null,
    [selectedOutcome, sortedOutcomeRows],
  );
  const selectedBookQuality = useMemo(() => {
    const yesPoints = selectedOutcome?.points || [];
    const noPoints = selectedOutcome?.complementPoints || [];
    const yes = outcomePointStats(yesPoints);
    const no = outcomePointStats(noPoints);
    const directNoRows = noPoints.filter((point) => !point.isImplied).length;
    const impliedNoRows = noPoints.filter((point) => point.isImplied).length;
    const lastBlock = Math.max(yes.lastBlock, no.lastBlock);
    const firstBlocks = [yes.firstBlock, no.firstBlock].filter((value) => value > 0);
    return {
      yes,
      no,
      firstBlock: firstBlocks.length ? Math.min(...firstBlocks) : 0,
      lastBlock,
      directNoRows,
      impliedNoRows,
      totalRows: yes.rows + no.rows,
      gaps: yes.gaps + no.gaps,
      spikes: yes.spikes + no.spikes,
      status: !yes.rows && !no.rows ? 'empty' : yes.gaps + no.gaps || yes.spikes + no.spikes ? 'review' : 'ready',
    };
  }, [selectedOutcome]);
  const watchlistRows = useMemo(() => {
    const savedRows = watchlistKeys
      .map((key) => sortedOutcomeRows.find(({ outcome }) => outcome.tokenId === key || outcome.buyYesTokenId === key || outcome.buyNoTokenId === key))
      .filter((row): row is (typeof sortedOutcomeRows)[number] => Boolean(row));
    return savedRows.length ? savedRows : sortedOutcomeRows.slice(0, 12);
  }, [sortedOutcomeRows, watchlistKeys]);
  const recentTradeRows = useMemo(() => filteredTrades.slice(-10).reverse(), [filteredTrades]);
  const priceBlockRange = useMemo(() => blockRangeLabel(activePrices), [activePrices]);
  const selectedWatchKey = selectedOutcome?.tokenId || selectedOutcomeRow?.outcome.tokenId || '';
  const selectedIsWatched = selectedWatchKey ? watchlistKeys.includes(selectedWatchKey) : false;
  const dataQuality = useMemo(
    () => dataQualitySummary(activePrices, backendPriceSource(priceSource), marketSeries?.outcomes || [], dataStatus),
    [activePrices, dataStatus, marketSeries, priceSource],
  );
  const recentBuildRuns = useMemo(() => runs.slice(0, 6), [runs]);
  const buildRunSummary = useMemo(() => {
    const latest = recentBuildRuns[0];
    const errors = recentBuildRuns.reduce((sum, run) => sum + toNumber(run.errorCount), 0);
    const rowsWritten = recentBuildRuns.reduce((sum, run) => sum + toNumber(run.rowsWritten), 0);
    return {
      latest,
      errors,
      rowsWritten,
      health: !recentBuildRuns.length ? 'empty' : errors > 0 ? 'review' : 'ready',
    };
  }, [recentBuildRuns]);
  const outcomeQualityRows = useMemo(() => {
    const eventTitle = marketSeries?.event?.eventTitle || marketSeries?.market?.marketTitle || '';
    const latestGlobalBlock = dataQuality.latestBlock || 0;
    return (marketSeries?.outcomes || []).map((outcome) => {
      const label = deriveEventOutcomeLabel(eventTitle, outcome.marketTitle, outcome.outcomeLabel);
      const yes = outcomePointStats(outcome.points);
      const no = outcomePointStats(outcome.complementPoints);
      const lastBlock = Math.max(yes.lastBlock, no.lastBlock);
      const rows = yes.rows + no.rows;
      const gaps = yes.gaps + no.gaps;
      const spikes = yes.spikes + no.spikes;
      const staleBlocks = latestGlobalBlock && lastBlock ? Math.max(0, latestGlobalBlock - lastBlock) : 0;
      const stale = staleBlocks > Math.max(1000, (dataQuality.medianDelta || 0) * 8);
      const status = !rows ? 'empty' : stale ? 'stale' : gaps || spikes ? 'review' : 'ready';
      const firstBlocks = [yes.firstBlock, no.firstBlock].filter((value) => value > 0);
      return {
        key: outcome.tokenId || outcome.marketSlug || label,
        label,
        yesRows: yes.rows,
        noRows: no.rows,
        rows,
        firstBlock: firstBlocks.length ? Math.min(...firstBlocks) : 0,
        lastBlock,
        gaps,
        spikes,
        staleBlocks,
        impliedNoRows: no.impliedRows,
        status,
      };
    }).sort((left, right) => {
      const severity = (row: { status: string; gaps: number; spikes: number; staleBlocks: number }) => (
        row.status === 'empty' ? 4 : row.status === 'stale' ? 3 : row.status === 'review' ? 2 : 1
      ) * 100000 + row.gaps * 1000 + row.spikes * 100 + Math.min(row.staleBlocks, 99);
      return severity(right) - severity(left) || right.rows - left.rows;
    }).slice(0, 18);
  }, [dataQuality.latestBlock, dataQuality.medianDelta, marketSeries]);

  useEffect(() => {
    window.localStorage.setItem('polydata.quant.inspectorTab', inspectorTab);
    window.localStorage.setItem('polydata.quant.inspectorCollapsed', String(inspectorCollapsed));
    window.localStorage.setItem('polydata.quant.strategyDrawerCollapsed', String(strategyDrawerCollapsed));
  }, [inspectorCollapsed, inspectorTab, strategyDrawerCollapsed]);

  useEffect(() => {
    window.localStorage.setItem('polydata.quant.watchlistKeys', JSON.stringify(watchlistKeys));
  }, [watchlistKeys]);

  useEffect(() => {
    window.localStorage.setItem('polydata.quant.chart.pinnedOutcomes', JSON.stringify(chartPinnedOutcomeKeys));
    window.localStorage.setItem('polydata.quant.chart.hiddenOutcomes', JSON.stringify(chartHiddenOutcomeKeys));
  }, [chartHiddenOutcomeKeys, chartPinnedOutcomeKeys]);

  useEffect(() => {
    window.localStorage.setItem('polydata.quant.strategyParameters', JSON.stringify(strategyParameters));
  }, [strategyParameters]);

  const updateStrategyParameters = (next: StrategyParameters) => {
    setStrategyParameters(normalizeStrategyParameters(next));
  };

  const autoTuneStrategyParameters = () => {
    const selectedRows = outcomePricePoints(selectedOutcome, selectedBacktestAction);
    const sourceRows = selectedRows.length ? selectedRows : activePrices;
    const thresholds = strategyDefaults(sourceRows);
    setStrategyParameters((current) => normalizeStrategyParameters({
      ...current,
      ...thresholds,
      maxHoldingBars: Math.max(20, Math.min(240, Math.floor(chartLimit / 30))),
    }));
    setWorkspaceNotice(`strategy tuned from ${sourceRows.length.toLocaleString('en-US')} rows`);
    window.setTimeout(() => setWorkspaceNotice(''), 2400);
  };

  const toggleSelectedWatchlist = () => {
    if (!selectedWatchKey) return;
    setWatchlistKeys((current) => (
      current.includes(selectedWatchKey)
        ? current.filter((key) => key !== selectedWatchKey)
        : [selectedWatchKey, ...current].slice(0, 48)
    ));
  };

  const toggleChartPinnedOutcome = (key: string) => {
    setChartPinnedOutcomeKeys((current) => (current.includes(key) ? current.filter((item) => item !== key) : [key, ...current].slice(0, 24)));
    setChartHiddenOutcomeKeys((current) => current.filter((item) => item !== key));
  };

  const toggleChartHiddenOutcome = (key: string) => {
    setChartHiddenOutcomeKeys((current) => (current.includes(key) ? current.filter((item) => item !== key) : [key, ...current].slice(0, 80)));
    setChartPinnedOutcomeKeys((current) => current.filter((item) => item !== key));
    if (chartSoloOutcomeKey === key) setChartSoloOutcomeKey('');
  };

  const resetChartOutcomeVisibility = () => {
    setChartPinnedOutcomeKeys([]);
    setChartHiddenOutcomeKeys([]);
    setChartSoloOutcomeKey('');
  };

  const togglePerformanceSort = (key: PerformanceSortKey) => {
    if (performanceSortKey === key) {
      setPerformanceSortDirection((current) => (current === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setPerformanceSortKey(key);
    setPerformanceSortDirection('asc');
  };

  const toggleTradeFilter = (filter: TradeFilter) => {
    setTradeFilters((current) => {
      const next = new Set(current);
      if (next.has(filter)) next.delete(filter);
      else next.add(filter);
      return next;
    });
  };

  const exportBacktest = (format: 'csv' | 'json') => {
    if (format === 'csv') {
      downloadText(`quant-backtest-${backtestResult.runId}.csv`, tradesToCsv(backtestResult.trades), 'text/csv;charset=utf-8');
      return;
    }
    downloadText(
      `quant-backtest-${backtestResult.runId}.json`,
      JSON.stringify({ market: marketInfo, priceSource, backtestEngine, timeframe, strategyParameters, result: backtestResult }, null, 2),
      'application/json;charset=utf-8',
    );
  };

  const saveWorkspace = () => {
    const payload = {
      marketSlug,
      marketTitle: marketInfo.title,
      marketSearchQuery,
      timeframe,
      priceSource,
      backtestEngine,
      strategyParameters,
      testerTab,
      deepBacktest,
      savedAt: new Date().toISOString(),
    };
    window.localStorage.setItem('polydata.quant.workspace', JSON.stringify(payload));
    setWorkspaceNotice(`workspace saved ${new Date().toLocaleTimeString()}`);
    window.setTimeout(() => setWorkspaceNotice(''), 2400);
  };

  return (
    <div className="qtv-shell">
      <WorkspaceHeader
        marketSlug={marketSlug}
        marketQuery={marketSearchQuery}
        timeframe={timeframe}
        viewportMode={viewportMode}
        priceSource={priceSource}
        backtestEngine={backtestEngine}
        loading={loading}
        marketOptions={quantMarkets}
        selectedMarket={selectedMarket}
        marketSearchStatus={marketSearchStatus}
        onMarketSlugChange={selectMarketSlug}
        onMarketQueryChange={setMarketSearchQuery}
        onTimeframeChange={changeTimeframePreset}
        onPriceSourceChange={changePriceSource}
        onBacktestEngineChange={setBacktestEngine}
        onRunBacktest={() => void runBacktest()}
        onSave={saveWorkspace}
        onExport={exportBacktest}
        onMarketPreview={prefetchMarketSlug}
      />

      {error ? <div className="qtv-error">{error}</div> : null}

      <main className={`qtv-workspace ${inspectorCollapsed ? 'inspector-collapsed' : ''} ${strategyDrawerCollapsed ? 'drawer-collapsed' : ''}`}>
        <section className="qtv-chart-region" aria-label="Quant chart workspace">
          <PriceChartPanel
            prices={activePrices}
            market={marketInfo}
            selectedTradeId={selectedTradeId}
            signals={strategySignals}
            priceSource={backendPriceSource(priceSource)}
            dataStatus={dataStatus}
            loadingMessage={loadingMessage}
            marketCoverageRows={marketCoverageRows}
            loadedPriceRows={displayedPriceRows}
            backtestRows={displayedPriceRows}
            eventMode={selectedEntityKind === 'event'}
            selectedTokenId={selectedBacktestAction === 'NO' ? selectedOutcome?.buyNoTokenId || '' : selectedOutcome?.buyYesTokenId || selectedOutcome?.tokenId || ''}
            selectedOutcomeLabel={selectedBacktestAction === 'NO' ? selectedOutcome?.buyNoLabel || '' : selectedOutcome?.buyYesLabel || selectedOutcome?.outcomeLabel || ''}
            pinnedOutcomeKeys={chartPinnedOutcomeKeys}
            hiddenOutcomeKeys={chartHiddenOutcomeKeys}
            soloOutcomeKey={chartSoloOutcomeKey}
            onPinnedOutcomeKeysChange={setChartPinnedOutcomeKeys}
            onHiddenOutcomeKeysChange={setChartHiddenOutcomeKeys}
            onSoloOutcomeKeyChange={setChartSoloOutcomeKey}
            onOutcomeSelect={(tokenId, side) => {
              const next = marketSeries?.outcomes?.find((outcome) => (
                side === 'NO' ? outcome.buyNoTokenId === tokenId : (outcome.buyYesTokenId === tokenId || outcome.tokenId === tokenId)
              ));
              if (next) {
                setSelectedOutcomeTokenId(next.tokenId);
                setSelectedBacktestAction(side);
              }
            }}
            onRetry={() => {
              setMarketReloadKey((current) => current + 1);
            }}
            viewportResetKey={`${marketSlug}|${priceSource}|${timeframe}|${viewportResetSeq}`}
            onViewportModeChange={updateViewportMode}
          />
        </section>

        <aside className="qtv-inspector" aria-label="Market inspector">
          <header className="qtv-inspector-head">
            <strong>Inspector</strong>
            <button type="button" onClick={() => setInspectorCollapsed((current) => !current)}>{inspectorCollapsed ? 'Open' : 'Hide'}</button>
          </header>
          {!inspectorCollapsed ? (
            <>
              <nav className="qtv-inspector-tabs" aria-label="Inspector tabs">
                {[
                  ['watchlist', 'Watchlist'],
                  ['market', 'Market'],
                  ['outcomes', 'Outcomes'],
                  ['book', 'Book'],
                  ['trades', 'Trades'],
                  ['dataQuality', 'Data'],
                ].map(([id, label]) => (
                  <button key={id} className={inspectorTab === id ? 'active' : ''} type="button" onClick={() => setInspectorTab(id as InspectorTab)}>{label}</button>
                ))}
              </nav>
              <div className="qtv-inspector-body">
                {inspectorTab === 'watchlist' ? (
                  <div className="qtv-watchlist">
                    <div className="qtv-watchlist-head">
                      <span>{watchlistKeys.length ? `${watchlistKeys.length} saved` : 'Top outcomes'}</span>
                      <button type="button" disabled={!selectedWatchKey} onClick={toggleSelectedWatchlist}>
                        {selectedIsWatched ? 'Remove selected' : 'Add selected'}
                      </button>
                    </div>
                    {watchlistRows.map(({ outcome, label, fullLabel, yes, no, rows }) => {
                      const isSelected = outcome.tokenId === selectedOutcome?.tokenId;
                      const isSaved = watchlistKeys.includes(outcome.tokenId);
                      return (
                        <button
                          key={`watch-${outcome.tokenId}`}
                          className={`${isSelected ? 'active' : ''} ${isSaved ? 'saved' : ''}`}
                          type="button"
                          title={fullLabel}
                          onClick={() => {
                            setSelectedOutcomeTokenId(outcome.tokenId);
                            setSelectedBacktestAction('YES');
                          }}
                        >
                          <span><strong>{label}</strong><em>{rows.toLocaleString('en-US')} rows</em></span>
                          <b>{fmtPrice(yes)}</b>
                          <i>{fmtPrice(no)}</i>
                        </button>
                      );
                    })}
                    {!watchlistRows.length ? <p>No outcomes loaded for the selected market.</p> : null}
                  </div>
                ) : null}

                {inspectorTab === 'market' ? (
                  <div className="qtv-market-card">
                    <h3>{marketInfo.title}</h3>
                    <dl>
                      <div><dt>Type</dt><dd>{selectedEntityKind === 'event' ? 'Event' : 'Market'}</dd></div>
                      <div><dt>Source</dt><dd>{backendPriceSource(priceSource)}</dd></div>
                      <div><dt>Outcomes</dt><dd>{displayedOutcomeCount.toLocaleString('en-US')}</dd></div>
                      <div><dt>Rows Loaded</dt><dd>{displayedPriceRows.toLocaleString('en-US')}</dd></div>
                      <div><dt>Coverage</dt><dd>{marketCoverageRows.toLocaleString('en-US')}</dd></div>
                      <div><dt>Blocks</dt><dd>{priceBlockRange}</dd></div>
                      <div><dt>Latest</dt><dd>{fmtPrice(latestPrice)}</dd></div>
                      <div><dt>Freshness</dt><dd>{lastPriceRefreshAt || '--'}</dd></div>
                      <div><dt>Status</dt><dd>{selectedMarket?.status || marketSeries?.event?.status || marketSeries?.market?.status || '--'}</dd></div>
                      <div><dt>Selected</dt><dd>{selectedOutcomeRow?.fullLabel || selectedOutcome?.outcomeLabel || '--'}</dd></div>
                      <div><dt>YES Token</dt><dd>{selectedOutcome?.buyYesTokenId || selectedOutcome?.tokenId || '--'}</dd></div>
                      <div><dt>NO Token</dt><dd>{selectedOutcome?.buyNoTokenId || '--'}</dd></div>
                      <div><dt>Slug</dt><dd>{marketSlug}</dd></div>
                    </dl>
                  </div>
                ) : null}

                {inspectorTab === 'outcomes' ? (
                  <div className="qtv-inspector-outcomes">
                    <div className="qtv-inspector-sort">
                      <span>
                        {displayedOutcomeCount.toLocaleString('en-US')} outcomes
                        {chartPinnedOutcomeKeys.length || chartHiddenOutcomeKeys.length || chartSoloOutcomeKey ? (
                          <em>{chartPinnedOutcomeKeys.length} pinned · {chartHiddenOutcomeKeys.length} hidden</em>
                        ) : null}
                      </span>
                      <select value={outcomeSortKey} onChange={(event) => setOutcomeSortKey(event.currentTarget.value as OutcomeSortKey)}>
                        <option value="probability">Probability</option>
                        <option value="order">Outcome order</option>
                        <option value="rows">Rows</option>
                        <option value="volume">Volume</option>
                      </select>
                      <button type="button" disabled={!chartPinnedOutcomeKeys.length && !chartHiddenOutcomeKeys.length && !chartSoloOutcomeKey} onClick={resetChartOutcomeVisibility}>Reset lines</button>
                    </div>
                    {sortedOutcomeRows.map(({ outcome, label, fullLabel, yes, no, rows, volume, yesKey, noKey }) => {
                      const isSelected = outcome.tokenId === selectedOutcome?.tokenId;
                      const activeKey = selectedBacktestAction === 'NO' ? noKey : yesKey;
                      const isPinned = chartPinnedOutcomeKeys.includes(yesKey) || chartPinnedOutcomeKeys.includes(noKey);
                      const isHidden = chartHiddenOutcomeKeys.includes(yesKey) || chartHiddenOutcomeKeys.includes(noKey);
                      const isSolo = chartSoloOutcomeKey === yesKey || chartSoloOutcomeKey === noKey;
                      return (
                        <div key={`side-${outcome.tokenId}`} className={`qtv-inspector-outcome ${isSelected ? 'active' : ''} ${isPinned ? 'pinned' : ''} ${isHidden ? 'hidden' : ''} ${isSolo ? 'solo' : ''}`} title={fullLabel}>
                          <button type="button" onClick={() => { setSelectedOutcomeTokenId(outcome.tokenId); setSelectedBacktestAction('YES'); }}>
                            <strong>{label}</strong>
                            <span>{rows.toLocaleString('en-US')} rows · {volume.toLocaleString('en-US', { maximumFractionDigits: 0 })} vol</span>
                          </button>
                          <div>
                            <button className={isSelected && selectedBacktestAction === 'YES' ? 'active' : ''} type="button" onClick={() => { setSelectedOutcomeTokenId(outcome.tokenId); setSelectedBacktestAction('YES'); }}>YES {fmtPrice(yes)}</button>
                            <button className={isSelected && selectedBacktestAction === 'NO' ? 'active no' : 'no'} type="button" disabled={!outcome.buyNoTokenId} onClick={() => { setSelectedOutcomeTokenId(outcome.tokenId); setSelectedBacktestAction('NO'); }}>NO {fmtPrice(no)}</button>
                          </div>
                          <div className="qtv-outcome-line-actions">
                            <button className={chartPinnedOutcomeKeys.includes(activeKey) ? 'active' : ''} type="button" onClick={() => toggleChartPinnedOutcome(activeKey)}>Pin</button>
                            <button className={chartSoloOutcomeKey === activeKey ? 'active' : ''} type="button" onClick={() => setChartSoloOutcomeKey(chartSoloOutcomeKey === activeKey ? '' : activeKey)}>Solo</button>
                            <button className={chartHiddenOutcomeKeys.includes(activeKey) ? 'active danger' : 'danger'} type="button" onClick={() => toggleChartHiddenOutcome(activeKey)}>{chartHiddenOutcomeKeys.includes(activeKey) ? 'Show' : 'Hide'}</button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : null}

                {inspectorTab === 'book' ? (
                  <div className="qtv-book-card">
                    <h3>{selectedOutcomeRow?.fullLabel || selectedOutcome?.outcomeLabel || 'Selected outcome'}</h3>
                    <div className="qtv-book-ladder">
                      <span>YES</span><b>{fmtPrice(selectedOutcomeRow?.yes || 0)}</b>
                      <span>NO</span><b>{fmtPrice(selectedOutcomeRow?.no || 0)}</b>
                      <span>Rows</span><b>{(selectedOutcomeRow?.rows || 0).toLocaleString('en-US')}</b>
                      <span>Volume</span><b>{(selectedOutcomeRow?.volume || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })}</b>
                    </div>
                    <div className="qtv-book-actions">
                      <button className={selectedBacktestAction === 'YES' ? 'active' : ''} type="button" onClick={() => setSelectedBacktestAction('YES')}>Target YES</button>
                      <button className={selectedBacktestAction === 'NO' ? 'active no' : 'no'} type="button" disabled={!selectedOutcome?.buyNoTokenId} onClick={() => setSelectedBacktestAction('NO')}>Target NO</button>
                      <button type="button" onClick={() => setInspectorTab('dataQuality')}>Data quality</button>
                    </div>
                    <dl className="qtv-book-metadata">
                      <div><dt>YES token</dt><dd>{selectedOutcome?.buyYesTokenId || selectedOutcome?.tokenId || '--'}</dd></div>
                      <div><dt>NO token</dt><dd>{selectedOutcome?.buyNoTokenId || '--'}</dd></div>
                      <div><dt>Condition</dt><dd>{selectedOutcome?.conditionId || '--'}</dd></div>
                      <div><dt>Block range</dt><dd>{selectedBookQuality.firstBlock ? Math.floor(selectedBookQuality.firstBlock).toLocaleString('en-US') : '--'} → {selectedBookQuality.lastBlock ? Math.floor(selectedBookQuality.lastBlock).toLocaleString('en-US') : '--'}</dd></div>
                      <div><dt>YES rows</dt><dd>{selectedBookQuality.yes.rows.toLocaleString('en-US')}</dd></div>
                      <div><dt>NO rows</dt><dd>{selectedBookQuality.no.rows.toLocaleString('en-US')}</dd></div>
                      <div><dt>Direct NO</dt><dd>{selectedBookQuality.directNoRows.toLocaleString('en-US')}</dd></div>
                      <div><dt>Implied NO</dt><dd>{selectedBookQuality.impliedNoRows.toLocaleString('en-US')}</dd></div>
                      <div><dt>Gaps</dt><dd>{selectedBookQuality.gaps.toLocaleString('en-US')}</dd></div>
                      <div><dt>Jumps</dt><dd>{selectedBookQuality.spikes.toLocaleString('en-US')}</dd></div>
                    </dl>
                    <div className={`qtv-book-status ${selectedBookQuality.status}`}>
                      <strong>{selectedBookQuality.status === 'ready' ? 'Block-close book proxy ready' : selectedBookQuality.status === 'review' ? 'Review gaps or jumps' : 'No selected outcome rows'}</strong>
                      <span>Live CLOB depth is not connected to this Quant route yet; this panel shows real block-close execution prices and source quality for the selected YES/NO tokens.</span>
                    </div>
                  </div>
                ) : null}

                {inspectorTab === 'trades' ? (
                  <div className="qtv-inspector-trades">
                    {recentTradeRows.map((trade) => (
                      <button key={`inspector-trade-${trade.id}`} className={trade.id === selectedTradeId ? 'active' : ''} type="button" onClick={() => { setSelectedTradeId(trade.id); setTesterTab('trades'); setStrategyDrawerCollapsed(false); }}>
                        <strong>{trade.outcome}</strong>
                        <span>{trade.entryTime} to {trade.exitTime}</span>
                        <b className={trade.pnl >= 0 ? 'positive' : 'negative'}>{trade.pnl >= 0 ? '+' : ''}{trade.pnl.toFixed(2)} USDC</b>
                      </button>
                    ))}
                    {!recentTradeRows.length ? <p>No completed backtest trades yet. Run a backtest to populate this tab.</p> : null}
                  </div>
                ) : null}

                {inspectorTab === 'dataQuality' ? (
                  <div className="qtv-data-quality">
                    <header>
                      <strong>{dataQuality.health === 'ready' ? 'Ready' : dataQuality.health === 'review' ? 'Review suggested' : 'No rows'}</strong>
                      <span>{dataQuality.source}</span>
                    </header>
                    <dl>
                      <div><dt>Loaded rows</dt><dd>{dataQuality.rows.toLocaleString('en-US')}</dd></div>
                      <div><dt>Outcome rows</dt><dd>{dataQuality.outcomeRows.toLocaleString('en-US')}</dd></div>
                      <div><dt>First block</dt><dd>{dataQuality.firstBlock ? Math.floor(dataQuality.firstBlock).toLocaleString('en-US') : '--'}</dd></div>
                      <div><dt>Latest block</dt><dd>{dataQuality.latestBlock ? Math.floor(dataQuality.latestBlock).toLocaleString('en-US') : '--'}</dd></div>
                      <div><dt>Median spacing</dt><dd>{dataQuality.medianDelta ? `${Math.floor(dataQuality.medianDelta).toLocaleString('en-US')} blocks` : '--'}</dd></div>
                      <div><dt>Large gaps</dt><dd>{dataQuality.gapCount.toLocaleString('en-US')}</dd></div>
                      <div><dt>Large jumps</dt><dd>{dataQuality.spikeCount.toLocaleString('en-US')}</dd></div>
                      <div><dt>Direct YES</dt><dd>{dataQuality.directYesRows.toLocaleString('en-US')}</dd></div>
                      <div><dt>Direct NO</dt><dd>{dataQuality.directNoRows.toLocaleString('en-US')}</dd></div>
                      <div><dt>Implied NO</dt><dd>{dataQuality.impliedNoRows.toLocaleString('en-US')}</dd></div>
                    </dl>
                    <div className="qtv-quality-notes">
                      {dataQuality.warnings.length ? dataQuality.warnings.map((warning) => <span key={warning}>{warning}</span>) : <span>Block-close coverage looks usable for this visible window.</span>}
                    </div>
                    <section className="qtv-build-quality">
                      <header>
                        <strong>Build and worker status</strong>
                        <span>{buildRunSummary.health === 'ready' ? 'recent runs clean' : buildRunSummary.health === 'review' ? `${buildRunSummary.errors.toLocaleString('en-US')} errors` : 'no runs loaded'}</span>
                      </header>
                      <dl>
                        <div><dt>Latest run</dt><dd>{buildRunSummary.latest?.runId ? `#${buildRunSummary.latest.runId}` : '--'}</dd></div>
                        <div><dt>Latest status</dt><dd>{buildRunSummary.latest?.status || '--'}</dd></div>
                        <div><dt>Rows written</dt><dd>{buildRunSummary.rowsWritten.toLocaleString('en-US')}</dd></div>
                        <div><dt>Errors</dt><dd>{buildRunSummary.errors.toLocaleString('en-US')}</dd></div>
                      </dl>
                      <div className="qtv-build-run-list">
                        {recentBuildRuns.map((run) => {
                          const statusClass = buildRunStatusClass(run);
                          const complete = toNumber(run.marketsComplete);
                          const total = toNumber(run.marketsTotal);
                          const progress = total ? `${complete.toLocaleString('en-US')} / ${total.toLocaleString('en-US')}` : '--';
                          return (
                            <button
                              key={`build-run-${run.runId}`}
                              className={`qtv-build-run-row ${statusClass}`}
                              type="button"
                              title={run.lastError || `${run.source} ${run.mode || ''}`}
                            >
                              <span>
                                <strong>#{run.runId} {run.source}</strong>
                                <em>{run.mode || 'default'} · {formatBuildTime(run.finishedAt || run.startedAt)}</em>
                              </span>
                              <b>{run.status}</b>
                              <small>{progress}</small>
                              <small>{toNumber(run.rowsWritten).toLocaleString('en-US')} rows</small>
                            </button>
                          );
                        })}
                        {!recentBuildRuns.length ? <p>No build status rows returned yet.</p> : null}
                      </div>
                    </section>
                    <section className="qtv-outcome-quality">
                      <header>
                        <strong>Outcome coverage</strong>
                        <span>{outcomeQualityRows.length.toLocaleString('en-US')} inspected</span>
                      </header>
                      {outcomeQualityRows.map((row) => (
                        <button
                          key={row.key}
                          className={`qtv-outcome-quality-row ${row.status}`}
                          type="button"
                          title={`${row.label}\n${row.firstBlock ? Math.floor(row.firstBlock).toLocaleString('en-US') : '--'} -> ${row.lastBlock ? Math.floor(row.lastBlock).toLocaleString('en-US') : '--'}`}
                          onClick={() => {
                            const next = marketSeries?.outcomes?.find((outcome) => (outcome.tokenId || outcome.marketSlug || outcome.outcomeLabel) === row.key);
                            if (next?.tokenId) {
                              setSelectedOutcomeTokenId(next.tokenId);
                              setInspectorTab('outcomes');
                            }
                          }}
                        >
                          <span>
                            <strong>{row.label}</strong>
                            <em>{row.firstBlock ? Math.floor(row.firstBlock).toLocaleString('en-US') : '--'} {'->'} {row.lastBlock ? Math.floor(row.lastBlock).toLocaleString('en-US') : '--'}</em>
                          </span>
                          <b>{row.status}</b>
                          <small>{row.yesRows.toLocaleString('en-US')}Y / {row.noRows.toLocaleString('en-US')}N</small>
                          <small>{row.gaps} gaps · {row.spikes} jumps</small>
                        </button>
                      ))}
                    </section>
                  </div>
                ) : null}
              </div>
            </>
          ) : null}
        </aside>

        <section className="qtv-strategy-drawer" aria-label="Strategy tester drawer">
          <header className="qtv-drawer-head">
            <div>
              <strong>Strategy Tester</strong>
              <span>{backtestStatus} · {backtestEngine} · {displayedPriceRows.toLocaleString('en-US')} rows</span>
            </div>
            <button type="button" onClick={() => setStrategyDrawerCollapsed((current) => !current)}>{strategyDrawerCollapsed ? 'Expand' : 'Collapse'}</button>
          </header>
          {!strategyDrawerCollapsed ? (
            <StrategyTesterPanel
              result={backtestResult}
              testerTab={testerTab}
              deepBacktest={deepBacktest}
              selectedTradeId={selectedTradeId}
              performanceSearch={performanceSearch}
              performanceSortKey={performanceSortKey}
              performanceSortDirection={performanceSortDirection}
              tradeFilters={tradeFilters}
              filteredPerformanceRows={filteredPerformanceRows}
              filteredTrades={filteredTrades}
              onTesterTabChange={setTesterTab}
              onDeepBacktestChange={() => setDeepBacktest((current) => !current)}
              onRefresh={() => void runBacktest()}
              onExport={exportBacktest}
              onPerformanceSearchChange={setPerformanceSearch}
              onPerformanceSortChange={togglePerformanceSort}
              onTradeFilterToggle={toggleTradeFilter}
              onTradeSelect={(tradeId) => {
                setSelectedTradeId(tradeId);
                setTesterTab('trades');
              }}
              strategyParameters={strategyParameters}
              onStrategyParametersChange={updateStrategyParameters}
              onStrategyAutoTune={autoTuneStrategyParameters}
              marketTitle={marketInfo.title}
              dataSource={backendPriceSource(priceSource)}
              engine={backtestEngine}
              rowCount={displayedPriceRows}
              backtestStatus={backtestStatus}
            />
          ) : null}
        </section>
      </main>

      <div className="qtv-statusbar">
        <span><i>Source</i><b>{priceSource === 'orderfilled' ? 'OrderFilled' : 'Frontend'}</b></span>
        <span><i>Target</i><b>{selectedOutcome?.outcomeLabel || 'Outcome'} {selectedBacktestAction}</b></span>
        <span><i>Latest YES</i><b>{fmtPrice(toNumber(selectedBacktestAction === 'NO' ? selectedOutcome?.buyNoPrice : selectedOutcome?.buyYesPrice) || latestPrice)}</b></span>
        <span><i>Rows</i><b>{displayedPriceRows.toLocaleString('en-US')}</b></span>
        <span><i>Outcomes</i><b>{displayedOutcomeCount}</b></span>
        <span><i>Engine</i><b>{backtestEngine}</b></span>
        <span><i>Build Runs</i><b>{runs.length}</b></span>
        <span><i>Live</i><b>{livePriceRefreshEnabled ? `ON ${lastPriceRefreshAt || 'waiting'}` : 'OFF'}</b></span>
        <span><i>Backtest</i><b>{backtestStatus}</b></span>
        {workspaceNotice ? <span className="notice"><b>{workspaceNotice}</b></span> : null}
        <span><b>UTC+0</b></span>
        <span><b>Auto</b></span>
      </div>
    </div>
  );
}
