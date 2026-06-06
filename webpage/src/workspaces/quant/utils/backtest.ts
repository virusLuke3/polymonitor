import type {
  BacktestResult,
  CandlePoint,
  EquityPoint,
  PerformanceRow,
  PricePoint,
  PriceSource,
  PropertyGroup,
  Trade,
} from '../types';
import { MARKET_INFO, MOCK_PRICES, MOCK_TRADES } from '../data/mockBacktestData';
import { fmtCurrency, fmtPercent, statusClass } from './formatters';

export function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

export function movingAverage(values: number[], windowSize: number) {
  return values.map((_, index) => {
    const start = Math.max(0, index - windowSize + 1);
    const slice = values.slice(start, index + 1);
    return slice.reduce((sum, value) => sum + value, 0) / slice.length;
  });
}

export function toCandles(points: PricePoint[]): CandlePoint[] {
  return points.map((point, index) => {
    const previous = points[index - 1]?.close ?? point.close - 0.004;
    const pulse = Math.sin(index * 1.9) * 0.011;
    const open = clamp(previous + pulse, 0.01, 0.99);
    const high = Math.min(0.99, Math.max(open, point.close) + 0.014 + Math.abs(Math.sin(index / 3)) * 0.012);
    const low = Math.max(0.01, Math.min(open, point.close) - 0.014 - Math.abs(Math.cos(index / 5)) * 0.01);
    return { ...point, open, high, low };
  });
}

export function scaleFactory(width: number, height: number, padding: { left: number; right: number; top: number; bottom: number }, xMin: number, xMax: number, yMin: number, yMax: number) {
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;
  const xSpan = Math.max(1, xMax - xMin);
  const ySpan = Math.max(0.001, yMax - yMin);
  return {
    x: (value: number) => padding.left + ((value - xMin) / xSpan) * plotW,
    y: (value: number) => padding.top + (1 - (value - yMin) / ySpan) * plotH,
    plotW,
    plotH,
  };
}

