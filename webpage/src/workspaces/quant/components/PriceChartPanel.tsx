import { useMemo, useState } from 'preact/hooks';
import type { CandlePoint, MarketInfo, PricePoint, Signal } from '../types';
import { MOCK_PRICES, MOCK_SIGNALS } from '../data/mockBacktestData';
import { clamp, movingAverage, scaleFactory, toCandles } from '../utils/backtest';
import { fmtPrice, formatTime } from '../utils/formatters';

const DRAW_TOOLS = ['+', 'T', '/', 'R', 'Fib', 'Br', 'Mag', 'Lock', 'Eye'];

type HoverPoint = {
  candle: CandlePoint;
  x: number;
  y: number;
};

type PriceChartPanelProps = {
  prices: PricePoint[];
  market: MarketInfo;
  selectedTradeId: string | null;
  signals?: Signal[];
};

export function PriceChartPanel({ prices, market, selectedTradeId, signals = MOCK_SIGNALS }: PriceChartPanelProps) {
  const [hover, setHover] = useState<HoverPoint | null>(null);
  const width = 1280;
  const height = 560;
  const padding = { left: 18, right: 88, top: 22, bottom: 88 };
  const points = prices.length ? prices.slice(-128) : MOCK_PRICES;
  const candles = useMemo(() => toCandles(points), [points]);
  const xMin = candles[0]?.timestamp || 0;
  const xMax = candles[candles.length - 1]?.timestamp || 1;
  const scale = scaleFactory(width, height, padding, xMin, xMax, 0, 1);
  const closes = candles.map((point) => point.close);
  const ma = movingAverage(closes, 18);
  const upper = ma.map((value, index) => Math.min(1, value + 0.05 + Math.abs(Math.sin(index / 11)) * 0.014));
  const lower = ma.map((value, index) => Math.max(0, value - 0.05 - Math.abs(Math.cos(index / 13)) * 0.014));
  const toScaledPath = (items: Array<{ x: number; y: number }>) => items.map((point, index) => (
    `${index === 0 ? 'M' : 'L'} ${scale.x(point.x).toFixed(2)} ${scale.y(point.y).toFixed(2)}`
  )).join(' ');
  const upperPoints = candles.map((point, index) => ({ x: point.timestamp, y: upper[index] ?? point.close }));
  const lowerPoints = candles.map((point, index) => ({ x: point.timestamp, y: lower[index] ?? point.close }));
  const maPoints = candles.map((point, index) => ({ x: point.timestamp, y: ma[index] ?? point.close }));
  const upperPath = toScaledPath(upperPoints);
  const lowerPath = toScaledPath(lowerPoints);
  const maPath = toScaledPath(maPoints);
  const lowerBandPath = lowerPoints.slice().reverse().map((point) => `L ${scale.x(point.x).toFixed(2)} ${scale.y(point.y).toFixed(2)}`).join(' ');
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
  const latest = candles[candles.length - 1] ?? firstPoint;
  const markerSignals = signals.map((signal) => {
    const nearest = candles.reduce((best, point) => (
      Math.abs(point.timestamp - signal.timestamp) < Math.abs(best.timestamp - signal.timestamp) ? point : best
    ), firstPoint);
    return {
      ...signal,
      x: scale.x(nearest.timestamp),
      y: scale.y(nearest.close),
      candle: nearest,
    };
  });
  const focusedSignals = markerSignals.filter((signal) => signal.tradeId === selectedTradeId);

  const handleMouseMove = (event: MouseEvent) => {
    const rect = (event.currentTarget as SVGSVGElement).getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * width;
    const y = ((event.clientY - rect.top) / rect.height) * height;
    const nearest = candles.reduce((best, candle) => (
      Math.abs(scale.x(candle.timestamp) - x) < Math.abs(scale.x(best.timestamp) - x) ? candle : best
    ), firstPoint);
    setHover({ candle: nearest, x: scale.x(nearest.timestamp), y: clamp(y, padding.top, height - padding.bottom) });
  };

  return (
    <section className="qtv-chart-shell">
      <aside className="qtv-draw-rail" aria-label="Chart drawing tools">
        {DRAW_TOOLS.map((tool) => <button key={tool} type="button" title={tool}>{tool}</button>)}
      </aside>

      <div className="qtv-chart-stack">
        <div className="qtv-chart-info">
          <div>
            <strong>{market.title}</strong>
            <span>{market.category} - YES - 5m - Polymarket</span>
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

        <svg
          className="qtv-main-chart"
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          role="img"
          aria-label="Prediction market candlestick chart with strategy signals"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHover(null)}
        >
          <defs>
            <linearGradient id="qtvBand" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stop-color="#2f6df6" stop-opacity="0.34" />
              <stop offset="100%" stop-color="#2f6df6" stop-opacity="0.05" />
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

          <path className="qtv-band-fill" d={`${upperPath} ${lowerBandPath} Z`} />
          <path className="qtv-band-line" d={upperPath} />
          <path className="qtv-band-line" d={lowerPath} />
          <path className="qtv-ma-line" d={maPath} />
          <line className="qtv-current-line" x1={padding.left} x2={width - padding.right + 18} y1={scale.y(latest.close)} y2={scale.y(latest.close)} />
          <line className="qtv-resolution-line" x1={scale.x(candles[Math.floor(candles.length * 0.82)]?.timestamp || xMax)} x2={scale.x(candles[Math.floor(candles.length * 0.82)]?.timestamp || xMax)} y1={padding.top} y2={height - padding.bottom + 78} />

          {focusedSignals.map((signal) => (
            <line key={`focus-${signal.id}`} className="qtv-trade-focus-line" x1={signal.x} x2={signal.x} y1={padding.top} y2={height - padding.bottom + 78} />
          ))}
          {focusedSignals.length >= 2 ? (
            <path className="qtv-trade-focus-path" d={`M ${focusedSignals[0]?.x ?? 0} ${focusedSignals[0]?.y ?? 0} L ${focusedSignals[1]?.x ?? 0} ${focusedSignals[1]?.y ?? 0}`} />
          ) : null}

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

          {hover ? (
            <g className="qtv-crosshair">
              <line x1={hover.x} x2={hover.x} y1={padding.top} y2={height - padding.bottom + 78} />
              <line x1={padding.left} x2={width - padding.right} y1={hover.y} y2={hover.y} />
            </g>
          ) : null}

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

        {hover ? (
          <div className="qtv-chart-tooltip" style={{ left: `${(hover.x / width) * 100}%`, top: `${(hover.y / height) * 100}%` }}>
            <strong>{formatTime(hover.candle.timestamp)}</strong>
            <span>O {fmtPrice(hover.candle.open)} H {fmtPrice(hover.candle.high)}</span>
            <span>L {fmtPrice(hover.candle.low)} C {fmtPrice(hover.candle.close)}</span>
            <span>Volume {hover.candle.volume.toLocaleString('en-US')}</span>
            <span>Source {hover.candle.source}</span>
          </div>
        ) : null}

        {focusedSignals.length ? (
          <div className="qtv-trade-focus-pill">
            {selectedTradeId} entry / exit located
          </div>
        ) : null}

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
