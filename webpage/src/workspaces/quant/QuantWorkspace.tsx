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
  type QuantPriceQuery,
} from '@/services/api';
import type { QuantBacktestRun, QuantBlockClosePoint, QuantBuildRun, QuantFrontendPricePoint, QuantMarketSeriesOutcome, QuantMarketSeriesPayload, QuantPriceMarket } from '@/types';
import { PriceChartPanel } from './components/PriceChartPanel';
import { StrategyTesterPanel } from './components/StrategyTesterPanel';
import { WorkspaceHeader } from './components/WorkspaceHeader';
import type { BacktestEngine, BacktestResult, DataStatus, MarketInfo, PerformanceSortKey, PriceSource, Signal, SortDirection, TesterTab, TradeFilter } from './types';
import { backtestApiToResult, blockToPrices, emptyBacktestResult, frontendToPrices, marketSeriesToPrices } from './utils/apiAdapters';
import { downloadText, fmtPrice } from './utils/formatters';

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

function defaultMarketSlug() {
  const params = new URLSearchParams(window.location.search);
  return params.get('market') || params.get('market_slug') || params.get('slug') || '';
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
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
  const [selectedMarketMeta, setSelectedMarketMeta] = useState<QuantPriceMarket | null>(null);
  const [dataStatus, setDataStatus] = useState<DataStatus>('idle');
  const [loadingMessage, setLoadingMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [timeframe, setTimeframe] = useState('2500');
  const [priceSource, setPriceSource] = useState<PriceSource>('orderfilled');
  const [backtestEngine, setBacktestEngine] = useState<BacktestEngine>('backtrader');
  const [testerTab, setTesterTab] = useState<TesterTab>('overview');
  const [deepBacktest, setDeepBacktest] = useState(false);
  const [selectedTradeId, setSelectedTradeId] = useState<string | null>(null);
  const [marketSlug, setMarketSlug] = useState(defaultMarketSlug);
  const [marketSearchQuery, setMarketSearchQuery] = useState('');
  const [marketReloadKey, setMarketReloadKey] = useState(0);
  const [backtestStatus, setBacktestStatus] = useState('idle');
  const [performanceSearch, setPerformanceSearch] = useState('');
  const [performanceSortKey, setPerformanceSortKey] = useState<PerformanceSortKey>('metric');
  const [performanceSortDirection, setPerformanceSortDirection] = useState<SortDirection>('asc');
  const [tradeFilters, setTradeFilters] = useState<Set<TradeFilter>>(new Set());
  const [workspaceNotice, setWorkspaceNotice] = useState('');
  const marketSearchSeq = useRef(0);
  const priceLoadSeq = useRef(0);
  const priceSeriesCacheRef = useRef(new Map<string, QuantMarketSeriesPayload>());
  const pricePrefetchingRef = useRef(new Set<string>());

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
  const selectedEntityKind = selectedMarket?.itemKind === 'event' ? 'event' : 'market';
  const marketInfo = useMemo(() => marketInfoFromSelection(marketSlug, selectedMarket), [marketSlug, selectedMarket]);
  const marketCoverageRows = toNumber(selectedMarket?.blockRows || selectedMarket?.frontendRows || marketSeries?.outcomes?.reduce((sum, outcome) => sum + toNumber(outcome.rows), 0));
  const chartLimit = useMemo(() => {
    const parsed = Number(timeframe);
    return Number.isFinite(parsed) ? Math.max(100, Math.min(25000, parsed)) : 2500;
  }, [timeframe]);
  const semanticChartQuery: QuantPriceQuery & { priceSource: string; scope: string; maxOutcomes: number } = {
    marketSlug,
    priceSource: backendPriceSource(priceSource),
    scope: 'auto',
    limit: chartLimit,
    maxOutcomes: selectedEntityKind === 'event' ? 100 : 24,
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

  const refreshQuantRows = async (requestSeq = priceLoadSeq.current) => {
    const hasMarketSlug = Boolean(marketSlug.trim());
    const cacheKey = priceRequestKey;
    if (hasMarketSlug) {
      const cached = priceSeriesCacheRef.current.get(cacheKey);
      if (cached) {
        setMarketSeries(cached);
        setDataStatus('partial');
        setLoadingMessage('Refreshing cached price series...');
      } else {
        setDataStatus(selectedMarket ? 'price_loading' : 'metadata_loading');
        setLoadingMessage(selectedMarket ? 'Loading price series...' : 'Loading market metadata...');
      }
      if (import.meta.env.DEV) {
        console.debug('[quant] price load start', { cacheKey, cached: Boolean(cached), marketSlug, priceSource, timeframe });
      }
    }
    const [seriesResult, statusResult] = await Promise.allSettled([
      hasMarketSlug
        ? (selectedEntityKind === 'event'
          ? fetchQuantEventPriceSeries({ ...semanticChartQuery, eventSlug: marketSlug, maxOutcomes: 100 })
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
    }
    if (priceSource !== 'frontend') setFrontendRows([]);
    if (priceSource !== 'orderfilled') setBlockRows([]);
    if (statusResult.status === 'fulfilled') setRuns(statusResult.value.items || []);
    const activeRowCount = marketSeriesToPrices(nextMarketSeries).length || (priceSource === 'orderfilled' ? nextBlockRows.length : nextFrontendRows.length);
    if (hasMarketSlug) {
      setDataStatus(activeRowCount ? 'ready' : 'empty');
      setLoadingMessage(activeRowCount ? '' : 'No price rows found for this source/window');
      if (import.meta.env.DEV) console.debug('[quant] price load complete', { cacheKey, activeRowCount });
    }
    if (hasMarketSlug && seriesResult.status === 'rejected') {
      const hasCached = priceSeriesCacheRef.current.has(cacheKey);
      setDataStatus(hasCached ? 'partial' : 'error');
      setLoadingMessage(hasCached ? 'Showing cached data; refresh failed.' : 'Price request failed.');
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
    const cached = nextSlug ? priceSeriesCacheRef.current.get(seriesKeyForSlug(nextSlug, nextMarket?.itemKind === 'event' ? 'event' : 'market')) : null;
    setFrontendRows([]);
    setBlockRows([]);
    setMarketSeries(cached || null);
    setSelectedOutcomeTokenId('');
    setSelectedBacktestAction('YES');
    setBacktestResult(emptyBacktestResult());
    setSelectedTradeId(null);
    setError('');
    if (nextSlug) {
      setDataStatus(cached ? 'partial' : 'metadata_loading');
      setLoadingMessage(cached ? 'Rendering cached data...' : 'Loading market metadata...');
    }
  };

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
      maxOutcomes: nextKind === 'event' ? 100 : 24,
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
    const seq = marketSearchSeq.current + 1;
    marketSearchSeq.current = seq;
    setMarketSearchStatus('loading');
    const timer = window.setTimeout(() => {
      void Promise.allSettled([fetchQuantPriceEvents(text, 24), fetchQuantPriceMarkets(text, 40)])
        .then(([eventResult, marketResult]) => {
          if (seq !== marketSearchSeq.current) return;
          const events = eventResult.status === 'fulfilled' ? eventResult.value.items || [] : [];
          const markets = marketResult.status === 'fulfilled' ? marketResult.value.items || [] : [];
          const seen = new Set<string>();
          const items = [...events, ...markets].filter((item) => {
            const key = `${item.itemKind || 'market'}:${item.marketSlug}`;
            if (seen.has(key)) return false;
            seen.add(key);
            if (item.itemKind !== 'event' && events.some((event) => event.marketSlug === item.marketSlug)) return false;
            return true;
          });
          setQuantMarkets(items);
          setMarketSearchStatus(items.length ? 'ready' : 'empty');
          if (!marketSlug.trim() && !text && items[0]?.marketSlug) {
            setMarketSlug(items[0].marketSlug);
            setSelectedMarketMeta(items[0]);
          }
        })
        .catch((searchError) => {
          if (seq !== marketSearchSeq.current) return;
          setMarketSearchStatus('error');
          if (text) setQuantMarkets([]);
          if (!isAbortLikeError(searchError)) {
            console.warn('quant market search failed', searchError);
          }
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
          onRetry={() => {
            setMarketReloadKey((current) => current + 1);
          }}
        />

        {marketSeries?.outcomes?.length ? (
          <section className="qtv-outcome-board" aria-label="Polymarket outcomes">
            {marketSeries.outcomes.map((outcome) => {
              const isSelected = outcome.tokenId === selectedOutcome?.tokenId;
              return (
              <div
                key={outcome.tokenId}
                className={`qtv-outcome-row ${isSelected ? 'active' : ''}`}
              >
                <span>
                  <strong>{outcome.outcomeLabel}</strong>
                  <em>{Number(outcome.rows || 0).toLocaleString('en-US')} rows</em>
                </span>
                <b>{fmtPrice(toNumber(outcome.latestPrice))}</b>
                <div className="qtv-outcome-actions">
                  <button
                    className={isSelected && selectedBacktestAction === 'YES' ? 'active' : ''}
                    type="button"
                    onClick={() => {
                      setSelectedOutcomeTokenId(outcome.tokenId);
                      setSelectedBacktestAction('YES');
                    }}
                  >
                    Buy Yes {fmtPrice(toNumber(outcome.buyYesPrice ?? outcome.latestPrice))}
                  </button>
                  <button
                    className={isSelected && selectedBacktestAction === 'NO' ? 'active no' : 'no'}
                    type="button"
                    disabled={!outcome.buyNoTokenId}
                    onClick={() => {
                      setSelectedOutcomeTokenId(outcome.tokenId);
                      setSelectedBacktestAction('NO');
                    }}
                  >
                    Buy No {fmtPrice(toNumber(outcome.buyNoPrice ?? outcome.complementLatestPrice))}
                  </button>
                </div>
              </div>
            );})}
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
        <span><i>Outcomes</i><b>{marketSeries?.outcomes?.length || 0}</b></span>
        <span><i>Engine</i><b>{backtestEngine}</b></span>
        <span><i>Build Runs</i><b>{runs.length}</b></span>
        <span><i>Backtest</i><b>{backtestStatus}</b></span>
        {workspaceNotice ? <span className="notice"><b>{workspaceNotice}</b></span> : null}
        <span><b>UTC+0</b></span>
        <span><b>Auto</b></span>
      </div>
    </div>
  );
}
