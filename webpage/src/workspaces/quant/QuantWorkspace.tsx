import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import {
  createQuantBacktestRun,
  fetchQuantBacktestEquity,
  fetchQuantBacktestMetrics,
  fetchQuantBacktestRun,
  fetchQuantBacktestTrades,
  fetchQuantBuildStatus,
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
import type { BacktestEngine, BacktestResult, DataStatus, MarketInfo, PerformanceSortKey, PriceSource, Signal, SortDirection, TesterTab, TradeFilter } from './types';
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
  if (Number.isFinite(lastX) && x <= lastX) return current;
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
  const [timeframe, setTimeframe] = useState('25000');
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
  const marketSearchSeq = useRef(0);
  const priceLoadSeq = useRef(0);
  const marketSlugRef = useRef(marketSlug);
  const autoSelectedDefaultRef = useRef(Boolean(defaultMarketSlug()));
  const marketSearchCacheRef = useRef(new Map<string, QuantPriceMarket[]>());
  const priceSeriesCacheRef = useRef(new Map<string, QuantMarketSeriesPayload>());
  const pricePrefetchingRef = useRef(new Set<string>());
  const liveRefreshInFlightRef = useRef(false);

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
  const semanticChartQuery: QuantPriceQuery & { priceSource: string; scope: string; maxOutcomes: number; topN?: number; maxPoints?: number } = {
    marketSlug,
    priceSource: backendPriceSource(priceSource),
    scope: 'auto',
    limit: chartLimit,
    maxOutcomes: selectedEntityKind === 'event' ? EVENT_TILE_OUTCOME_LIMIT : 24,
    topN: selectedEntityKind === 'event' ? EVENT_TILE_OUTCOME_LIMIT : undefined,
    maxPoints: selectedEntityKind === 'event' ? (chartRange === 'full' ? EVENT_TILE_FULL_MAX_POINTS : EVENT_TILE_MAX_POINTS) : undefined,
    range: selectedEntityKind === 'event' ? chartRange : undefined,
    resolution: selectedEntityKind === 'event' ? 'auto' : undefined,
  };
  const priceRequestKey = [
    selectedEntityKind,
    marketSlug.trim(),
    backendPriceSource(priceSource),
    timeframe,
    selectedOutcomeTokenId || 'all-outcomes',
    selectedBacktestAction,
  ].join('|');

  const seriesKeyForSlug = (slug: string, itemKind = selectedEntityKind) => [
    itemKind,
    slug.trim(),
    backendPriceSource(priceSource),
    timeframe,
    'all-outcomes',
    'YES',
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
    const [seriesResult, statusResult] = await Promise.allSettled([
      hasMarketSlug
        ? (selectedEntityKind === 'event'
          ? fetchQuantEventPriceSeries({ ...semanticChartQuery, eventSlug: marketSlug })
          : fetchQuantMarketPriceSeries(semanticChartQuery))
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
    const nextMarketSeries = seriesResult.status === 'fulfilled' ? seriesResult.value : marketSeries;
    const nextFrontendRows = priceSource === 'frontend' ? frontendRows : [];
    const nextBlockRows = priceSource === 'orderfilled' ? blockRows : [];
    if (seriesResult.status === 'fulfilled') {
      if (nextMarketSeries) priceSeriesCacheRef.current.set(cacheKey, nextMarketSeries);
      setMarketSeries(nextMarketSeries);
      setLastPriceRefreshAt(new Date().toLocaleTimeString());
    }
    if (priceSource !== 'frontend') setFrontendRows([]);
    if (priceSource !== 'orderfilled') setBlockRows([]);
    if (statusResult.status === 'fulfilled') setRuns(statusResult.value.items || []);
    const activeRowCount = marketSeriesToPrices(nextMarketSeries).length || (priceSource === 'orderfilled' ? nextBlockRows.length : nextFrontendRows.length);
    if (hasMarketSlug) {
      if (!silent) {
        setDataStatus(activeRowCount ? 'ready' : 'empty');
        setLoadingMessage(activeRowCount ? '' : 'No price rows found for this source/window');
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
      const strategy = strategyDefaults(sourceRows);
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
        entryThreshold: strategy.entryThreshold,
        exitThreshold: strategy.exitThreshold,
        stopLoss: 0.075,
        takeProfit: 0.16,
        maxHoldingBars: Math.max(20, Math.min(240, Math.floor(chartLimit / 30))),
        initialCapital: 100000,
        positionSize: 100,
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
    const nextMarket = quantMarkets.find((market) => market.marketSlug === nextSlug && market.itemKind === 'event')
      || quantMarkets.find((market) => market.marketSlug === nextSlug && market.tokenSide === 'YES')
      || quantMarkets.find((market) => market.marketSlug === nextSlug)
      || null;
    setMarketSlug(nextSlug);
    setMarketSearchQuery('');
    setMarketReloadKey((current) => current + 1);
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
    void (nextKind === 'event' ? fetchQuantEventPriceSeries({ ...request, eventSlug: nextSlug }) : fetchQuantMarketPriceSeries(request))
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
      void fetchQuantPriceMarkets(text, 40)
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
      void fetchQuantPriceEvents(text, 24)
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
  }, [marketReloadKey, marketSlug, priceSource, timeframe, selectedOutcomeTokenId, selectedBacktestAction, selectedEntityKind]);

  useEffect(() => {
    if (!livePriceRefreshEnabled) return undefined;
    const intervalMs = priceSource === 'frontend' ? 60000 : 30000;
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
  }, [livePriceRefreshEnabled, marketSlug, priceSource, timeframe, selectedOutcomeTokenId, selectedBacktestAction, selectedEntityKind]);

  useEffect(() => {
    if (!livePriceRefreshEnabled || selectedEntityKind !== 'event' || !marketSlug.trim() || typeof EventSource === 'undefined') return undefined;
    const stream = new EventSource(quantEventPriceStreamUrl({
      eventSlug: marketSlug,
      priceSource: backendPriceSource(priceSource),
      maxOutcomes: EVENT_TILE_OUTCOME_LIMIT,
      interval: priceSource === 'frontend' ? 15 : 5,
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
  const useOutcomeTable = selectedEntityKind === 'event'
    ? (marketSeries?.outcomes?.length || 0) >= 4
    : (marketSeries?.outcomes?.length || 0) > 4;

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
      JSON.stringify({ market: marketInfo, priceSource, backtestEngine, timeframe, result: backtestResult }, null, 2),
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
        priceSource={priceSource}
        backtestEngine={backtestEngine}
        loading={loading}
        marketOptions={quantMarkets}
        selectedMarket={selectedMarket}
        marketSearchStatus={marketSearchStatus}
        onMarketSlugChange={selectMarketSlug}
        onMarketQueryChange={setMarketSearchQuery}
        onTimeframeChange={setTimeframe}
        onPriceSourceChange={setPriceSource}
        onBacktestEngineChange={setBacktestEngine}
        onRunBacktest={() => void runBacktest()}
        onSave={saveWorkspace}
        onExport={exportBacktest}
        onMarketPreview={prefetchMarketSlug}
      />

      {error ? <div className="qtv-error">{error}</div> : null}

      <main className="qtv-workspace">
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
        />

        {marketSeries?.outcomes?.length ? (
          <section className={`qtv-outcome-board ${useOutcomeTable ? 'table-mode' : 'card-mode'}`} aria-label="Polymarket outcomes">
            <header className="qtv-outcome-board-head">
              <strong>{displayedOutcomeCount.toLocaleString('en-US')} outcomes</strong>
              <div>
                <span>Sort</span>
                <select value={outcomeSortKey} onChange={(event) => setOutcomeSortKey(event.currentTarget.value as OutcomeSortKey)}>
                  <option value="probability">Probability</option>
                  <option value="order">Outcome order</option>
                  <option value="rows">Rows</option>
                  <option value="volume">Volume</option>
                </select>
              </div>
            </header>
            {useOutcomeTable ? (
              <div className="qtv-outcome-table" role="table">
                <div className="qtv-outcome-table-row head" role="row">
                  <span>Outcome</span><span>YES</span><span>NO</span><span>Rows</span><span>Volume</span><span>Coverage</span><span>Actions</span>
                </div>
                {sortedOutcomeRows.map(({ outcome, label, fullLabel, yes, no, rows, volume }) => {
                  const isSelected = outcome.tokenId === selectedOutcome?.tokenId;
                  return (
                    <button
                      key={outcome.tokenId}
                      className={`qtv-outcome-table-row ${isSelected ? 'active' : ''}`}
                      type="button"
                      role="row"
                      title={fullLabel}
                      onClick={() => {
                        setSelectedOutcomeTokenId(outcome.tokenId);
                        setSelectedBacktestAction('YES');
                      }}
                    >
                      <strong>{label}</strong>
                      <b>{fmtPrice(yes)}</b>
                      <b>{fmtPrice(no)}</b>
                      <span>{rows.toLocaleString('en-US')}</span>
                      <span>{volume.toLocaleString('en-US', { maximumFractionDigits: 0 })}</span>
                      <em>{outcome.coverageStatus || (rows ? 'ready' : 'none')}</em>
                      <i>
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelectedOutcomeTokenId(outcome.tokenId);
                            setSelectedBacktestAction('YES');
                          }}
                        >
                          Backtest Yes
                        </span>
                        <span
                          role="button"
                          tabIndex={0}
                          className={!outcome.buyNoTokenId ? 'disabled' : ''}
                          onClick={(event) => {
                            event.stopPropagation();
                            if (!outcome.buyNoTokenId) return;
                            setSelectedOutcomeTokenId(outcome.tokenId);
                            setSelectedBacktestAction('NO');
                          }}
                        >
                          Backtest No
                        </span>
                      </i>
                    </button>
                  );
                })}
              </div>
            ) : sortedOutcomeRows.map(({ outcome, label, fullLabel, yes, no, rows }) => {
              const isSelected = outcome.tokenId === selectedOutcome?.tokenId;
              return (
                <div key={outcome.tokenId} className={`qtv-outcome-row ${isSelected ? 'active' : ''}`} title={fullLabel}>
                  <span>
                    <strong>{label}</strong>
                    <em>{rows.toLocaleString('en-US')} rows</em>
                  </span>
                  <b>{fmtPrice(yes)}</b>
                  <div className="qtv-outcome-actions">
                    <button className={isSelected && selectedBacktestAction === 'YES' ? 'active' : ''} type="button" onClick={() => { setSelectedOutcomeTokenId(outcome.tokenId); setSelectedBacktestAction('YES'); }}>
                      Backtest Yes {fmtPrice(yes)}
                    </button>
                    <button className={isSelected && selectedBacktestAction === 'NO' ? 'active no' : 'no'} type="button" disabled={!outcome.buyNoTokenId} onClick={() => { setSelectedOutcomeTokenId(outcome.tokenId); setSelectedBacktestAction('NO'); }}>
                      Backtest No {fmtPrice(no)}
                    </button>
                  </div>
                </div>
              );
            })}
          </section>
        ) : null}

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
          marketTitle={marketInfo.title}
          dataSource={backendPriceSource(priceSource)}
          engine={backtestEngine}
          rowCount={displayedPriceRows}
          backtestStatus={backtestStatus}
        />
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
