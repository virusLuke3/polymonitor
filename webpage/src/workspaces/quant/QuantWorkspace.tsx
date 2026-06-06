import { useEffect, useMemo, useState } from 'preact/hooks';
import {
  createQuantBacktestRun,
  fetchQuantBacktestEquity,
  fetchQuantBacktestMetrics,
  fetchQuantBacktestRun,
  fetchQuantBacktestTrades,
  fetchQuantBlockClosePrices,
  fetchQuantBuildStatus,
  fetchQuantFrontendPrices,
  type QuantPriceQuery,
} from '@/services/api';
import type { QuantBlockClosePoint, QuantBuildRun, QuantFrontendPricePoint } from '@/types';
import { PriceChartPanel } from './components/PriceChartPanel';
import { StrategyTesterPanel } from './components/StrategyTesterPanel';
import { WorkspaceHeader } from './components/WorkspaceHeader';
import { MARKET_INFO, MOCK_PRICES, MOCK_SIGNALS } from './data/mockBacktestData';
import type { BacktestResult, PerformanceSortKey, PriceSource, Signal, SortDirection, TesterTab, TradeFilter } from './types';
import { backtestApiToResult, blockToPrices, frontendToPrices } from './utils/apiAdapters';
import { buildBacktestResult } from './utils/backtest';
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

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function waitForRun(runId: number) {
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const response = await fetchQuantBacktestRun(runId);
    if (!['queued', 'running'].includes(response.item.status)) return response.item;
    await sleep(900);
  }
  return (await fetchQuantBacktestRun(runId)).item;
}

