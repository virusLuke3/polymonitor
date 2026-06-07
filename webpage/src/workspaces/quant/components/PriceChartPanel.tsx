import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from 'lightweight-charts';
import type { CandlePoint, DataStatus, MarketInfo, PricePoint, Signal } from '../types';
import { clamp, movingAverage, scaleFactory, toCandles } from '../utils/backtest';
import { fmtPrice, formatTime } from '../utils/formatters';

const DRAW_TOOLS = ['+', 'T', '/', 'R', 'Fib', 'Br', 'Mag', 'Lock', 'Eye'];
const SYNTHETIC_BLOCK_AXIS_START = 1_704_067_200;

type PriceChartPanelProps = {
  prices: PricePoint[];
  market: MarketInfo;
  selectedTradeId: string | null;
  signals?: Signal[];
  priceSource: string;
  dataStatus: DataStatus;
};

type SeriesRefs = {
  candle: ISeriesApi<'Candlestick'> | null;
  volume: ISeriesApi<'Histogram'> | null;
  ma: ISeriesApi<'Line'> | null;
};

type SignalMarker = NonNullable<ReturnType<typeof markerPosition>>;

function chartTime(point: PricePoint, index: number): Time {
  if (point.source.includes('block')) return (SYNTHETIC_BLOCK_AXIS_START + index * 60) as Time;
  return Math.max(0, Math.floor(point.timestamp)) as Time;
}

function timeLabel(point: PricePoint | CandlePoint | undefined, source: string) {
  if (!point) return '--';
  if (source.includes('block')) return `block ${point.timestamp.toLocaleString('en-US')}`;
  return formatTime(point.timestamp);
}

function priceDelta(points: CandlePoint[]) {
  const latest = points[points.length - 1];
  const previous = points[points.length - 2] || points[0];
  if (!latest || !previous) return { absolute: 0, percent: 0 };
  const absolute = latest.close - previous.close;
  const percent = previous.close ? (absolute / previous.close) * 100 : 0;
  return { absolute, percent };
}

