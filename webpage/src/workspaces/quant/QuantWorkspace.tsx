import { useEffect, useMemo, useState } from 'preact/hooks';
import {
  fetchQuantBlockClosePrices,
  fetchQuantBuildStatus,
  fetchQuantFrontendPrices,
  type QuantPriceQuery,
} from '@/services/api';
import type { QuantBlockClosePoint, QuantBuildRun, QuantFrontendPricePoint } from '@/types';

type TesterTab = 'overview' | 'performance' | 'trades' | 'properties';
type PriceSource = 'frontend' | 'orderfilled' | 'orderbook' | 'conservative';

type BacktestPricePoint = {
  timestamp: number;
  close: number;
  volume: number;
  source: string;
};

type CandlePoint = BacktestPricePoint & {
  open: number;
  high: number;
  low: number;
};

type BacktestSignal = {
  id: string;
  timestamp: number;
  action: 'OPEN' | 'CLOSE' | 'BUY' | 'SELL';
  outcome: 'YES' | 'NO';
  price: number;
  size: number;
  notional: number;
  reason: string;
  tradeId: string;
};

type BacktestTrade = {
  id: string;
  entryTime: string;
  exitTime: string;
  market: string;
  outcome: 'YES' | 'NO';
  side: 'LONG' | 'SHORT';
  entryPrice: number;
  exitPrice: number;
  size: number;
  notional: number;
  pnl: number;
  pnlPct: number;
  holdingTime: string;
  exitReason: string;
};

type EquityPoint = {
  index: number;
  equity: number;
  drawdown: number;
  drawdownPct: number;
};

const MOCK_PRICES: BacktestPricePoint[] = Array.from({ length: 128 }, (_, index) => {
  const wave = Math.sin(index / 6) * 0.044 + Math.cos(index / 17) * 0.021;
  const breakout = index > 32 && index < 55 ? (index - 32) * 0.0032 : 0;
  const selloff = index > 76 && index < 92 ? -0.12 + (index - 76) * 0.004 : 0;
  const recovery = index > 99 ? (index - 99) * 0.0028 : 0;
  return {
    timestamp: 1_717_584_000 + index * 300,
    close: Math.max(0.04, Math.min(0.96, 0.49 + wave + breakout + selloff + recovery)),
    volume: 900 + Math.round(Math.abs(Math.sin(index / 4.5)) * 5800 + (index % 9) * 190),
    source: 'mock',
  };
});

function mockTs(index: number) {
  return MOCK_PRICES[index]?.timestamp || MOCK_PRICES[0]?.timestamp || 0;
}

const MOCK_SIGNALS: BacktestSignal[] = [
  { id: 's1', timestamp: mockTs(17), action: 'OPEN', outcome: 'YES', price: 0.48, size: 240, notional: 115.2, reason: 'Momentum breakout', tradeId: 'T-118' },
  { id: 's2', timestamp: mockTs(33), action: 'CLOSE', outcome: 'YES', price: 0.57, size: 240, notional: 136.8, reason: 'Target reached', tradeId: 'T-118' },
  { id: 's3', timestamp: mockTs(56), action: 'SELL', outcome: 'NO', price: 0.62, size: 180, notional: 111.6, reason: 'Breakdown confirmation', tradeId: 'T-119' },
  { id: 's4', timestamp: mockTs(73), action: 'CLOSE', outcome: 'NO', price: 0.54, size: 180, notional: 97.2, reason: 'Trailing stop', tradeId: 'T-119' },
  { id: 's5', timestamp: mockTs(91), action: 'OPEN', outcome: 'YES', price: 0.51, size: 320, notional: 163.2, reason: 'Mean reversion', tradeId: 'T-120' },
  { id: 's6', timestamp: mockTs(112), action: 'CLOSE', outcome: 'YES', price: 0.59, size: 320, notional: 188.8, reason: 'Resolution risk trim', tradeId: 'T-120' },
];

