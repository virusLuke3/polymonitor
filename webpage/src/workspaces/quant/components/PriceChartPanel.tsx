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

type ScaleMode = 'full' | 'auto' | 'local';

const DRAW_TOOLS = [
  ['cursor', 'Cursor', 'M5 4l10 8-5 1.5L8 18 5 4z'],
  ['trend', 'Trend line', 'M4 17L17 4M6 17h-2v-2M17 6V4h-2'],
  ['ray', 'Ray', 'M4 15l7-7 4 4 4-8M15 4h4v4'],
  ['text', 'Text', 'M5 5h14M12 5v14M9 19h6'],
  ['fib', 'Fib retracement', 'M5 5h14M5 9h14M5 13h14M5 17h14'],
  ['brush', 'Brush', 'M7 17c1.5 1 4 0 4-2L17 7l-3-3-6 8c-1.5 0-3 1.5-1 5z'],
  ['magnet', 'Magnet', 'M7 4v7a5 5 0 0010 0V4M7 8h3M14 8h3'],
  ['lock', 'Lock', 'M7 10V8a5 5 0 0110 0v2M6 10h12v9H6z'],
  ['eye', 'Visibility', 'M3 12s3-5 9-5 9 5 9 5-3 5-9 5-9-5-9-5zM12 9a3 3 0 100 6 3 3 0 000-6z'],
] as const;

const SCALE_MODES: Array<[ScaleMode, string]> = [
  ['full', 'Full'],
  ['auto', 'Auto'],
  ['local', 'Local'],
];

type PriceChartPanelProps = {
  prices: PricePoint[];
  market: MarketInfo;
  selectedTradeId: string | null;
  signals?: Signal[];
  priceSource: string;
  dataStatus: DataStatus;
};

type SeriesRefs = {
  lines: Map<string, ISeriesApi<'Line'>>;
  ma: ISeriesApi<'Line'> | null;
  volume: ISeriesApi<'Histogram'> | null;
};

const SERIES_COLORS = ['#22c55e', '#3b82f6', '#f59e0b', '#06b6d4', '#ef4444', '#a855f7', '#f97316', '#84cc16'];

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

function outcomeKey(point: PricePoint) {
  return point.outcomeLabel || point.tokenSide || point.tokenId || 'YES';
}

function outcomeGroups(points: PricePoint[]) {
  const groups = new Map<string, PricePoint[]>();
  points.forEach((point) => {
    const key = outcomeKey(point);
    const rows = groups.get(key) || [];
    rows.push(point);
    groups.set(key, rows);
  });
  return Array.from(groups.entries())
    .map(([label, rows]) => ({ label, points: sortUnique(rows) }))
    .filter((group) => group.points.length)
    .sort((left, right) => {
      const leftLatest = left.points[left.points.length - 1]?.close ?? 0;
      const rightLatest = right.points[right.points.length - 1]?.close ?? 0;
      return rightLatest - leftLatest;
    });
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

function scaleProvider(mode: ScaleMode, points: PricePoint[]) {
  if (mode === 'auto') return undefined;
  if (mode === 'full' || !points.length) {
    return () => ({ priceRange: { minValue: 0, maxValue: 1 } });
  }
  const min = points.reduce((value, point) => Math.min(value, point.close), Number.POSITIVE_INFINITY);
  const max = points.reduce((value, point) => Math.max(value, point.close), Number.NEGATIVE_INFINITY);
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    return () => ({ priceRange: { minValue: 0, maxValue: 1 } });
  }
  const spread = Math.max(0.01, max - min);
  return () => ({
    priceRange: {
      minValue: Math.max(0, min - spread * 0.35),
      maxValue: Math.min(1, max + spread * 0.35),
    },
  });
}

