import type {
  QuantBacktestEquityPoint,
  QuantBacktestMetric,
  QuantBacktestRun,
  QuantBacktestTrade,
  QuantBlockClosePoint,
  QuantFrontendPricePoint,
  QuantMarketSeriesPayload,
  QuantMarketSeriesPoint,
} from '@/types';
import type { BacktestMetric, BacktestResult, EquityPoint, PerformanceRow, PricePoint, PriceSource, PropertyGroup, Trade } from '../types';
import { deriveEventOutcomeLabel, toNumber } from './formatters';

export function frontendToPrices(rows: QuantFrontendPricePoint[]): PricePoint[] {
  return rows.map((row) => ({
    timestamp: Number(row.timestamp),
    close: toNumber(row.price),
    volume: 0,
    source: 'frontend',
  })).filter((row) => row.timestamp && Number.isFinite(row.close));
}

export function blockToPrices(rows: QuantBlockClosePoint[]): PricePoint[] {
  return rows.map((row) => ({
    timestamp: Number(row.blockNumber),
    close: toNumber(row.closePrice ?? row.yesProbabilityClose),
    volume: toNumber(row.volume),
    tokenSide: row.tokenSide,
    source: 'orderfilled_block_close',
  })).filter((row) => row.timestamp && Number.isFinite(row.close));
}

