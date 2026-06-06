import type {
  QuantBacktestEquityPoint,
  QuantBacktestMetric,
  QuantBacktestRun,
  QuantBacktestTrade,
  QuantBlockClosePoint,
  QuantFrontendPricePoint,
} from '@/types';
import type { BacktestMetric, BacktestResult, EquityPoint, PerformanceRow, PricePoint, PriceSource, PropertyGroup, Trade } from '../types';
import { MARKET_INFO } from '../data/mockBacktestData';
import { toNumber } from './formatters';

export function frontendToPrices(rows: QuantFrontendPricePoint[]): PricePoint[] {
  return rows.map((row) => ({
    timestamp: Number(row.timestamp),
    close: toNumber(row.price),
    volume: 0,
    source: 'frontend',
  })).filter((row) => row.timestamp && row.close);
}

export function blockToPrices(rows: QuantBlockClosePoint[]): PricePoint[] {
  return rows.map((row) => ({
    timestamp: Number(row.blockNumber),
    close: toNumber(row.closePrice),
    volume: toNumber(row.volume),
    source: 'orderfilled_block_close',
  })).filter((row) => row.timestamp && row.close);
}

function formatAxisValue(value: unknown, axis: string) {
  const numeric = Number(value);
  if (axis === 'block_number') return `block ${Number.isFinite(numeric) ? numeric.toLocaleString('en-US') : value}`;
  if (!Number.isFinite(numeric)) return String(value ?? '');
  return new Date(numeric * 1000).toISOString().slice(0, 16).replace('T', ' ');
}

function metricStatus(value: unknown): BacktestMetric['status'] {
  return value === 'positive' || value === 'negative' || value === 'neutral' ? value : 'neutral';
}

function metricToCard(row: QuantBacktestMetric): BacktestMetric {
  return {
    name: row.metricName,
    value: toNumber(row.value),
    formattedValue: row.formattedValue || String(row.value ?? ''),
    delta: row.delta || '',
    status: metricStatus(row.status),
    tooltip: row.tooltip || row.metricName,
  };
}

function tradeToUi(row: QuantBacktestTrade): Trade {
  const xAxis = row.xAxis || 'timestamp';
  return {
    id: row.tradeId,
    entryTime: formatAxisValue(row.entryX, xAxis),
    exitTime: formatAxisValue(row.exitX, xAxis),
    entryX: Number(row.entryX),
    exitX: Number(row.exitX),
    xAxis,
    marketId: row.marketSlug,
    market: row.marketSlug,
    outcome: row.tokenSide === 'NO' ? 'NO' : 'YES',
    side: row.side === 'SHORT' ? 'SHORT' : 'LONG',
    entryPrice: toNumber(row.entryPrice),
    exitPrice: toNumber(row.exitPrice),
    size: toNumber(row.size),
    notional: toNumber(row.notional),
    pnl: toNumber(row.pnl),
    pnlPct: toNumber(row.pnlPct),
    holdingBars: toNumber(row.holdingBars),
    holdingTime: `${toNumber(row.holdingBars)} bars`,
    exitReason: row.exitReason,
  };
}

function equityToUi(row: QuantBacktestEquityPoint): EquityPoint {
  return {
    timestamp: Number(row.xValue),
    index: Number(row.pointIndex),
    equity: toNumber(row.equity),
    drawdown: toNumber(row.drawdown),
    drawdownPct: toNumber(row.drawdownPct),
    cumulativeReturn: toNumber(row.cumulativeReturn),
  };
}

function performanceRows(metrics: QuantBacktestMetric[], trades: Trade[]): PerformanceRow[] {
  const yesTrades = trades.filter((trade) => trade.outcome === 'YES');
  const noTrades = trades.filter((trade) => trade.outcome === 'NO');
  return metrics.map((metric) => ({
    metric: metric.metricName,
    all: metric.formattedValue || String(metric.value ?? ''),
    long: metric.metricKey === 'total_trades' ? String(yesTrades.length) : '',
    short: metric.metricKey === 'total_trades' ? String(noTrades.length) : '',
    description: metric.tooltip || metric.metricName,
  }));
}

function propertyGroups(run: QuantBacktestRun, priceSource: PriceSource): PropertyGroup[] {
  return [
    {
      title: 'Market Info',
      rows: [
        { label: 'market slug', value: run.marketSlug },
        { label: 'token side', value: run.tokenSide },
        { label: 'source', value: run.priceSource },
        { label: 'condition id', value: MARKET_INFO.conditionId },
        { label: 'resolution', value: MARKET_INFO.resolutionTime },
        { label: 'resolved', value: MARKET_INFO.resolvedOutcome },
      ],
    },
    {
      title: 'Strategy Parameters',
      rows: [
        { label: 'entry threshold', value: String(run.entryThreshold ?? '0.58') },
        { label: 'exit threshold', value: String(run.exitThreshold ?? '0.44') },
        { label: 'stop loss', value: String(run.stopLoss ?? '0.075') },
        { label: 'take profit', value: String(run.takeProfit ?? '0.16') },
        { label: 'max hold', value: `${run.maxHoldingBars ?? 96} bars` },
        { label: 'position size', value: `${run.positionSize ?? 100} shares` },
      ],
    },
    {
      title: 'Backtest Assumptions',
      rows: [
        { label: 'initial capital', value: `${run.initialCapital ?? 100000} USDC` },
        { label: 'price source', value: priceSource },
        { label: 'run status', value: run.status },
        { label: 'rows processed', value: String(run.rowsProcessed ?? 0) },
      ],
    },
  ];
}

export function backtestApiToResult(
  run: QuantBacktestRun,
  metrics: QuantBacktestMetric[],
  equity: QuantBacktestEquityPoint[],
  trades: QuantBacktestTrade[],
  priceSource: PriceSource,
): BacktestResult {
  const overviewMetrics = metrics.filter((metric) => metric.metricGroup !== 'prediction').map(metricToCard);
  const predictionMetrics = metrics.filter((metric) => metric.metricGroup === 'prediction').map(metricToCard);
  const uiTrades = trades.map(tradeToUi);
  const uiEquity = equity.map(equityToUi);
  return {
    runId: run.runId,
    generatedAt: run.finishedAt || run.startedAt || new Date().toISOString(),
    metrics: overviewMetrics,
    equity: uiEquity,
    trades: uiTrades,
    performanceRows: performanceRows(metrics, uiTrades),
    propertyGroups: propertyGroups(run, priceSource),
    predictionMetrics,
  };
}