function ToolIcon({ path }: { path: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d={path} />
    </svg>
  );
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
  const seriesRef = useRef<SeriesRefs>({ lines: new Map(), ma: null, volume: null });
  const pointsRef = useRef<PricePoint[]>([]);
  const [hover, setHover] = useState<PricePoint | null>(null);
  const [scaleMode, setScaleMode] = useState<ScaleMode>('full');
  const [activeTool, setActiveTool] = useState('cursor');

  const allPoints = useMemo(() => sortUnique(prices), [prices]);
  const groupedOutcomes = useMemo(() => outcomeGroups(prices), [prices]);
  const yesPoints = useMemo(() => sidePoints(prices, 'YES'), [prices]);
  const primaryPoints = groupedOutcomes[0]?.points || yesPoints || allPoints;
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
    seriesRef.current = { lines: new Map(), ma, volume };
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
      seriesRef.current = { lines: new Map(), ma: null, volume: null };
    };
  }, [priceSource, scaleMode]);

  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series.ma || !series.volume) return;
    const activeLabels = new Set(groupedOutcomes.map((group) => group.label));
    Array.from(series.lines.entries()).forEach(([label, line]) => {
      if (!activeLabels.has(label)) {
        chart.removeSeries(line);
        series.lines.delete(label);
      }
    });
    groupedOutcomes.forEach((group, index) => {
      const autoscaleInfoProvider = scaleProvider(scaleMode, group.points);
      let line = series.lines.get(group.label);
      if (!line) {
        line = chart.addSeries(LineSeries, {
          color: SERIES_COLORS[index % SERIES_COLORS.length],
          lineWidth: 2,
          priceLineVisible: index === 0,
          priceLineColor: SERIES_COLORS[index % SERIES_COLORS.length],
          priceLineWidth: 1,
          title: group.label,
          ...(autoscaleInfoProvider ? { autoscaleInfoProvider } : {}),
        });
        series.lines.set(group.label, line);
      }
      line.applyOptions({
        color: SERIES_COLORS[index % SERIES_COLORS.length],
        priceLineVisible: index === 0,
        priceLineColor: SERIES_COLORS[index % SERIES_COLORS.length],
        ...(autoscaleInfoProvider ? { autoscaleInfoProvider } : {}),
      });
      line.setData(lineData(group.points));
    });
    series.ma.setData(lineData(maPoints));
    series.volume.setData(volumeData(allPoints));
    chart.timeScale().fitContent();
  }, [allPoints, groupedOutcomes, maPoints, scaleMode]);

  return (
    <section className="qtv-chart-shell">
      <aside className="qtv-draw-rail" aria-label="Chart drawing tools">
        {DRAW_TOOLS.map(([id, label, path]) => (
          <button
            key={id}
            className={activeTool === id ? 'active' : ''}
            type="button"
            title={label}
            aria-label={label}
            onClick={() => setActiveTool(id)}
          >
            <ToolIcon path={path} />
          </button>
        ))}
      </aside>

      <div className="qtv-chart-stack">
        <div className="qtv-chart-info">
          <div className="qtv-chart-meta">
            <strong>{market.title}</strong>
            <span>{market.category} - outcome probabilities - {priceSource}</span>
            <div className="qtv-indicator-legend">
              <span>Rows <b>{allPoints.length.toLocaleString('en-US')}</b></span>
              <span>Range <i>{pointLabel(primaryPoints[0], priceSource)}</i> <em>{pointLabel(primaryPoints[primaryPoints.length - 1], priceSource)}</em></span>
              <span>Volume <b>{volumeTotal.toLocaleString('en-US', { maximumFractionDigits: 2 })}</b></span>
              <span>Latest YES <b>{fmtPrice(latest?.close || 0)}</b></span>
            </div>
            <div className="qtv-outcome-legend">
              {groupedOutcomes.slice(0, 8).map((group, index) => {
                const point = group.points[group.points.length - 1];
                return (
                  <span key={group.label}>
                    <i style={{ backgroundColor: SERIES_COLORS[index % SERIES_COLORS.length] }} />
                    {group.label} <b>{fmtPrice(point?.close || 0)}</b>
                  </span>
                );
              })}
            </div>
          </div>
          <div className="qtv-ohlc">
            <span>Block {latest ? blockLabel(latest.timestamp) : '--'}</span>
            <span>Price {fmtPrice(latest?.close || 0)}</span>
            <span>Min {Number.isFinite(minPrice) ? fmtPrice(minPrice) : '--'}</span>
            <span>Max {Number.isFinite(maxPrice) ? fmtPrice(maxPrice) : '--'}</span>
            <b className={delta >= 0 ? 'positive' : 'negative'}>{formatSigned(delta)} ({formatSigned(deltaPct, 2)}%)</b>
          </div>
          <div className="qtv-scale-switch" aria-label="Chart scale mode">
            {SCALE_MODES.map(([mode, label]) => (
              <button key={mode} className={scaleMode === mode ? 'active' : ''} type="button" onClick={() => setScaleMode(mode)}>{label}</button>
            ))}
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
