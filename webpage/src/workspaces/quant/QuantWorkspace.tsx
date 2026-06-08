import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import {
  createQuantBacktestRun,
  fetchQuantBacktestEquity,
  fetchQuantBacktestMetrics,
  fetchQuantBacktestRun,
  fetchQuantBacktestTrades,
  fetchQuantBlockClosePrices,
  fetchQuantBuildStatus,
  fetchQuantFrontendPrices,
  fetchQuantPriceMarkets,
  isAbortLikeError,
  type QuantPriceQuery,
} from '@/services/api';
import type { QuantBacktestRun, QuantBlockClosePoint, QuantBuildRun, QuantFrontendPricePoint, QuantPriceMarket } from '@/types';
import { PriceChartPanel } from './components/PriceChartPanel';
import { StrategyTesterPanel } from './components/StrategyTesterPanel';
import { WorkspaceHeader } from './components/WorkspaceHeader';
import type { BacktestEngine, BacktestResult, DataStatus, MarketInfo, PerformanceSortKey, PriceSource, Signal, SortDirection, TesterTab, TradeFilter } from './types';
import { backtestApiToResult, blockToPrices, emptyBacktestResult, frontendToPrices } from './utils/apiAdapters';
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

function marketInfoFromSelection(slug: string, market?: QuantPriceMarket): MarketInfo {
  return {
    id: String(market?.marketId || slug || 'quant-market'),
    conditionId: market?.conditionId || '-',
    title: market?.marketTitle || slug || 'Select a Polymarket market',
    category: 'Polymarket',
    slug: market?.marketSlug || slug,
    startTime: market?.firstTs ? new Date(toNumber(market.firstTs) * 1000).toISOString() : '-',
    endTime: market?.endDate || '-',
    resolutionTime: market?.endDate || '-',
    resolvedOutcome: 'PENDING',
    yesTokenId: 'YES',
    noTokenId: 'NO',
    liquidity: '-',
    volume: `${toNumber(market?.blockRows).toLocaleString('en-US')} block rows`,
  };
}

