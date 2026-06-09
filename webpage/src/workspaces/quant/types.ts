import type { QuantBlockClosePoint, QuantFrontendPricePoint } from '@/types';

export type TesterTab = 'overview' | 'parameters' | 'performance' | 'trades' | 'equity' | 'drawdown' | 'runs' | 'logs' | 'properties';
export type PriceSource = 'frontend' | 'orderfilled' | 'orderbook' | 'conservative';
export type BacktestEngine = 'builtin' | 'backtrader' | 'nautilus_trader';
export type DataStatus = 'idle' | 'loading' | 'metadata_loading' | 'price_loading' | 'partial' | 'ready' | 'empty' | 'error';
export type MetricStatus = 'positive' | 'negative' | 'neutral';
export type TradeFilter = 'profitable' | 'losing' | 'yes' | 'no' | 'longHolding' | 'shortHolding';
export type PerformanceSortKey = 'metric' | 'all' | 'long' | 'short' | 'description';
export type SortDirection = 'asc' | 'desc';

export type MarketInfo = {
  id: string;
  conditionId: string;
  title: string;
  category: string;
  slug: string;
  startTime: string;
  endTime: string;
  resolutionTime: string;
  resolvedOutcome: 'YES' | 'NO' | 'PENDING';
  yesTokenId: string;
  noTokenId: string;
  liquidity: string;
  volume: string;
};

export type PricePoint = {
  timestamp: number;
  close: number;
  volume: number;
  source: string;
  tokenId?: string;
  tokenSide?: string;
  outcomeLabel?: string;
  outcomeShortLabel?: string;
  outcomeFullLabel?: string;
  outcomeKey?: string;
  yesPrice?: number;
  noPrice?: number;
  yesPriceKind?: 'direct' | 'implied';
  noPriceKind?: 'direct' | 'implied';
  ma?: number;
  qualityFlags?: string[];
  isCarriedForward?: boolean;
  isInterpolated?: boolean;
};

export type CandlePoint = PricePoint & {
  open: number;
  high: number;
  low: number;
};

export type Signal = {
  id: string;
  timestamp: number;
  action: 'OPEN' | 'CLOSE' | 'BUY' | 'SELL';
  outcome: string;
  price: number;
  size: number;
  notional: number;
  reason: string;
  tradeId: string;
};

export type Trade = {
  id: string;
  entryTime: string;
  exitTime: string;
  entryX?: number;
  exitX?: number;
  xAxis?: string;
  marketId: string;
  market: string;
  outcome: string;
  side: 'LONG' | 'SHORT';
  entryPrice: number;
  exitPrice: number;
  size: number;
  notional: number;
  pnl: number;
  pnlPct: number;
  holdingTime: string;
  holdingBars: number;
  exitReason: string;
};

export type BacktestMetric = {
  name: string;
  value: number;
  formattedValue: string;
  delta: string;
  status: MetricStatus;
  tooltip: string;
};

export type EquityPoint = {
  timestamp: number;
  index: number;
  equity: number;
  drawdown: number;
  drawdownPct: number;
  cumulativeReturn: number;
};

export type PerformanceRow = {
  metric: string;
  all: string;
  long: string;
  short: string;
  description: string;
};

export type PropertyGroup = {
  title: string;
  rows: Array<{ label: string; value: string }>;
};

export type BacktestResult = {
  runId: number;
  generatedAt: string;
  metrics: BacktestMetric[];
  equity: EquityPoint[];
  trades: Trade[];
  performanceRows: PerformanceRow[];
  propertyGroups: PropertyGroup[];
  predictionMetrics: BacktestMetric[];
};

export type QuantRows = {
  frontendRows: QuantFrontendPricePoint[];
  blockRows: QuantBlockClosePoint[];
};