export function marketSeriesToPrices(payload: QuantMarketSeriesPayload | null | undefined): PricePoint[] {
  if (!payload) return [];
  const source = payload.event?.source || payload.market?.source || 'quant_market_series';
  const eventTitle = payload.event?.eventTitle || payload.market?.marketTitle || '';
  const rawOutcomes = payload.outcomes || [];
  const canonicalKeys = new Set(
    rawOutcomes
      .filter((outcome) => String(outcome.buyYesTokenSide || outcome.tokenSide || '').toUpperCase() === 'YES')
      .map((outcome) => `${outcome.marketId || outcome.marketSlug || outcome.outcomeKey || outcome.outcomeLabel}`),
  );
  const canonicalOutcomes = rawOutcomes.filter((outcome) => {
    const side = String(outcome.buyYesTokenSide || outcome.tokenSide || '').toUpperCase();
    const key = `${outcome.marketId || outcome.marketSlug || outcome.outcomeKey || outcome.outcomeLabel}`;
    return side !== 'NO' || !canonicalKeys.has(key);
  });

  const canonicalYes = (point: QuantMarketSeriesPoint, fallbackSide?: string | null) => {
    const direct = toNumber(point.yesProbabilityClose);
    if (Number.isFinite(direct) && direct >= 0 && direct <= 1) return direct;
    const raw = toNumber(point.price);
    const side = String(point.tokenSide || fallbackSide || '').toUpperCase();
    return side === 'NO' ? Math.max(0, Math.min(1, 1 - raw)) : raw;
  };
  const directTokenPrice = (point: QuantMarketSeriesPoint) => toNumber(point.price);

  return canonicalOutcomes.flatMap((outcome) => (
    (() => {
      const fullLabel = outcome.marketTitle || outcome.outcomeLabel || outcome.marketSlug || 'Outcome';
      const shortLabel = deriveEventOutcomeLabel(eventTitle, fullLabel, outcome.outcomeLabel);
      const outcomeKey = outcome.outcomeKey || `${outcome.marketSlug || outcome.marketId || shortLabel}`;
      const complementByX = new Map<string, number>();
      (outcome.complementPoints || []).forEach((point) => {
        const x = String(point.x ?? point.blockNumber ?? point.timestamp ?? '');
        if (x) complementByX.set(x, directTokenPrice(point));
      });
      const yesRows = (outcome.points || []).map((point) => {
        const x = String(point.x ?? point.blockNumber ?? point.timestamp ?? '');
        const yesPrice = canonicalYes(point, outcome.buyYesTokenSide || outcome.tokenSide);
        const directNo = complementByX.get(x);
        const hasDirectNo = typeof directNo === 'number' && Number.isFinite(directNo);
        const noPrice = hasDirectNo ? directNo : Math.max(0, Math.min(1, 1 - yesPrice));
        return {
          timestamp: Number(point.x ?? point.blockNumber ?? point.timestamp),
          close: yesPrice,
          volume: toNumber(point.volume),
          source,
          tokenId: outcome.buyYesTokenId || outcome.tokenId,
          tokenSide: outcome.buyYesTokenSide || 'YES',
          outcomeLabel: shortLabel,
          outcomeShortLabel: shortLabel,
          outcomeFullLabel: fullLabel,
          outcomeKey: `${outcomeKey}:YES`,
          yesPrice,
          noPrice,
          yesPriceKind: 'direct' as const,
          noPriceKind: hasDirectNo ? 'direct' as const : 'implied' as const,
        };
      });
      const noRows = (outcome.complementPoints || [])
        .filter((point) => !point.isImplied)
        .map((point) => {
          const noPrice = directTokenPrice(point);
          return {
            timestamp: Number(point.x ?? point.blockNumber ?? point.timestamp),
            close: noPrice,
            volume: toNumber(point.volume),
            source,
            tokenId: outcome.buyNoTokenId || point.tokenId || undefined,
            tokenSide: outcome.buyNoTokenSide || 'NO',
            outcomeLabel: deriveEventOutcomeLabel(eventTitle, outcome.buyNoLabel || '', outcome.buyNoLabel || `${shortLabel} No`),
            outcomeShortLabel: deriveEventOutcomeLabel(eventTitle, outcome.buyNoLabel || '', outcome.buyNoLabel || `${shortLabel} No`),
            outcomeFullLabel: outcome.buyNoLabel || fullLabel,
            outcomeKey: `${outcomeKey}:NO`,
            yesPrice: Math.max(0, Math.min(1, 1 - noPrice)),
            noPrice,
            yesPriceKind: 'implied' as const,
            noPriceKind: 'direct' as const,
          };
        });
      return [...yesRows, ...noRows];
    })()
  )).filter((row) => row.timestamp && Number.isFinite(row.close));
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

function runOutcomeLabel(run: QuantBacktestRun) {
  const meta = run.meta || {};
  const label = typeof meta.outcome_label === 'string' ? meta.outcome_label : typeof meta.outcomeLabel === 'string' ? meta.outcomeLabel : '';
  return label.trim();
}

function tradeToUi(row: QuantBacktestTrade, run: QuantBacktestRun): Trade {
  const xAxis = row.xAxis || 'timestamp';
  const outcomeLabel = runOutcomeLabel(run);
  return {
    id: row.tradeId,
    entryTime: formatAxisValue(row.entryX, xAxis),
    exitTime: formatAxisValue(row.exitX, xAxis),
    entryX: Number(row.entryX),
    exitX: Number(row.exitX),
    xAxis,
    marketId: row.marketSlug,
    market: row.marketSlug,
    outcome: outcomeLabel || (row.tokenSide === 'NO' ? 'NO' : 'YES'),
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
  const meta = run.meta || {};
  return [
    {
      title: 'Market Info',
      rows: [
        { label: 'market slug', value: run.marketSlug },
        { label: 'token side', value: run.tokenSide },
        { label: 'outcome', value: runOutcomeLabel(run) || run.tokenSide },
        { label: 'token id', value: typeof meta.token_id === 'string' ? meta.token_id : '-' },
        { label: 'source', value: run.priceSource },
        { label: 'engine', value: run.backtestEngine || 'builtin' },
        { label: 'from block', value: String(run.fromBlock ?? '-') },
        { label: 'to block', value: String(run.toBlock ?? '-') },
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
  const uiTrades = trades.map((trade) => tradeToUi(trade, run));
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

export function emptyBacktestResult(): BacktestResult {
  return {
    runId: 0,
    generatedAt: '',
    metrics: [],
    equity: [],
    trades: [],
    performanceRows: [],
    propertyGroups: [
      {
        title: 'Backtest',
        rows: [
          { label: 'status', value: 'No completed run' },
          { label: 'data', value: 'Select a market and run a backtest' },
        ],
      },
    ],
    predictionMetrics: [],
  };
}