export function QuantWorkspace() {
  const [frontendRows, setFrontendRows] = useState<QuantFrontendPricePoint[]>([]);
  const [blockRows, setBlockRows] = useState<QuantBlockClosePoint[]>([]);
  const [runs, setRuns] = useState<QuantBuildRun[]>([]);
  const [quantMarkets, setQuantMarkets] = useState<QuantPriceMarket[]>([]);
  const [marketSearchStatus, setMarketSearchStatus] = useState<DataStatus>('idle');
  const [selectedMarketMeta, setSelectedMarketMeta] = useState<QuantPriceMarket | null>(null);
  const [dataStatus, setDataStatus] = useState<DataStatus>('idle');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [timeframe, setTimeframe] = useState('2500');
  const [priceSource, setPriceSource] = useState<PriceSource>('orderfilled');
  const [backtestEngine, setBacktestEngine] = useState<BacktestEngine>('backtrader');
  const [testerTab, setTesterTab] = useState<TesterTab>('overview');
  const [deepBacktest, setDeepBacktest] = useState(false);
  const [selectedTradeId, setSelectedTradeId] = useState<string | null>(null);
  const [marketSlug, setMarketSlug] = useState(defaultMarketSlug);
  const [marketSearchQuery, setMarketSearchQuery] = useState(defaultMarketSlug);
  const [backtestStatus, setBacktestStatus] = useState('idle');
  const [performanceSearch, setPerformanceSearch] = useState('');
  const [performanceSortKey, setPerformanceSortKey] = useState<PerformanceSortKey>('metric');
  const [performanceSortDirection, setPerformanceSortDirection] = useState<SortDirection>('asc');
  const [tradeFilters, setTradeFilters] = useState<Set<TradeFilter>>(new Set());
  const [workspaceNotice, setWorkspaceNotice] = useState('');
  const marketSearchSeq = useRef(0);
  const priceLoadSeq = useRef(0);

  const activePrices = useMemo(() => {
    if (priceSource === 'orderfilled') return blockToPrices(blockRows);
    if (priceSource === 'frontend') return frontendToPrices(frontendRows);
    return [];
  }, [blockRows, frontendRows, priceSource]);
  const [backtestResult, setBacktestResult] = useState<BacktestResult>(() => emptyBacktestResult());
  const strategySignals = useMemo(() => signalsFromTrades(backtestResult), [backtestResult]);
  const latestPrice = activePrices[activePrices.length - 1]?.close || 0;
  const selectedMarket = useMemo(
    () => (
      quantMarkets.find((market) => market.marketSlug === marketSlug && market.tokenSide === 'YES')
      || quantMarkets.find((market) => market.marketSlug === marketSlug)
      || (selectedMarketMeta?.marketSlug === marketSlug ? selectedMarketMeta : undefined)
    ),
    [marketSlug, quantMarkets, selectedMarketMeta],
  );
  const marketInfo = useMemo(() => marketInfoFromSelection(marketSlug, selectedMarket), [marketSlug, selectedMarket]);
  const chartLimit = useMemo(() => {
    const parsed = Number(timeframe);
    return Number.isFinite(parsed) ? Math.max(100, Math.min(25000, parsed)) : 2500;
  }, [timeframe]);
  const query: QuantPriceQuery = { marketSlug, tokenSide: 'YES', limit: chartLimit };
  const blockChartQuery: QuantPriceQuery = { marketSlug, limit: chartLimit };

  const refreshQuantRows = async () => {
    const hasMarketSlug = Boolean(marketSlug.trim());
    if (hasMarketSlug) setDataStatus('loading');
    const [frontendResult, blockResult, statusResult] = await Promise.allSettled([
      hasMarketSlug ? fetchQuantFrontendPrices(query) : Promise.resolve({ count: 0, items: [] }),
      hasMarketSlug ? fetchQuantBlockClosePrices(blockChartQuery) : Promise.resolve({ count: 0, items: [] }),
      fetchQuantBuildStatus('', 12),
    ]);
    const nextFrontendRows = frontendResult.status === 'fulfilled' ? frontendResult.value.items || [] : frontendRows;
    const nextBlockRows = blockResult.status === 'fulfilled' ? blockResult.value.items || [] : blockRows;
    if (frontendResult.status === 'fulfilled') setFrontendRows(nextFrontendRows);
    if (blockResult.status === 'fulfilled') setBlockRows(nextBlockRows);
    if (statusResult.status === 'fulfilled') setRuns(statusResult.value.items || []);
    const activeRowCount = priceSource === 'orderfilled' ? nextBlockRows.length : nextFrontendRows.length;
    if (hasMarketSlug) setDataStatus(activeRowCount ? 'ready' : 'empty');
    const criticalResult = priceSource === 'orderfilled' ? blockResult : frontendResult;
    if (hasMarketSlug && criticalResult.status === 'rejected') {
      setDataStatus('error');
      throw criticalResult.reason instanceof Error ? criticalResult.reason : new Error('Quant API unavailable');
    }
    return {
      frontendRows: nextFrontendRows,
      blockRows: nextBlockRows,
    };
  };

  const runBacktest = async () => {
    setLoading(true);
    setError('');
    setBacktestStatus('submitting');
    try {
      const nextRows = await refreshQuantRows();
      if (!marketSlug.trim()) {
        throw new Error('market_slug is required for real backtest');
      }
      const backtestBlockRows = nextRows.blockRows.filter((row) => String(row.tokenSide || '').toUpperCase() === 'YES');
      const sourceRows = priceSource === 'orderfilled' ? backtestBlockRows : nextRows.frontendRows;
      if (!sourceRows.length) {
        throw new Error(`No ${backendPriceSource(priceSource)} rows for ${marketSlug.trim()}`);
      }
      const firstBlock = backtestBlockRows[0]?.blockNumber;
      const lastBlock = backtestBlockRows[backtestBlockRows.length - 1]?.blockNumber;
      const firstTs = nextRows.frontendRows[0]?.timestamp;
      const lastTs = nextRows.frontendRows[nextRows.frontendRows.length - 1]?.timestamp;
      const strategy = strategyDefaults(priceSource === 'orderfilled' ? blockToPrices(backtestBlockRows) : frontendToPrices(nextRows.frontendRows));
      const created = await createQuantBacktestRun({
        marketSlug: marketSlug.trim(),
        tokenSide: 'YES',
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
    const nextMarket = quantMarkets.find((market) => market.marketSlug === nextSlug && market.tokenSide === 'YES')
      || quantMarkets.find((market) => market.marketSlug === nextSlug)
      || null;
    setMarketSlug(nextSlug);
    setMarketSearchQuery(nextSlug);
    setSelectedMarketMeta(nextMarket);
    setFrontendRows([]);
    setBlockRows([]);
    setBacktestResult(emptyBacktestResult());
    setSelectedTradeId(null);
    setError('');
    if (nextSlug) setDataStatus('loading');
  };

  useEffect(() => {
    const text = marketSearchQuery.trim();
    const seq = marketSearchSeq.current + 1;
    marketSearchSeq.current = seq;
    setMarketSearchStatus('loading');
    const timer = window.setTimeout(() => {
      void fetchQuantPriceMarkets(text, 40)
        .then((payload) => {
          if (seq !== marketSearchSeq.current) return;
          const items = payload.items || [];
          setQuantMarkets(items);
          setMarketSearchStatus(items.length ? 'ready' : 'empty');
          if (!marketSlug.trim() && !text && items[0]?.marketSlug) {
            setMarketSlug(items[0].marketSlug);
            setMarketSearchQuery(items[0].marketSlug);
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
  }, [marketSearchQuery, marketSlug]);

  useEffect(() => {
    if (!marketSlug.trim()) return;
    const seq = priceLoadSeq.current + 1;
    priceLoadSeq.current = seq;
    const timer = window.setTimeout(() => {
      void refreshQuantRows().catch((loadError) => {
        if (seq !== priceLoadSeq.current) return;
        setError(loadError instanceof Error ? loadError.message : 'Quant API unavailable');
      });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [marketSlug, priceSource, timeframe]);

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
        marketSearchStatus={marketSearchStatus}
        onMarketSlugChange={selectMarketSlug}
        onMarketQueryChange={setMarketSearchQuery}
        onTimeframeChange={setTimeframe}
        onPriceSourceChange={setPriceSource}
        onBacktestEngineChange={setBacktestEngine}
        onRunBacktest={() => void runBacktest()}
        onSave={saveWorkspace}
        onExport={exportBacktest}
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
        />

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
        />
      </main>

      <div className="qtv-statusbar">
        <span>source {priceSource}</span>
        <span>latest YES {fmtPrice(latestPrice)}</span>
        <span>frontend rows {frontendRows.length}</span>
        <span>block close rows {blockRows.length}</span>
        <span>engine {backtestEngine}</span>
        <span>build runs {runs.length}</span>
        <span>backtest {backtestStatus}</span>
        {workspaceNotice ? <span>{workspaceNotice}</span> : null}
        <span>UTC+0</span>
        <span>%</span>
        <span>log</span>
        <span>auto</span>
      </div>
    </div>
  );
}