const MOCK_TRADES: BacktestTrade[] = [
  { id: 'T-118', entryTime: '2026-06-05 12:31', exitTime: '2026-06-05 13:36', market: 'Will Team A win?', outcome: 'YES', side: 'LONG', entryPrice: 0.48, exitPrice: 0.57, size: 240, notional: 115.2, pnl: 21.6, pnlPct: 18.75, holdingTime: '1h 05m', exitReason: 'Target reached' },
  { id: 'T-119', entryTime: '2026-06-05 15:26', exitTime: '2026-06-05 16:36', market: 'Will Team A win?', outcome: 'NO', side: 'SHORT', entryPrice: 0.62, exitPrice: 0.54, size: 180, notional: 111.6, pnl: 14.4, pnlPct: 12.9, holdingTime: '1h 10m', exitReason: 'Trailing stop' },
  { id: 'T-120', entryTime: '2026-06-05 17:46', exitTime: '2026-06-05 18:41', market: 'Will Team A win?', outcome: 'YES', side: 'LONG', entryPrice: 0.51, exitPrice: 0.59, size: 320, notional: 163.2, pnl: 25.6, pnlPct: 15.69, holdingTime: '55m', exitReason: 'Resolution risk trim' },
  { id: 'T-121', entryTime: '2026-06-05 19:06', exitTime: '2026-06-05 20:11', market: 'Will Team B qualify?', outcome: 'YES', side: 'LONG', entryPrice: 0.37, exitPrice: 0.33, size: 410, notional: 151.7, pnl: -16.4, pnlPct: -10.81, holdingTime: '1h 05m', exitReason: 'Stop loss' },
];

const MOCK_EQUITY: EquityPoint[] = Array.from({ length: 160 }, (_, index) => {
  const equity = 100_000 + index * 142 + Math.sin(index / 7) * 1180 - (index > 82 && index < 112 ? (112 - Math.abs(index - 97)) * 154 : 0);
  const peak = 100_000 + index * 174 + 900;
  const drawdown = Math.min(0, equity - peak);
  return { index: index + 1, equity, drawdown, drawdownPct: (drawdown / peak) * 100 };
});

const PERFORMANCE_ROWS = [
  ['Net Profit', '+4,782.40 USDC', '+4,128.10', '+654.30', 'Closed and realized strategy return'],
  ['Gross Profit', '7,914.20 USDC', '6,420.90', '1,493.30', 'Sum of profitable trades'],
  ['Gross Loss', '-3,131.80 USDC', '-2,292.80', '-839.00', 'Sum of losing trades'],
  ['Max Drawdown', '-3,754.52 USDC', '-2,980.10', '-774.42', 'Largest equity peak-to-trough loss'],
  ['Buy & Hold Return', '+2.93%', '+2.93%', '-', 'Passive YES token return'],
  ['Sharpe Ratio', '1.41', '1.55', '0.92', 'Risk-adjusted return'],
  ['Sortino Ratio', '1.78', '1.93', '1.04', 'Downside-risk adjusted return'],
  ['Profit Factor', '1.198', '1.31', '1.08', 'Gross profit divided by gross loss'],
  ['Total Closed Trades', '2,470', '1,824', '646', 'Closed simulated trades'],
  ['Percent Profitable', '35.55%', '39.10%', '30.20%', 'Winning closed trades share'],
  ['Avg Bars in Trades', '5', '5', '4', 'Average holding period in chart bars'],
];

const PROPERTY_GROUPS = [
  ['Strategy Parameters', ['Entry threshold 0.58', 'Exit threshold 0.44', 'Stop loss 7.5%', 'Take profit 16%', 'Max holding time 8h', 'Position sizing risk-weighted']],
  ['Backtest Assumptions', ['Initial capital 100,000 USDC', 'Commission 0.00%', 'Slippage 0.4%', 'Fill model block close', 'Time range selected market history']],
  ['Market Data', ['Source frontend / OrderFilled', 'Resolution 1m or block_number', 'Missing prices forward fill', 'Settlement PnL enabled']],
];

const DRAW_TOOLS = ['+', 'T', '/', 'R', 'Fib', 'Br', 'Mag', 'Lock', 'Eye'];