function formatSigned(value: number, digits = 3) {
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}`;
}

function markerPosition(signal: Signal, candles: CandlePoint[]) {
  if (!candles.length) return null;
  let bestIndex = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  candles.forEach((candle, index) => {
    const distance = Math.abs(candle.timestamp - signal.timestamp);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  const candle = candles[bestIndex];
  if (!candle) return null;
  return {
    signal,
    candle,
    left: `${(bestIndex / Math.max(1, candles.length - 1)) * 100}%`,
    top: `${clamp((1 - candle.close) * 100, 8, 82)}%`,
  };
}

export function PriceChartPanel({
  prices,
  market,
  selectedTradeId,
  signals = [],
  priceSource,
  dataStatus,
}: PriceChartPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<SeriesRefs>({ candle: null, volume: null, ma: null });
  const candlesRef = useRef<CandlePoint[]>([]);
  const timeLabelRef = useRef<Map<number, string>>(new Map());
  const [hover, setHover] = useState<CandlePoint | null>(null);
  const points = useMemo(() => prices.slice(-900), [prices]);
  const candles = useMemo(() => toCandles(points), [points]);
  const latest = candles[candles.length - 1];
  const first = candles[0];
  const delta = priceDelta(candles);
  const volumeTotal = candles.reduce((sum, candle) => sum + (Number.isFinite(candle.volume) ? candle.volume : 0), 0);
  const closes = candles.map((point) => point.close);
  const ma = useMemo(() => movingAverage(closes, Math.min(20, Math.max(2, Math.floor(candles.length / 8)))), [candles.length, closes]);
  useEffect(() => {
    candlesRef.current = candles;
  }, [candles]);

  const markers = useMemo(
    () => signals.map((signal) => markerPosition(signal, candles)).filter((marker): marker is SignalMarker => Boolean(marker)),
    [candles, signals],
  );
  const focusedMarkers = markers.filter((marker) => marker?.signal.tradeId === selectedTradeId);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const chart = createChart(container, {
      autoSize: false,
      height: Math.max(280, container.clientHeight || 360),
      width: Math.max(360, container.clientWidth || 760),
      layout: {
        attributionLogo: false,
        background: { type: ColorType.Solid, color: '#0b0d10' },
        textColor: '#9ca3af',
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.055)' },
        horzLines: { color: 'rgba(255,255,255,0.07)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(148,163,184,0.18)',
        scaleMargins: { top: 0.08, bottom: 0.24 },
      },
      timeScale: {
        borderColor: 'rgba(148,163,184,0.18)',
        fixLeftEdge: true,
        fixRightEdge: true,
        secondsVisible: false,
        timeVisible: true,
        rightOffset: 5,
        barSpacing: 8,
        tickMarkFormatter: (time: Time) => timeLabelRef.current.get(Number(time)) || '',
      },
      crosshair: {
        horzLine: { color: 'rgba(148,163,184,0.42)', labelBackgroundColor: '#1f2937' },
        vertLine: { color: 'rgba(148,163,184,0.28)', labelBackgroundColor: '#1f2937' },
      },
      localization: {
        priceFormatter: (value: number) => fmtPrice(value),
      },
    });
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: '#00b894',
      downColor: '#ff3b55',
      borderUpColor: '#12d6bd',
      borderDownColor: '#ff5d6f',
      wickUpColor: '#12d6bd',
      wickDownColor: '#ff5d6f',
      priceLineColor: '#2f6df6',
      priceLineWidth: 1,
    });
    const maSeries = chart.addSeries(LineSeries, {
      color: '#f59e0b',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const volume = chart.addSeries(HistogramSeries, {
      color: 'rgba(20,184,166,0.42)',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
      priceLineVisible: false,
      lastValueVisible: false,
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    seriesRef.current = { candle, volume, ma: maSeries };
    chartRef.current = chart;

    chart.subscribeCrosshairMove((param) => {
      const time = Number(param.time);
      if (!Number.isFinite(time)) {
        setHover(null);
        return;
      }
      const currentCandles = candlesRef.current;
      const index = currentCandles.findIndex((item, itemIndex) => Number(chartTime(item, itemIndex)) === time);
      setHover(index >= 0 ? currentCandles[index] || null : null);
    });

    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      chart.resize(Math.max(360, Math.floor(entry.contentRect.width)), Math.max(280, Math.floor(entry.contentRect.height)));
      chart.timeScale().fitContent();
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = { candle: null, volume: null, ma: null };
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series.candle || !series.volume || !series.ma) return;
    const candleData: CandlestickData<Time>[] = candles.map((candle, index) => ({
      time: chartTime(candle, index),
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
    }));
    timeLabelRef.current = new Map(candles.map((candle, index) => {
      const time = Number(chartTime(candle, index));
      const label = priceSource.includes('block')
        ? `b${Math.round(candle.timestamp / 1000)}k`
        : formatTime(candle.timestamp);
      return [time, label];
    }));
    const volumeData: HistogramData<Time>[] = candles.map((candle, index) => ({
      time: chartTime(candle, index),
      value: Math.max(0, candle.volume),
      color: candle.close >= candle.open ? 'rgba(20,184,166,0.45)' : 'rgba(255,59,85,0.42)',
    }));
    const maData: LineData<Time>[] = candles.map((candle, index) => ({
      time: chartTime(candle, index),
      value: ma[index] ?? candle.close,
    }));
    series.candle.setData(candleData);
    series.volume.setData(volumeData);
    series.ma.setData(maData);
    chart.timeScale().fitContent();
  }, [candles, ma]);

  const shown = hover || latest;

  return (
    <section className="qtv-chart-shell">
      <aside className="qtv-draw-rail" aria-label="Chart drawing tools">
        {DRAW_TOOLS.map((tool) => <button key={tool} type="button" title={tool}>{tool}</button>)}
      </aside>

      <div className="qtv-chart-stack">
        <div className="qtv-chart-info">
          <div>
            <strong>{market.title}</strong>
            <span>{market.category} - YES - Polymarket - {priceSource}</span>
            <div className="qtv-indicator-legend">
              <span>Rows <b>{candles.length.toLocaleString('en-US')}</b></span>
              <span>Range <i>{timeLabel(first, priceSource)}</i> <em>{timeLabel(latest, priceSource)}</em></span>
              <span>Volume <b>{volumeTotal.toLocaleString('en-US', { maximumFractionDigits: 2 })}</b></span>
            </div>
          </div>
          <div className="qtv-ohlc">
            <span>O {fmtPrice(shown?.open || 0)}</span>
            <span>H {fmtPrice(shown?.high || 0)}</span>
            <span>L {fmtPrice(shown?.low || 0)}</span>
            <span>C {fmtPrice(shown?.close || 0)}</span>
            <b className={delta.absolute >= 0 ? 'positive' : 'negative'}>{formatSigned(delta.absolute)} ({formatSigned(delta.percent, 2)}%)</b>
          </div>
        </div>

        <div className="qtv-tv-chart" ref={containerRef}>
          {!candles.length ? (
            <div className="qtv-chart-empty">
              <strong>{dataStatus === 'loading' ? 'Loading market prices' : 'No real price rows'}</strong>
              <span>Select a market with quant price coverage or run the price builder first.</span>
            </div>
          ) : null}
          {markers.map((marker) => (
            <div
              key={marker.signal.id}
              className={`qtv-html-signal ${marker.signal.action === 'OPEN' || marker.signal.action === 'BUY' ? 'open' : 'close'} ${marker.signal.tradeId === selectedTradeId ? 'selected' : ''}`}
              style={{ left: marker.left, top: marker.top }}
              title={`${marker.signal.action} ${marker.signal.outcome} @ ${fmtPrice(marker.signal.price)}\n${marker.signal.reason}`}
            >
              {marker.signal.action === 'SELL' ? 'SELL' : marker.signal.action}
            </div>
          ))}
          {focusedMarkers.length ? <div className="qtv-trade-focus-pill">{selectedTradeId} entry / exit located</div> : null}
        </div>

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