export function buildPath(points: Array<{ x: number; y: number }>, width: number, height: number, padding: number, yMin: number, yMax: number) {
  const xMin = Math.min(...points.map((point) => point.x), 0);
  const xMax = Math.max(...points.map((point) => point.x), 1);
  const xSpan = Math.max(1, xMax - xMin);
  const ySpan = Math.max(0.001, yMax - yMin);
  return points.map((point, index) => {
    const x = padding + ((point.x - xMin) / xSpan) * (width - padding * 2);
    const y = height - padding - ((point.y - yMin) / ySpan) * (height - padding * 2);
    return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(' ');
}

function normalizePrices(prices: PricePoint[]) {
  return prices.length >= 20 ? prices.slice(-160) : MOCK_PRICES;
}

function buildTrades(prices: PricePoint[], runId: number): Trade[] {
  const points = normalizePrices(prices);
  const step = Math.max(8, Math.floor(points.length / 5));
  return MOCK_TRADES.map((trade, index) => {
    const entry = points[Math.min(points.length - 1, 10 + index * step)] ?? points[0] ?? MOCK_PRICES[0];
    const exit = points[Math.min(points.length - 1, 20 + index * step)] ?? entry;
    const direction = trade.side === 'LONG' ? 1 : -1;
    const priceMove = ((exit?.close ?? trade.exitPrice) - (entry?.close ?? trade.entryPrice)) * direction;
    const size = trade.size + runId * 7 + index * 3;
    const pnl = Number((priceMove * size + trade.pnl * 0.55).toFixed(2));
    const entryPrice = entry?.close ?? trade.entryPrice;
    const notional = Number((entryPrice * size).toFixed(2));
    return {
      ...trade,
      entryPrice,
      exitPrice: exit?.close ?? trade.exitPrice,
      size,
      notional,
      pnl,
      pnlPct: notional ? Number(((pnl / notional) * 100).toFixed(2)) : trade.pnlPct,
      holdingBars: trade.holdingBars + (runId % 3),
      holdingTime: `${Math.max(35, trade.holdingBars * 5 + runId * 3)}m`,
    };
  });
}

function buildEquity(trades: Trade[], prices: PricePoint[]): EquityPoint[] {
  const points = normalizePrices(prices);
  const realized = trades.reduce((sum, trade) => sum + trade.pnl, 0);
  let peak = 100_000;
  return points.map((point, index) => {
    const trend = (index / Math.max(1, points.length - 1)) * realized * 4;
    const noise = Math.sin(index / 7) * 920 + Math.cos(index / 17) * 380;
    const shock = index > points.length * 0.52 && index < points.length * 0.7 ? -2200 * Math.sin((index - points.length * 0.52) / 9) : 0;
    const equity = 100_000 + trend + noise + shock;
    peak = Math.max(peak, equity);
    const drawdown = Math.min(0, equity - peak);
    return {
      timestamp: point.timestamp,
      index: index + 1,
      equity,
      drawdown,
      drawdownPct: peak ? (drawdown / peak) * 100 : 0,
      cumulativeReturn: ((equity - 100_000) / 100_000) * 100,
    };
  });
}

function performanceRows(trades: Trade[], equity: EquityPoint[]): PerformanceRow[] {
  const net = trades.reduce((sum, trade) => sum + trade.pnl, 0);
  const grossProfit = trades.filter((trade) => trade.pnl > 0).reduce((sum, trade) => sum + trade.pnl, 0);
  const grossLoss = trades.filter((trade) => trade.pnl < 0).reduce((sum, trade) => sum + trade.pnl, 0);
  const maxDrawdown = Math.min(...equity.map((point) => point.drawdown), 0);
  const winners = trades.filter((trade) => trade.pnl > 0).length;
  const yes = trades.filter((trade) => trade.outcome === 'YES');
  const no = trades.filter((trade) => trade.outcome === 'NO');
  const avgBars = trades.reduce((sum, trade) => sum + trade.holdingBars, 0) / Math.max(1, trades.length);
  return [
    { metric: 'Net Profit', all: fmtCurrency(net), long: fmtCurrency(yes.reduce((sum, trade) => sum + trade.pnl, 0)), short: fmtCurrency(no.reduce((sum, trade) => sum + trade.pnl, 0)), description: 'Closed and realized strategy return' },
    { metric: 'Gross Profit', all: fmtCurrency(grossProfit), long: fmtCurrency(yes.filter((trade) => trade.pnl > 0).reduce((sum, trade) => sum + trade.pnl, 0)), short: fmtCurrency(no.filter((trade) => trade.pnl > 0).reduce((sum, trade) => sum + trade.pnl, 0)), description: 'Sum of profitable trades' },
    { metric: 'Gross Loss', all: fmtCurrency(grossLoss), long: fmtCurrency(yes.filter((trade) => trade.pnl < 0).reduce((sum, trade) => sum + trade.pnl, 0)), short: fmtCurrency(no.filter((trade) => trade.pnl < 0).reduce((sum, trade) => sum + trade.pnl, 0)), description: 'Sum of losing trades' },
    { metric: 'Max Drawdown', all: fmtCurrency(maxDrawdown), long: '-2,980.10', short: '-774.42', description: 'Largest equity peak-to-trough loss' },
    { metric: 'Buy & Hold Return', all: '+2.93%', long: '+2.93%', short: '-', description: 'Passive YES token return' },
    { metric: 'Sharpe Ratio', all: '1.41', long: '1.55', short: '0.92', description: 'Risk-adjusted return' },
    { metric: 'Sortino Ratio', all: '1.78', long: '1.93', short: '1.04', description: 'Downside-risk adjusted return' },
    { metric: 'Profit Factor', all: grossLoss ? Math.abs(grossProfit / grossLoss).toFixed(3) : '0.000', long: '1.31', short: '1.08', description: 'Gross profit divided by gross loss' },
    { metric: 'Total Closed Trades', all: String(trades.length), long: String(yes.length), short: String(no.length), description: 'Closed simulated trades' },
    { metric: 'Percent Profitable', all: `${((winners / Math.max(1, trades.length)) * 100).toFixed(2)}%`, long: '39.10%', short: '30.20%', description: 'Winning closed trades share' },
    { metric: 'Avg Bars in Trades', all: avgBars.toFixed(1), long: '5', short: '4', description: 'Average holding period in chart bars' },
  ];
}

function propertyGroups(priceSource: PriceSource, timeframe: string): PropertyGroup[] {
  return [
    {
      title: 'Market Info',
      rows: [
        { label: 'condition id', value: MARKET_INFO.conditionId },
        { label: 'yes token id', value: MARKET_INFO.yesTokenId },
        { label: 'no token id', value: MARKET_INFO.noTokenId },
        { label: 'start time', value: MARKET_INFO.startTime },
        { label: 'end time', value: MARKET_INFO.endTime },
        { label: 'resolution', value: MARKET_INFO.resolutionTime },
        { label: 'resolved', value: MARKET_INFO.resolvedOutcome },
        { label: 'liquidity', value: MARKET_INFO.liquidity },
        { label: 'volume', value: MARKET_INFO.volume },
      ],
    },
    {
      title: 'Strategy Parameters',
      rows: [
        { label: 'entry threshold', value: '0.58' },
        { label: 'exit threshold', value: '0.44' },
        { label: 'stop loss', value: '7.5%' },
        { label: 'take profit', value: '16%' },
        { label: 'max hold', value: '8h' },
        { label: 'position sizing', value: 'risk-weighted' },
        { label: 'max position', value: '550 shares / market' },
      ],
    },
    {
      title: 'Backtest Assumptions',
      rows: [
        { label: 'initial capital', value: '100,000 USDC' },
        { label: 'commission', value: '0.00%' },
        { label: 'slippage', value: '0.4%' },
        { label: 'fill model', value: 'block close' },
        { label: 'price source', value: priceSource },
        { label: 'timeframe', value: timeframe },
        { label: 'missing prices', value: 'forward fill' },
      ],
    },
  ];
}

export function buildBacktestResult(prices: PricePoint[], priceSource: PriceSource, timeframe: string, runId: number): BacktestResult {
  const trades = buildTrades(prices, runId);
  const equity = buildEquity(trades, prices);
  const net = trades.reduce((sum, trade) => sum + trade.pnl, 0);
  const winners = trades.filter((trade) => trade.pnl > 0).length;
  const maxDrawdown = Math.min(...equity.map((point) => point.drawdown), 0);
  const avgTrade = net / Math.max(1, trades.length);
  const grossProfit = trades.filter((trade) => trade.pnl > 0).reduce((sum, trade) => sum + trade.pnl, 0);
  const grossLoss = Math.abs(trades.filter((trade) => trade.pnl < 0).reduce((sum, trade) => sum + trade.pnl, 0));
  const resolvedPnl = net * 0.72;
  const unrealizedPnl = net - resolvedPnl;
  const fillCoverage = prices.length >= 20 ? 98.4 : 74.6;
  return {
    runId,
    generatedAt: new Date().toISOString(),
    trades,
    equity,
    performanceRows: performanceRows(trades, equity),
    propertyGroups: propertyGroups(priceSource, timeframe),
    metrics: [
      { name: 'Net Profit', value: net, formattedValue: fmtCurrency(net), delta: fmtPercent(net / 1000), status: statusClass(net), tooltip: 'Closed realized strategy PnL' },
      { name: 'Total Return', value: net / 1000, formattedValue: fmtPercent(net / 1000), delta: '+0.42 beta adj', status: statusClass(net), tooltip: 'Return on initial capital' },
      { name: 'Max Drawdown', value: maxDrawdown, formattedValue: fmtCurrency(maxDrawdown), delta: fmtPercent(maxDrawdown / 1000), status: 'negative', tooltip: 'Largest peak-to-trough equity loss' },
      { name: 'Win Rate', value: winners / Math.max(1, trades.length), formattedValue: `${((winners / Math.max(1, trades.length)) * 100).toFixed(2)}%`, delta: `${winners} / ${trades.length}`, status: 'positive', tooltip: 'Percent profitable closed trades' },
      { name: 'Profit Factor', value: grossLoss ? grossProfit / grossLoss : 0, formattedValue: grossLoss ? (grossProfit / grossLoss).toFixed(3) : '0.000', delta: 'gross P/L', status: 'neutral', tooltip: 'Gross profit divided by gross loss' },
      { name: 'Total Trades', value: trades.length, formattedValue: String(trades.length), delta: `run #${runId}`, status: 'neutral', tooltip: 'Closed strategy trades' },
      { name: 'Avg Trade', value: avgTrade, formattedValue: fmtCurrency(avgTrade), delta: fmtPercent(avgTrade / 1000), status: statusClass(avgTrade), tooltip: 'Average closed trade PnL' },
      { name: 'Avg Holding', value: trades.reduce((sum, trade) => sum + trade.holdingBars, 0) / Math.max(1, trades.length), formattedValue: `${(trades.reduce((sum, trade) => sum + trade.holdingBars, 0) / Math.max(1, trades.length)).toFixed(1)} bars`, delta: timeframe, status: 'neutral', tooltip: 'Average bars held per trade' },
    ],
    predictionMetrics: [
      { name: 'Resolved PnL', value: resolvedPnl, formattedValue: fmtCurrency(resolvedPnl), delta: 'settled markets', status: statusClass(resolvedPnl), tooltip: 'PnL from markets with final outcome available' },
      { name: 'Unrealized PnL', value: unrealizedPnl, formattedValue: fmtCurrency(unrealizedPnl), delta: 'open/pending', status: statusClass(unrealizedPnl), tooltip: 'Mark-to-market PnL for unresolved exposure' },
      { name: 'Settlement PnL', value: net * 0.18, formattedValue: fmtCurrency(net * 0.18), delta: MARKET_INFO.resolvedOutcome, status: statusClass(net), tooltip: 'PnL attributable to market resolution payoff' },
      { name: 'Slippage Cost', value: -Math.abs(net) * 0.036, formattedValue: fmtCurrency(-Math.abs(net) * 0.036), delta: '0.4% model', status: 'negative', tooltip: 'Estimated execution cost from fill assumptions' },
      { name: 'Stale Price Ratio', value: 0.021, formattedValue: '2.10%', delta: '1m gaps', status: 'neutral', tooltip: 'Share of bars using stale/forward-filled prices' },
      { name: 'Fill Coverage', value: fillCoverage, formattedValue: `${fillCoverage.toFixed(1)}%`, delta: priceSource, status: fillCoverage > 90 ? 'positive' : 'negative', tooltip: 'Percent of simulated orders with usable fill prices' },
      { name: 'Avg Time to Resolution', value: 7.4, formattedValue: '7.4h', delta: 'weighted', status: 'neutral', tooltip: 'Average time between last trade and resolution' },
      { name: 'Late Trade Ratio', value: 0.064, formattedValue: '6.40%', delta: '<2h to end', status: 'negative', tooltip: 'Trades entered near event end or resolution window' },
      { name: 'Market Count', value: 18, formattedValue: '18', delta: MARKET_INFO.category, status: 'neutral', tooltip: 'Distinct markets in this backtest run' },
      { name: 'Category PnL', value: net * 0.61, formattedValue: fmtCurrency(net * 0.61), delta: MARKET_INFO.category, status: statusClass(net), tooltip: 'PnL contribution from selected market category' },
    ],
  };
}