function toNumber(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function fmtPrice(value: unknown) {
  return toNumber(value).toFixed(3);
}

function fmtCurrency(value: unknown) {
  const numeric = toNumber(value);
  const sign = numeric > 0 ? '+' : '';
  return `${sign}${numeric.toLocaleString('en-US', { maximumFractionDigits: 2 })} USDC`;
}

function statusClass(value: number) {
  if (value > 0) return 'positive';
  if (value < 0) return 'negative';
  return 'neutral';
}

function frontendToPrices(rows: QuantFrontendPricePoint[]): BacktestPricePoint[] {
  return rows.map((row) => ({
    timestamp: Number(row.timestamp),
    close: toNumber(row.price),
    volume: 0,
    source: 'frontend',
  })).filter((row) => row.timestamp && row.close);
}

function blockToPrices(rows: QuantBlockClosePoint[]): BacktestPricePoint[] {
  return rows.map((row) => ({
    timestamp: Number(row.blockNumber),
    close: toNumber(row.closePrice),
    volume: toNumber(row.volume),
    source: 'orderfilled_block_close',
  })).filter((row) => row.timestamp && row.close);
}

function movingAverage(values: number[], windowSize: number) {
  return values.map((_, index) => {
    const start = Math.max(0, index - windowSize + 1);
    const slice = values.slice(start, index + 1);
    return slice.reduce((sum, value) => sum + value, 0) / slice.length;
  });
}

function toCandles(points: BacktestPricePoint[]): CandlePoint[] {
  return points.map((point, index) => {
    const previous = points[index - 1]?.close ?? point.close - 0.004;
    const pulse = Math.sin(index * 1.9) * 0.011;
    const open = Math.max(0.01, Math.min(0.99, previous + pulse));
    const high = Math.min(0.99, Math.max(open, point.close) + 0.014 + Math.abs(Math.sin(index / 3)) * 0.012);
    const low = Math.max(0.01, Math.min(open, point.close) - 0.014 - Math.abs(Math.cos(index / 5)) * 0.01);
    return { ...point, open, high, low };
  });
}

function buildPath(points: Array<{ x: number; y: number }>, width: number, height: number, padding: number, yMin: number, yMax: number) {
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

function scaleFactory(width: number, height: number, padding: { left: number; right: number; top: number; bottom: number }, xMin: number, xMax: number, yMin: number, yMax: number) {
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

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function PriceChartPanel({
  prices,
  selectedTradeId,
}: {
  prices: BacktestPricePoint[];
  selectedTradeId: string | null;
}) {
  const width = 1280;
  const height = 560;
  const padding = { left: 18, right: 88, top: 22, bottom: 88 };
  const points = prices.length ? prices.slice(-128) : MOCK_PRICES;
  const candles = toCandles(points);
  const xMin = candles[0]?.timestamp || 0;
  const xMax = candles[candles.length - 1]?.timestamp || 1;
  const scale = scaleFactory(width, height, padding, xMin, xMax, 0, 1);
  const closes = candles.map((point) => point.close);
  const ma = movingAverage(closes, 18);
  const upper = ma.map((value, index) => Math.min(1, value + 0.05 + Math.abs(Math.sin(index / 11)) * 0.014));
  const lower = ma.map((value, index) => Math.max(0, value - 0.05 - Math.abs(Math.cos(index / 13)) * 0.014));
  const maPoints = candles.map((point, index) => ({ x: point.timestamp, y: ma[index] ?? point.close }));
  const upperPoints = candles.map((point, index) => ({ x: point.timestamp, y: upper[index] ?? point.close }));
  const lowerPoints = candles.map((point, index) => ({ x: point.timestamp, y: lower[index] ?? point.close }));
  const toScaledPath = (items: Array<{ x: number; y: number }>) => items.map((point, index) => (
    `${index === 0 ? 'M' : 'L'} ${scale.x(point.x).toFixed(2)} ${scale.y(point.y).toFixed(2)}`
  )).join(' ');
  const upperPath = toScaledPath(upperPoints);
  const lowerPath = toScaledPath(lowerPoints);
  const maPath = toScaledPath(maPoints);
  const lowerBandPath = lowerPoints.slice().reverse().map((point) => `L ${scale.x(point.x).toFixed(2)} ${scale.y(point.y).toFixed(2)}`).join(' ');
  const bandPath = `${upperPath} ${lowerBandPath} Z`;
  const candleStep = scale.plotW / Math.max(1, candles.length - 1);
  const candleW = Math.max(3, Math.min(9, candleStep * 0.58));
  const maxVolume = Math.max(...candles.map((point) => point.volume), 1);
  const fallbackCandle = toCandles(MOCK_PRICES)[0] ?? {
    timestamp: 0,
    open: 0.5,
    high: 0.52,
    low: 0.48,
    close: 0.5,
    volume: 0,
    source: 'fallback',
  };
  const firstPoint = candles[0] ?? fallbackCandle;
  const markerSignals = MOCK_SIGNALS.map((signal) => {
    const nearest = candles.reduce((best, point) => (
      Math.abs(point.timestamp - signal.timestamp) < Math.abs(best.timestamp - signal.timestamp) ? point : best
    ), firstPoint);
    return {
      ...signal,
      x: scale.x(nearest.timestamp),
      y: scale.y(nearest.close),
    };
  });
  const latest = candles[candles.length - 1] ?? firstPoint;

  return (
    <section className="qtv-chart-shell">
      <aside className="qtv-draw-rail" aria-label="Chart drawing tools">
        {DRAW_TOOLS.map((tool) => <button key={tool} type="button" title={tool}>{tool}</button>)}
      </aside>

      <div className="qtv-chart-stack">
        <div className="qtv-chart-info">
          <div>
            <strong>Will Team A win?</strong>
            <span>Sports - YES - 5m - Polymarket</span>
            <div className="qtv-indicator-legend">
              <span>Volume SMA 9 <b>38.963M</b></span>
              <span>BB 20 2 <b>0.663</b> <i>0.585</i> <em>0.522</em></span>
              <span>OrderFilled close <b>block axis</b></span>
            </div>
          </div>
          <div className="qtv-ohlc">
            <span>O {fmtPrice(latest.open)}</span>
            <span>H {fmtPrice(latest.high)}</span>
            <span>L {fmtPrice(latest.low)}</span>
            <span>C {fmtPrice(latest.close)}</span>
            <b>+0.012 (+1.9%)</b>
          </div>
        </div>

        <svg className="qtv-main-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Prediction market candlestick chart with strategy signals">
          <defs>
            <linearGradient id="qtvBand" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stop-color="#2f6df6" stop-opacity="0.34" />
              <stop offset="100%" stop-color="#2f6df6" stop-opacity="0.05" />
            </linearGradient>
            <linearGradient id="qtvVolume" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stop-color="#17b8b3" stop-opacity="0.74" />
              <stop offset="100%" stop-color="#17b8b3" stop-opacity="0.18" />
            </linearGradient>
          </defs>
          {Array.from({ length: 10 }, (_, index) => {
            const y = padding.top + (scale.plotH / 9) * index;
            return <line key={`h-${index}`} className="qtv-grid-line" x1={padding.left} x2={width - padding.right} y1={y} y2={y} />;
          })}
          {Array.from({ length: 14 }, (_, index) => {
            const x = padding.left + (scale.plotW / 13) * index;
            return <line key={`v-${index}`} className="qtv-grid-line" y1={padding.top} y2={height - padding.bottom + 78} x1={x} x2={x} />;
          })}

          <path className="qtv-band-fill" d={bandPath} />
          <path className="qtv-band-line" d={upperPath} />
          <path className="qtv-band-line" d={lowerPath} />
          <path className="qtv-ma-line" d={maPath} />

          <line className="qtv-current-line" x1={padding.left} x2={width - padding.right + 18} y1={scale.y(latest.close)} y2={scale.y(latest.close)} />
          <line className="qtv-resolution-line" x1={scale.x(candles[Math.floor(candles.length * 0.82)]?.timestamp || xMax)} x2={scale.x(candles[Math.floor(candles.length * 0.82)]?.timestamp || xMax)} y1={padding.top} y2={height - padding.bottom + 78} />

          {candles.map((candle) => {
            const x = scale.x(candle.timestamp);
            const openY = scale.y(candle.open);
            const closeY = scale.y(candle.close);
            const highY = scale.y(candle.high);
            const lowY = scale.y(candle.low);
            const bullish = candle.close >= candle.open;
            const bodyY = Math.min(openY, closeY);
            const bodyH = Math.max(2, Math.abs(openY - closeY));
            const volumeH = Math.max(3, (candle.volume / maxVolume) * 58);
            return (
              <g key={candle.timestamp} className={bullish ? 'qtv-candle up' : 'qtv-candle down'}>
                <line x1={x} x2={x} y1={highY} y2={lowY} />
                <rect x={x - candleW / 2} y={bodyY} width={candleW} height={bodyH} />
                <rect className="qtv-volume-bar" x={x - candleW / 2} y={height - 18 - volumeH} width={candleW} height={volumeH} />
              </g>
            );
          })}

          {markerSignals.map((signal) => {
            const isOpen = signal.action === 'OPEN' || signal.action === 'BUY';
            const labelY = isOpen ? signal.y - 45 : signal.y + 27;
            const arrowY = isOpen ? signal.y - 21 : signal.y + 22;
            return (
              <g key={signal.id} className={`qtv-signal ${isOpen ? 'open' : 'close'} ${selectedTradeId === signal.tradeId ? 'selected' : ''}`}>
                <title>{`Action: ${signal.action} ${signal.outcome}\nPrice: ${signal.price}\nSize: ${signal.size} shares\nNotional: ${signal.notional} USDC\nReason: ${signal.reason}`}</title>
                <path d={isOpen ? `M ${signal.x} ${arrowY} l 8 14 h -16 z` : `M ${signal.x} ${arrowY} l 8 -14 h -16 z`} />
                <rect x={signal.x - 30} y={labelY} width="60" height="26" rx="4" />
                <text x={signal.x} y={labelY + 17}>{signal.action === 'SELL' ? 'Sell' : signal.action}</text>
              </g>
            );
          })}

          {[1, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4].map((value) => (
            <text key={value} className="qtv-axis-text" x={width - 52} y={scale.y(value) + 4}>{value.toFixed(2)}</text>
          ))}
          <g className="qtv-price-badges">
            <rect x={width - 80} y={scale.y(latest.close) - 12} width="64" height="22" rx="3" />
            <text x={width - 48} y={scale.y(latest.close) + 4}>{fmtPrice(latest.close)}</text>
            <rect className="ask" x={width - 80} y={scale.y(latest.close) + 13} width="64" height="20" rx="3" />
            <text x={width - 48} y={scale.y(latest.close) + 28}>ASK 0.62</text>
          </g>
          {['23:01', '02:01', '05:01', '08:01', '11:01', '14:01', '17:01', '20:01'].map((label, index) => (
            <text key={label} className="qtv-time-axis" x={padding.left + (scale.plotW / 7) * index} y={height - 4}>{label}</text>
          ))}
        </svg>

        <div className="qtv-indicator-pane">
          <RsiPane points={candles} />
        </div>
      </div>
    </section>
  );
}

function RsiPane({ points }: { points: CandlePoint[] }) {
  const width = 1280;
  const height = 144;
  const padding = { left: 18, right: 88, top: 10, bottom: 24 };
  const xMin = points[0]?.timestamp || 0;
  const xMax = points[points.length - 1]?.timestamp || 1;
  const scale = scaleFactory(width, height, padding, xMin, xMax, 20, 80);
  const rsi = points.map((point, index) => ({
    x: point.timestamp,
    y: clamp(48 + Math.sin(index / 5) * 18 + Math.cos(index / 11) * 9 + (point.close - 0.5) * 40, 22, 78),
  }));
  const path = rsi.map((point, index) => `${index === 0 ? 'M' : 'L'} ${scale.x(point.x).toFixed(2)} ${scale.y(point.y).toFixed(2)}`).join(' ');
  const areaPath = `${path} L ${scale.x(rsi[rsi.length - 1]?.x || xMax).toFixed(2)} ${height - padding.bottom} L ${padding.left} ${height - padding.bottom} Z`;
  return (
    <svg className="qtv-rsi-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="RSI indicator pane">
      {Array.from({ length: 4 }, (_, index) => {
        const y = padding.top + (scale.plotH / 3) * index;
        return <line key={index} className="qtv-grid-line" x1={padding.left} x2={width - padding.right} y1={y} y2={y} />;
      })}
      <rect x={padding.left} y={scale.y(70)} width={scale.plotW} height={scale.y(30) - scale.y(70)} />
      <line className="qtv-rsi-threshold" x1={padding.left} x2={width - padding.right} y1={scale.y(70)} y2={scale.y(70)} />
      <line className="qtv-rsi-threshold" x1={padding.left} x2={width - padding.right} y1={scale.y(30)} y2={scale.y(30)} />
      <path className="qtv-rsi-fill" d={areaPath} />
      <path className="qtv-rsi-line" d={path} />
      <text x={width - 52} y={scale.y(70) + 4}>70.00</text>
      <text x={width - 52} y={scale.y(30) + 4}>30.00</text>
      <g>
        <rect x={width - 78} y={scale.y(rsi[rsi.length - 1]?.y || 50) - 11} width="62" height="22" rx="3" />
        <text x={width - 47} y={scale.y(rsi[rsi.length - 1]?.y || 50) + 4}>{fmtPrice((rsi[rsi.length - 1]?.y || 50) / 100)}</text>
      </g>
    </svg>
  );
}

function EquityDrawdownChart({ points }: { points: EquityPoint[] }) {
  const width = 1280;
  const height = 260;
  const padding = 26;
  const equityPoints = points.map((point) => ({ x: point.index, y: point.equity }));
  const drawdownPoints = points.map((point) => ({ x: point.index, y: point.drawdown }));
  const equityMin = Math.min(...equityPoints.map((point) => point.y));
  const equityMax = Math.max(...equityPoints.map((point) => point.y));
  const equityPath = buildPath(equityPoints, width, height, padding, equityMin, equityMax);
  const drawdownPath = buildPath(drawdownPoints, width, height, padding, -5000, 0);
  return (
    <svg className="qtv-equity-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Equity and drawdown curve">
      {Array.from({ length: 7 }, (_, index) => <line key={`h-${index}`} x1={padding} x2={width - padding} y1={padding + index * 34} y2={padding + index * 34} />)}
      {Array.from({ length: 11 }, (_, index) => <line key={`v-${index}`} y1={padding} y2={height - padding} x1={padding + index * 122} x2={padding + index * 122} />)}
      <path className="qtv-drawdown-fill" d={`${drawdownPath} L ${width - padding} ${padding} L ${padding} ${padding} Z`} />
      <path className="qtv-equity-fill" d={`${equityPath} L ${width - padding} ${height - padding} L ${padding} ${height - padding} Z`} />
      <path className="qtv-equity-line" d={equityPath} />
      <path className="qtv-drawdown-line" d={drawdownPath} />
    </svg>
  );
}

function MetricCard({ name, value, delta, status, tooltip }: { name: string; value: string; delta: string; status: 'positive' | 'negative' | 'neutral'; tooltip: string }) {
  return (
    <div className="qtv-metric" title={tooltip}>
      <span>{name}</span>
      <strong className={status}>{value}</strong>
      <em className={status}>{delta}</em>
    </div>
  );
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
  const [selectedTradeId, setSelectedTradeId] = useState<string | null>('T-118');
  const [marketSlug, setMarketSlug] = useState('');

  const activePrices = useMemo(() => {
    if (priceSource === 'orderfilled') return blockToPrices(blockRows);
    if (priceSource === 'frontend') return frontendToPrices(frontendRows);
    return [];
  }, [blockRows, frontendRows, priceSource]);
  const renderedPrices = activePrices.length ? activePrices : MOCK_PRICES;
  const latestPrice = renderedPrices[renderedPrices.length - 1]?.close || 0;
  const netPnl = MOCK_TRADES.reduce((sum, trade) => sum + trade.pnl, 0);
  const query: QuantPriceQuery = { marketSlug, tokenSide: 'YES', limit: 360 };

  const loadQuantData = async () => {
    setLoading(true);
    setError('');
    const hasMarketSlug = Boolean(marketSlug.trim());
    const [frontendResult, blockResult, statusResult] = await Promise.allSettled([
      hasMarketSlug ? fetchQuantFrontendPrices(query) : Promise.resolve({ count: 0, items: [] }),
      hasMarketSlug ? fetchQuantBlockClosePrices(query) : Promise.resolve({ count: 0, items: [] }),
      fetchQuantBuildStatus('', 12),
    ]);
    if (frontendResult.status === 'fulfilled') setFrontendRows(frontendResult.value.items || []);
    if (blockResult.status === 'fulfilled') setBlockRows(blockResult.value.items || []);
    if (statusResult.status === 'fulfilled') setRuns(statusResult.value.items || []);
    const rejected = [frontendResult, blockResult, statusResult].find((result) => result.status === 'rejected');
    if (hasMarketSlug && rejected?.status === 'rejected') {
      setError(rejected.reason instanceof Error ? rejected.reason.message : 'Quant API unavailable');
    }
    setLoading(false);
  };

  useEffect(() => {
    void loadQuantData();
  }, []);

  return (
    <div className="qtv-shell">
      <header className="qtv-topbar">
        <div className="qtv-left-tools">
          <a className="qtv-logo" href="/">POLYDATA</a>
          <button type="button" title="Menu">Menu</button>
          <label className="qtv-symbol-search">
            <span>Search</span>
            <input value={marketSlug} onInput={(event) => setMarketSlug(event.currentTarget.value)} placeholder="market_slug" />
          </label>
          <button type="button" title="Add market">+</button>
          <div className="qtv-timeframes">
            {['1m', '5m', '15m', '1h', '4h', '1d'].map((item) => (
              <button key={item} className={timeframe === item ? 'active' : ''} type="button" onClick={() => setTimeframe(item)}>{item}</button>
            ))}
          </div>
          <button type="button" title="Candles">Candles</button>
          <button type="button" title="Indicators">Indicators</button>
          <button type="button" title="Compare">Layout</button>
          <button type="button" title="Undo">Undo</button>
        </div>

        <div className="qtv-right-tools">
          <select value={priceSource} onChange={(event) => setPriceSource(event.currentTarget.value as PriceSource)}>
            <option value="frontend">Frontend price-history</option>
            <option value="orderfilled">OrderFilled block close</option>
            <option value="orderbook">Orderbook mid</option>
            <option value="conservative">Conservative bid/ask</option>
          </select>
          <button type="button">Save</button>
          <button type="button">Snapshot</button>
          <button className="primary" type="button" onClick={() => void loadQuantData()}>{loading ? 'Running...' : 'Run Backtest'}</button>
        </div>
      </header>

      {error ? <div className="qtv-error">{error}</div> : null}

      <main className="qtv-workspace">
        <PriceChartPanel prices={renderedPrices} selectedTradeId={selectedTradeId} />

        <section className="qtv-bottom-panel">
          <nav className="qtv-tool-tabs" aria-label="Backtest tools">
            {['Market Screener', 'Strategy Editor', 'Strategy Tester', 'Replay Trading', 'Trading Panel'].map((item) => (
              <button key={item} className={item === 'Strategy Tester' ? 'active' : ''} type="button">{item}</button>
            ))}
            <span className="qtv-powered">PolyData</span>
          </nav>

          <div className="qtv-tester-head">
            <div className="qtv-strategy-title">
              <strong>Momentum Probability Strategy</strong>
              <button type="button" title="Strategy settings">Settings</button>
              <button type="button" onClick={() => void loadQuantData()} title="Refresh strategy data">Refresh</button>
            </div>
            <div className="qtv-tester-actions">
              <label><input type="checkbox" checked /> Backtest mode</label>
              <label><input type="checkbox" checked={deepBacktest} onChange={() => setDeepBacktest((current) => !current)} /> Deep Backtest</label>
              <button type="button">Export</button>
            </div>
          </div>

          <nav className="qtv-subtabs" aria-label="Strategy tester tabs">
            {[
              ['overview', 'Overview'],
              ['performance', 'Performance Summary'],
              ['trades', 'List of Trades'],
              ['properties', 'Properties'],
            ].map(([id, label]) => (
              <button key={id} className={testerTab === id ? 'active' : ''} type="button" onClick={() => setTesterTab(id as TesterTab)}>{label}</button>
            ))}
          </nav>

          {testerTab === 'overview' ? (
            <div className="qtv-overview">
              <div className="qtv-metrics-row">
                <MetricCard name="Net Profit" value={fmtCurrency(netPnl)} delta="+4.79%" status={statusClass(netPnl)} tooltip="Closed realized strategy PnL" />
                <MetricCard name="Total Return" value="+4.78%" delta="+0.42 beta adj" status="positive" tooltip="Return on initial capital" />
                <MetricCard name="Max Drawdown" value="-3,754.52 USDC" delta="-3.45%" status="negative" tooltip="Largest peak-to-trough equity loss" />
                <MetricCard name="Win Rate" value="35.55%" delta="878 / 2,470" status="positive" tooltip="Percent profitable closed trades" />
                <MetricCard name="Profit Factor" value="1.198" delta="gross P/L" status="neutral" tooltip="Gross profit divided by gross loss" />
                <MetricCard name="Total Trades" value="2,470" delta={`${runs.length} runs`} status="neutral" tooltip="Closed strategy trades" />
                <MetricCard name="Avg Trade" value="7.77 USDC" delta="+0.01%" status="positive" tooltip="Average closed trade PnL" />
                <MetricCard name="Avg Holding" value="5 bars" delta={timeframe} status="neutral" tooltip="Average bars held per trade" />
              </div>
              <div className="qtv-result-grid">
                <div className="qtv-equity-wrap">
                  <EquityDrawdownChart points={MOCK_EQUITY} />
                </div>
                <div className="qtv-mini-table">
                  <strong>Strategy Report</strong>
                  {PERFORMANCE_ROWS.slice(0, 7).map((row) => (
                    <div key={row[0]}>
                      <span>{row[0]}</span>
                      <b>{row[1]}</b>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}

          {testerTab === 'performance' ? (
            <div className="qtv-table-wrap">
              <table className="qtv-table">
                <thead><tr><th>Metric</th><th>All Trades</th><th>Long / YES</th><th>Short / NO</th><th>Description</th></tr></thead>
                <tbody>{PERFORMANCE_ROWS.map((row) => <tr key={row[0]}>{row.map((cell) => <td key={cell}>{cell}</td>)}</tr>)}</tbody>
              </table>
            </div>
          ) : null}

          {testerTab === 'trades' ? (
            <div className="qtv-table-wrap">
              <div className="qtv-filter-strip">
                {['Profitable only', 'Losing only', 'YES only', 'NO only', 'Long holding', 'Short holding'].map((item) => <button key={item} type="button">{item}</button>)}
              </div>
              <table className="qtv-table">
                <thead><tr><th>Trade #</th><th>Entry Time</th><th>Exit Time</th><th>Market</th><th>Outcome</th><th>Side</th><th>Entry</th><th>Exit</th><th>Size</th><th>Notional</th><th>PnL</th><th>PnL %</th><th>Holding</th><th>Exit Reason</th></tr></thead>
                <tbody>
                  {MOCK_TRADES.map((trade) => (
                    <tr key={trade.id} className={selectedTradeId === trade.id ? 'selected' : ''} onClick={() => setSelectedTradeId(trade.id)}>
                      <td>{trade.id}</td><td>{trade.entryTime}</td><td>{trade.exitTime}</td><td>{trade.market}</td><td>{trade.outcome}</td><td>{trade.side}</td><td>{fmtPrice(trade.entryPrice)}</td><td>{fmtPrice(trade.exitPrice)}</td><td>{trade.size}</td><td>{fmtCurrency(trade.notional)}</td><td className={statusClass(trade.pnl)}>{fmtCurrency(trade.pnl)}</td><td className={statusClass(trade.pnlPct)}>{trade.pnlPct.toFixed(2)}%</td><td>{trade.holdingTime}</td><td>{trade.exitReason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {testerTab === 'properties' ? (
            <div className="qtv-properties">
              {PROPERTY_GROUPS.map(([group, values]) => (
                <section key={group}>
                  <h3>{group}</h3>
                  {(values as string[]).map((value) => <div key={value}><span>{value.split(' ')[0]}</span><strong>{value}</strong></div>)}
                </section>
              ))}
            </div>
          ) : null}
        </section>
      </main>

      <div className="qtv-statusbar">
        <span>source {priceSource}</span>
        <span>latest YES {fmtPrice(latestPrice)}</span>
        <span>frontend rows {frontendRows.length}</span>
        <span>block close rows {blockRows.length}</span>
        <span>UTC+0</span>
        <span>%</span>
        <span>log</span>
        <span>auto</span>
      </div>
    </div>
  );
}