function signalsFromTrades(result: BacktestResult): Signal[] {
  const derived = result.trades.flatMap((trade) => {
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
  return derived.length ? derived : MOCK_SIGNALS;
}

export function QuantWorkspace() {
  const [frontendRows, setFrontendRows] = useState<QuantFrontendPricePoint[]>([]);
  const [blockRows, setBlockRows] = useState<QuantBlockClosePoint[]>([]);
  const [runs, setRuns] = useState<QuantBuildRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [timeframe, setTimeframe] = useState('5m');
  const [priceSource, setPriceSource] = useState<PriceSource>('frontend');
  const [testerTab, setTesterTab] = useState<TesterTab>('overview');
  const [deepBacktest, setDeepBacktest] = useState(false);
  const [selectedTradeId, setSelectedTradeId] = useState<string | null>(null);
  const [marketSlug, setMarketSlug] = useState('');
  const [runId, setRunId] = useState(1);
  const [performanceSearch, setPerformanceSearch] = useState('');
  const [performanceSortKey, setPerformanceSortKey] = useState<PerformanceSortKey>('metric');
  const [performanceSortDirection, setPerformanceSortDirection] = useState<SortDirection>('asc');
  const [tradeFilters, setTradeFilters] = useState<Set<TradeFilter>>(new Set());

  const activePrices = useMemo(() => {
    if (priceSource === 'orderfilled') return blockToPrices(blockRows);
    if (priceSource === 'frontend') return frontendToPrices(frontendRows);
    return [];
  }, [blockRows, frontendRows, priceSource]);
  const renderedPrices = activePrices.length ? activePrices : MOCK_PRICES;
  const [backtestResult, setBacktestResult] = useState<BacktestResult>(() => buildBacktestResult(MOCK_PRICES, 'frontend', '5m', 1));
  const strategySignals = useMemo(() => signalsFromTrades(backtestResult), [backtestResult]);
  const latestPrice = renderedPrices[renderedPrices.length - 1]?.close || 0;
  const query: QuantPriceQuery = { marketSlug, tokenSide: 'YES', limit: 360 };

  const refreshQuantRows = async () => {
    const hasMarketSlug = Boolean(marketSlug.trim());
    const [frontendResult, blockResult, statusResult] = await Promise.allSettled([
      hasMarketSlug ? fetchQuantFrontendPrices(query) : Promise.resolve({ count: 0, items: [] }),
      hasMarketSlug ? fetchQuantBlockClosePrices(query) : Promise.resolve({ count: 0, items: [] }),
      fetchQuantBuildStatus('', 12),
    ]);
    const nextFrontendRows = frontendResult.status === 'fulfilled' ? frontendResult.value.items || [] : frontendRows;
    const nextBlockRows = blockResult.status === 'fulfilled' ? blockResult.value.items || [] : blockRows;
    if (frontendResult.status === 'fulfilled') setFrontendRows(nextFrontendRows);
    if (blockResult.status === 'fulfilled') setBlockRows(nextBlockRows);
    if (statusResult.status === 'fulfilled') setRuns(statusResult.value.items || []);
    const rejected = [frontendResult, blockResult, statusResult].find((result) => result.status === 'rejected');
    if (hasMarketSlug && rejected?.status === 'rejected') {
      throw rejected.reason instanceof Error ? rejected.reason : new Error('Quant API unavailable');
    }
    return {
      frontendRows: nextFrontendRows,
      blockRows: nextBlockRows,
    };
  };

  const runBacktest = async () => {
    setLoading(true);
    setError('');
    try {
      const nextRows = await refreshQuantRows();
      if (!marketSlug.trim()) {
        throw new Error('market_slug is required for real backtest');
      }
      const created = await createQuantBacktestRun({
        marketSlug: marketSlug.trim(),
        tokenSide: 'YES',
        priceSource: backendPriceSource(priceSource),
        entryThreshold: 0.58,
        exitThreshold: 0.44,
        stopLoss: 0.075,
        takeProfit: 0.16,
        maxHoldingBars: timeframe === '1m' ? 240 : 96,
        initialCapital: 100000,
        positionSize: 100,
      });
      const completedRun = ['queued', 'running'].includes(created.item.status)
        ? await waitForRun(created.runId)
        : created.item;
      if (completedRun.status === 'failed') {
        throw new Error(completedRun.error || 'Backtest failed');
      }
      const [metricsResult, equityResult, tradesResult] = await Promise.all([
        fetchQuantBacktestMetrics(completedRun.runId),
        fetchQuantBacktestEquity(completedRun.runId),
        fetchQuantBacktestTrades(completedRun.runId),
      ]);
      const result = backtestApiToResult(completedRun, metricsResult.items || [], equityResult.items || [], tradesResult.items || [], priceSource);
      setRunId(completedRun.runId);
      setBacktestResult(result);
      setSelectedTradeId(result.trades[0]?.id ?? null);
      if (!nextRows.frontendRows.length && !nextRows.blockRows.length) setError('');
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : 'Quant API unavailable');
      setBacktestResult(buildBacktestResult(renderedPrices, priceSource, timeframe, runId + 1));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refreshQuantRows().catch(() => {
      setError('');
    });
  }, []);

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
      JSON.stringify({ market: MARKET_INFO, priceSource, timeframe, result: backtestResult }, null, 2),
      'application/json;charset=utf-8',
    );
  };

  return (
    <div className="qtv-shell">
      <WorkspaceHeader
        marketSlug={marketSlug}
        timeframe={timeframe}
        priceSource={priceSource}
        loading={loading}
        onMarketSlugChange={setMarketSlug}
        onTimeframeChange={setTimeframe}
        onPriceSourceChange={setPriceSource}
        onRunBacktest={() => void runBacktest()}
        onExport={exportBacktest}
      />

      {error ? <div className="qtv-error">{error}</div> : null}

      <main className="qtv-workspace">
        <PriceChartPanel
          prices={renderedPrices}
          market={MARKET_INFO}
          selectedTradeId={selectedTradeId}
          signals={strategySignals}
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
        <span>build runs {runs.length}</span>
        <span>UTC+0</span>
        <span>%</span>
        <span>log</span>
        <span>auto</span>
      </div>
    </div>
  );
}
