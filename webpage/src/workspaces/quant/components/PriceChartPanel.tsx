import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import {
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from 'lightweight-charts';
import type { DataStatus, MarketInfo, PricePoint, Signal } from '../types';
import { movingAverage } from '../utils/backtest';
import { fmtPrice, formatTime } from '../utils/formatters';

const DRAW_TOOLS = ['+', 'T', '/', 'R', 'Fib', 'Br', 'Mag', 'Lock', 'Eye'];

type PriceChartPanelProps = {
  prices: PricePoint[];
  market: MarketInfo;
  selectedTradeId: string | null;
  signals?: Signal[];
  priceSource: string;
  dataStatus: DataStatus;
};

type SeriesRefs = {
  yes: ISeriesApi<'Line'> | null;
  no: ISeriesApi<'Line'> | null;
  ma: ISeriesApi<'Line'> | null;
  volume: ISeriesApi<'Histogram'> | null;
};

function chartTime(point: PricePoint): Time {
  return Math.floor(point.timestamp) as Time;
}

function blockLabel(value: number) {
  if (!Number.isFinite(value)) return '';
  return value.toLocaleString('en-US');
}

function pointLabel(point: PricePoint | undefined, source: string) {
  if (!point) return '--';
  if (source.includes('block')) return `block ${blockLabel(point.timestamp)}`;
  return formatTime(point.timestamp);
}

function sortUnique(points: PricePoint[]) {
  const seen = new Set<number>();
  return points
    .filter((point) => Number.isFinite(point.timestamp) && Number.isFinite(point.close))
    .sort((left, right) => left.timestamp - right.timestamp)
    .filter((point) => {
      const key = Math.floor(point.timestamp);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function sidePoints(points: PricePoint[], side: string) {
  const sideRows = points.filter((point) => (point.tokenSide || 'YES').toUpperCase() === side);
  return sortUnique(sideRows.length ? sideRows : points);
}

function lineData(points: PricePoint[]): LineData<Time>[] {
  return points.map((point) => ({
    time: chartTime(point),
    value: point.close,
  }));
}

function volumeData(points: PricePoint[]): HistogramData<Time>[] {
  return points.map((point) => ({
    time: chartTime(point),
    value: Math.max(0, point.volume),
    color: 'rgba(148,163,184,0.24)',
  }));
}

function formatSigned(value: number, digits = 3) {
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}`;
}

function markerPosition(signal: Signal, points: PricePoint[]) {
  if (!points.length) return null;
  let bestIndex = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  points.forEach((point, index) => {
    const distance = Math.abs(point.timestamp - signal.timestamp);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  const point = points[bestIndex];
  if (!point) return null;
  return {
    signal,
    point,
    left: `${(bestIndex / Math.max(1, points.length - 1)) * 100}%`,
    top: `${Math.max(7, Math.min(84, (1 - point.close) * 100))}%`,
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
  const seriesRef = useRef<SeriesRefs>({ yes: null, no: null, ma: null, volume: null });
  const pointsRef = useRef<PricePoint[]>([]);
  const [hover, setHover] = useState<PricePoint | null>(null);

  const allPoints = useMemo(() => sortUnique(prices), [prices]);
  const yesPoints = useMemo(() => sidePoints(prices, 'YES'), [prices]);
  const noPoints = useMemo(() => sidePoints(prices, 'NO'), [prices]);
  const primaryPoints = yesPoints.length ? yesPoints : allPoints;
  const latest = hover || primaryPoints[primaryPoints.length - 1];
  const previous = primaryPoints[Math.max(0, primaryPoints.length - 2)];
  const delta = latest && previous ? latest.close - previous.close : 0;
  const deltaPct = latest && previous?.close ? (delta / previous.close) * 100 : 0;
  const minPrice = primaryPoints.reduce((min, point) => Math.min(min, point.close), Number.POSITIVE_INFINITY);
  const maxPrice = primaryPoints.reduce((max, point) => Math.max(max, point.close), Number.NEGATIVE_INFINITY);
  const volumeTotal = allPoints.reduce((sum, point) => sum + (Number.isFinite(point.volume) ? point.volume : 0), 0);
  const maPoints = useMemo(() => {
    const closes = primaryPoints.map((point) => point.close);
    const ma = movingAverage(closes, Math.min(40, Math.max(3, Math.floor(primaryPoints.length / 20))));
    return primaryPoints.map((point, index) => ({ ...point, close: ma[index] ?? point.close }));
  }, [primaryPoints]);
  const markers = useMemo(() => signals.map((signal) => markerPosition(signal, primaryPoints)).filter(Boolean), [primaryPoints, signals]);
  const focusedMarkers = markers.filter((marker) => marker?.signal.tradeId === selectedTradeId);

  useEffect(() => {
    pointsRef.current = primaryPoints;
  }, [primaryPoints]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const chart = createChart(container, {
      autoSize: false,
      height: Math.max(300, container.clientHeight || 420),
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
        horzLines: { color: 'rgba(255,255,255,0.075)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(148,163,184,0.18)',
        scaleMargins: { top: 0.08, bottom: 0.22 },
      },
      timeScale: {
        borderColor: 'rgba(148,163,184,0.18)',
        fixLeftEdge: true,
        fixRightEdge: true,
        secondsVisible: false,
        timeVisible: false,
        rightOffset: 2,
        barSpacing: 5,
        tickMarkFormatter: (time: Time) => priceSource.includes('block') ? blockLabel(Number(time)) : formatTime(Number(time)),
      },
      localization: {
        priceFormatter: (value: number) => `${Math.round(value * 100)}%`,
        timeFormatter: (time: Time) => priceSource.includes('block') ? `block ${blockLabel(Number(time))}` : formatTime(Number(time)),
      },
      crosshair: {
        horzLine: { color: 'rgba(148,163,184,0.42)', labelBackgroundColor: '#1f2937' },
        vertLine: { color: 'rgba(148,163,184,0.28)', labelBackgroundColor: '#1f2937' },
      },
    });
    const yes = chart.addSeries(LineSeries, {
      color: '#22c55e',
      lineWidth: 2,
      priceLineColor: '#2563eb',
      priceLineWidth: 1,
      title: 'YES probability',
      autoscaleInfoProvider: () => ({
        priceRange: { minValue: 0, maxValue: 1 },
      }),
    });
    const no = chart.addSeries(LineSeries, {
      color: '#3b82f6',
      lineWidth: 2,
      priceLineVisible: false,
      title: 'NO token -> YES probability',
      autoscaleInfoProvider: () => ({
        priceRange: { minValue: 0, maxValue: 1 },
      }),
    });
    const ma = chart.addSeries(LineSeries, {
      color: '#f59e0b',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      title: 'MA',
    });
    const volume = chart.addSeries(HistogramSeries, {
      color: 'rgba(148,163,184,0.24)',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
      priceLineVisible: false,
      lastValueVisible: false,
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    seriesRef.current = { yes, no, ma, volume };
    chartRef.current = chart;

    chart.subscribeCrosshairMove((param) => {
      const time = Number(param.time);
      if (!Number.isFinite(time)) {
        setHover(null);
        return;
      }
      const currentPoints = pointsRef.current;
      const point = currentPoints.reduce<PricePoint | null>((best, candidate) => {
        if (!best) return candidate;
        return Math.abs(candidate.timestamp - time) < Math.abs(best.timestamp - time) ? candidate : best;
      }, null);
      setHover(point);
    });

    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      chart.resize(Math.max(360, Math.floor(entry.contentRect.width)), Math.max(300, Math.floor(entry.contentRect.height)));
      chart.timeScale().fitContent();
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = { yes: null, no: null, ma: null, volume: null };
    };
  }, [priceSource]);

  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series.yes || !series.no || !series.ma || !series.volume) return;
    series.yes.setData(lineData(yesPoints));
    series.no.setData(noPoints.length ? lineData(noPoints) : []);
    series.ma.setData(lineData(maPoints));
    series.volume.setData(volumeData(allPoints));
    chart.timeScale().fitContent();
  }, [allPoints, maPoints, noPoints, yesPoints]);

  return (
    <section className="qtv-chart-shell">
      <aside className="qtv-draw-rail" aria-label="Chart drawing tools">
        {DRAW_TOOLS.map((tool) => <button key={tool} type="button" title={tool}>{tool}</button>)}
      </aside>

      <div className="qtv-chart-stack">
        <div className="qtv-chart-info">
          <div>
            <strong>{market.title}</strong>
            <span>{market.category} - YES probability - {priceSource}</span>
            <div className="qtv-indicator-legend">
              <span>Rows <b>{allPoints.length.toLocaleString('en-US')}</b></span>
              <span>Range <i>{pointLabel(primaryPoints[0], priceSource)}</i> <em>{pointLabel(primaryPoints[primaryPoints.length - 1], priceSource)}</em></span>
              <span>Volume <b>{volumeTotal.toLocaleString('en-US', { maximumFractionDigits: 2 })}</b></span>
            </div>
          </div>
          <div className="qtv-ohlc">
            <span>Block {latest ? blockLabel(latest.timestamp) : '--'}</span>
            <span>Price {fmtPrice(latest?.close || 0)}</span>
            <span>Min {Number.isFinite(minPrice) ? fmtPrice(minPrice) : '--'}</span>
            <span>Max {Number.isFinite(maxPrice) ? fmtPrice(maxPrice) : '--'}</span>
            <b className={delta >= 0 ? 'positive' : 'negative'}>{formatSigned(delta)} ({formatSigned(deltaPct, 2)}%)</b>
          </div>
        </div>

        <div className="qtv-tv-chart" ref={containerRef}>
          {!allPoints.length ? (
            <div className="qtv-chart-empty">
              <strong>{dataStatus === 'loading' ? 'Loading market prices' : 'No real price rows'}</strong>
              <span>Search or select a market with quant block close coverage.</span>
            </div>
          ) : null}
          {markers.map((marker) => marker ? (
            <div
              key={marker.signal.id}
              className={`qtv-html-signal ${marker.signal.action === 'OPEN' || marker.signal.action === 'BUY' ? 'open' : 'close'} ${marker.signal.tradeId === selectedTradeId ? 'selected' : ''}`}
              style={{ left: marker.left, top: marker.top }}
              title={`${marker.signal.action} ${marker.signal.outcome} @ ${fmtPrice(marker.signal.price)}\n${marker.signal.reason}`}
            >
              {marker.signal.action === 'SELL' ? 'SELL' : marker.signal.action}
            </div>
          ) : null)}
          {focusedMarkers.length ? <div className="qtv-trade-focus-pill">{selectedTradeId} entry / exit located</div> : null}
        </div>
      </div>
    </section>
  );
}
