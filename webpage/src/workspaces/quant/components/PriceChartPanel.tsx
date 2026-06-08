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
  ['crosshair', 'Crosshair', 'M12 4v16M4 12h16'],
  ['trend', 'Trend line', 'M4 17L17 4M6 17h-2v-2M17 6V4h-2'],
  ['hline', 'Horizontal line', 'M4 12h16'],
  ['vline', 'Vertical line', 'M12 4v16'],
  ['ray', 'Ray', 'M4 15l7-7 4 4 4-8M15 4h4v4'],
  ['text', 'Text', 'M5 5h14M12 5v14M9 19h6'],
  ['fib', 'Fib retracement', 'M5 5h14M5 9h14M5 13h14M5 17h14'],
  ['measure', 'Measure', 'M5 17L17 5M7 17H5v-2M17 7V5h-2M8 14l2 2M14 8l2 2'],
  ['brush', 'Brush', 'M7 17c1.5 1 4 0 4-2L17 7l-3-3-6 8c-1.5 0-3 1.5-1 5z'],
  ['magnet', 'Magnet', 'M7 4v7a5 5 0 0010 0V4M7 8h3M14 8h3'],
  ['lock', 'Lock', 'M7 10V8a5 5 0 0110 0v2M6 10h12v9H6z'],
  ['eye', 'Visibility', 'M3 12s3-5 9-5 9 5 9 5-3 5-9 5-9-5-9-5zM12 9a3 3 0 100 6 3 3 0 000-6z'],
  ['delete', 'Delete drawings', 'M7 7h10M10 7V5h4v2M8 7l1 12h6l1-12'],
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
  loadingMessage?: string;
  marketCoverageRows?: number;
  loadedPriceRows?: number;
  backtestRows?: number;
  onRetry?: () => void;
};

type SeriesRefs = {
  lines: Map<string, ISeriesApi<'Line'>>;
  ma: ISeriesApi<'Line'> | null;
  volume: ISeriesApi<'Histogram'> | null;
};

type Drawing = {
  id: string;
  kind: 'trend' | 'ray' | 'hline' | 'vline' | 'measure' | 'text';
  points: Array<{ timestamp: number; price: number }>;
  text?: string;
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

function clampProbability(value: number) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

function nearestPoint(points: PricePoint[], timestamp: number) {
  if (!points.length) return null;
  return points.reduce<PricePoint | null>((best, candidate) => {
    if (!best) return candidate;
    return Math.abs(candidate.timestamp - timestamp) < Math.abs(best.timestamp - timestamp) ? candidate : best;
  }, null);
}

function pointSnapshot(point: PricePoint | null | undefined, latestPoint: PricePoint | null | undefined, maPoint: PricePoint | null | undefined) {
  if (!point) return null;
  const yes = clampProbability(point.yesPrice ?? point.close);
  const no = clampProbability(point.noPrice ?? (1 - yes));
  const latestYes = clampProbability(latestPoint?.yesPrice ?? latestPoint?.close ?? yes);
  const latestNo = clampProbability(latestPoint?.noPrice ?? (1 - latestYes));
  return {
    point,
    yes,
    no,
    yesKind: point.yesPriceKind || 'direct',
    noKind: point.noPriceKind || 'implied',
    ma: maPoint?.close,
    deltaYes: yes - latestYes,
    deltaNo: no - latestNo,
    deltaYesPct: latestYes ? ((yes - latestYes) / latestYes) * 100 : 0,
    deltaNoPct: latestNo ? ((no - latestNo) / latestNo) * 100 : 0,
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

function drawingStorageKey(market: MarketInfo, priceSource: string) {
  return `polydata.quant.drawings.${market.slug}.${priceSource}`;
}

export function PriceChartPanel({
  prices,
  market,
  selectedTradeId,
  signals = [],
  priceSource,
  dataStatus,
  loadingMessage = '',
  marketCoverageRows = 0,
  loadedPriceRows,
  backtestRows = 0,
  onRetry,
}: PriceChartPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<SeriesRefs>({ lines: new Map(), ma: null, volume: null });
  const pointsRef = useRef<PricePoint[]>([]);
  const [hover, setHover] = useState<PricePoint | null>(null);
  const [pinnedPoint, setPinnedPoint] = useState<PricePoint | null>(null);
  const [dataWindowOpen, setDataWindowOpen] = useState(true);
  const [scaleMode, setScaleMode] = useState<ScaleMode>('full');
  const [activeTool, setActiveTool] = useState('cursor');
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [pendingDrawing, setPendingDrawing] = useState<Drawing | null>(null);
  const [drawingsLocked, setDrawingsLocked] = useState(false);
  const [drawingsHidden, setDrawingsHidden] = useState(false);
  const [chartType, setChartType] = useState('Block-close line');
  const [indicatorMode, setIndicatorMode] = useState({ ma: true, ema: false, bands: false, rsi: false, volume: true });
  const [compareMode, setCompareMode] = useState('YES + NO');
  const [layoutMode, setLayoutMode] = useState('1');
  const [replayEnabled, setReplayEnabled] = useState(false);
  const [replayPlaying, setReplayPlaying] = useState(false);
  const [replayIndex, setReplayIndex] = useState<number | null>(null);

  const rawAllPoints = useMemo(() => sortUnique(prices), [prices]);
  const replayCutoff = replayEnabled && replayIndex !== null ? rawAllPoints[Math.min(replayIndex, rawAllPoints.length - 1)]?.timestamp : null;
  const replayPrices = useMemo(() => (
    replayCutoff ? prices.filter((point) => point.timestamp <= replayCutoff) : prices
  ), [prices, replayCutoff]);
  const allPoints = useMemo(() => sortUnique(replayPrices), [replayPrices]);
  const groupedOutcomes = useMemo(() => outcomeGroups(replayPrices), [replayPrices]);
  const yesPoints = useMemo(() => sidePoints(replayPrices, 'YES'), [replayPrices]);
  const primaryPoints = groupedOutcomes[0]?.points || yesPoints || allPoints;
  const latestPoint = primaryPoints[primaryPoints.length - 1] || null;
  const latest = hover || latestPoint;
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
  const inspectPoint = pinnedPoint || hover || latestPoint;
  const inspectMaPoint = inspectPoint ? nearestPoint(maPoints, inspectPoint.timestamp) : null;
  const inspect = pointSnapshot(inspectPoint, latestPoint, inspectMaPoint);
  const markers = useMemo(() => signals.map((signal) => markerPosition(signal, primaryPoints)).filter(Boolean), [primaryPoints, signals]);
  const focusedMarkers = markers.filter((marker) => marker?.signal.tradeId === selectedTradeId);

  useEffect(() => {
    pointsRef.current = primaryPoints;
  }, [primaryPoints]);

  useEffect(() => {
    const raw = window.localStorage.getItem(drawingStorageKey(market, priceSource));
    if (!raw) {
      setDrawings([]);
      return;
    }
    try {
      const parsed = JSON.parse(raw) as Drawing[];
      setDrawings(Array.isArray(parsed) ? parsed : []);
    } catch {
      setDrawings([]);
    }
  }, [market.slug, priceSource]);

  useEffect(() => {
    window.localStorage.setItem(drawingStorageKey(market, priceSource), JSON.stringify(drawings));
  }, [drawings, market, priceSource]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setPinnedPoint(null);
        setPendingDrawing(null);
      }
      if (event.key.toLowerCase() === 'd' && !(event.target instanceof HTMLInputElement)) {
        setDataWindowOpen((current) => !current);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (!replayPlaying || !replayEnabled || !rawAllPoints.length) return undefined;
    const timer = window.setInterval(() => {
      setReplayIndex((current) => Math.min(rawAllPoints.length - 1, (current ?? 0) + 1));
    }, 700);
    return () => window.clearInterval(timer);
  }, [rawAllPoints.length, replayEnabled, replayPlaying]);

  useEffect(() => {
    if (!replayEnabled) return;
    if (replayIndex === null && rawAllPoints.length) setReplayIndex(Math.floor(rawAllPoints.length * 0.25));
  }, [rawAllPoints.length, replayEnabled, replayIndex]);

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

  const drawingPointFromEvent = (event: MouseEvent) => {
    const box = containerRef.current?.getBoundingClientRect();
    if (!box || !primaryPoints.length) return null;
    const ratioX = Math.max(0, Math.min(1, (event.clientX - box.left) / box.width));
    const ratioY = Math.max(0, Math.min(1, (event.clientY - box.top) / box.height));
    const index = Math.min(primaryPoints.length - 1, Math.max(0, Math.round(ratioX * (primaryPoints.length - 1))));
    const snapped = primaryPoints[index];
    return {
      timestamp: snapped?.timestamp ?? 0,
      price: clampProbability(1 - ratioY),
    };
  };

  const pointToScreen = (point: { timestamp: number; price: number }) => {
    const index = primaryPoints.findIndex((row) => Math.floor(row.timestamp) === Math.floor(point.timestamp));
    const x = `${((index >= 0 ? index : 0) / Math.max(1, primaryPoints.length - 1)) * 100}%`;
    const y = `${(1 - clampProbability(point.price)) * 100}%`;
    return { x, y };
  };

  const handleChartClick = (event: MouseEvent) => {
    if (activeTool === 'lock') {
      setDrawingsLocked((current) => !current);
      return;
    }
    if (activeTool === 'eye') {
      setDrawingsHidden((current) => !current);
      return;
    }
    if (activeTool === 'delete') {
      setDrawings([]);
      setPendingDrawing(null);
      return;
    }
    if (drawingsLocked) return;
    const point = drawingPointFromEvent(event);
    if (!point) return;
    if (activeTool === 'cursor' || activeTool === 'crosshair') {
      setPinnedPoint(hover || nearestPoint(primaryPoints, point.timestamp));
      return;
    }
    if (activeTool === 'hline' || activeTool === 'vline') {
      setDrawings((current) => [...current, { id: `${activeTool}-${Date.now()}`, kind: activeTool, points: [point] }]);
      return;
    }
    if (activeTool === 'text') {
      const text = window.prompt('Text note', 'Note') || 'Note';
      setDrawings((current) => [...current, { id: `text-${Date.now()}`, kind: 'text', points: [point], text }]);
      return;
    }
    if (['trend', 'ray', 'measure'].includes(activeTool)) {
      if (!pendingDrawing || pendingDrawing.kind !== activeTool) {
        setPendingDrawing({ id: `${activeTool}-${Date.now()}`, kind: activeTool as Drawing['kind'], points: [point] });
        return;
      }
      setDrawings((current) => [...current, { ...pendingDrawing, points: [...pendingDrawing.points, point] }]);
      setPendingDrawing(null);
    }
  };

  const exportLoadedCsv = () => {
    const rows = allPoints.map((point) => [
      point.timestamp,
      point.outcomeLabel || '',
      point.yesPrice ?? point.close,
      point.noPrice ?? '',
      point.noPriceKind || '',
      point.volume,
      point.source,
    ]);
    const csv = [
      ['block_or_time', 'outcome', 'yes', 'no', 'no_kind', 'volume', 'source'].join(','),
      ...rows.map((row) => row.map((value) => JSON.stringify(String(value ?? ''))).join(',')),
    ].join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `polydata-${market.slug || 'quant'}-prices.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const exportSnapshot = () => {
    const canvas = containerRef.current?.querySelector('canvas');
    if (!(canvas instanceof HTMLCanvasElement)) return;
    const link = document.createElement('a');
    link.href = canvas.toDataURL('image/png');
    link.download = `polydata-${market.slug || 'quant'}-chart.png`;
    link.click();
  };

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
        <div className="qtv-advanced-toolbar" aria-label="Advanced chart controls">
          <select value={chartType} onChange={(event) => setChartType(event.currentTarget.value)}>
            <option>Block-close line</option>
            <option>Line</option>
            <option>Step line</option>
            <option>Area</option>
            <option disabled>Candles requires OHLC</option>
          </select>
          <button className={indicatorMode.ma ? 'active' : ''} type="button" title="Moving average" onClick={() => setIndicatorMode((current) => ({ ...current, ma: !current.ma }))}>MA</button>
          <button className={indicatorMode.ema ? 'active' : ''} type="button" title="EMA scaffold" onClick={() => setIndicatorMode((current) => ({ ...current, ema: !current.ema }))}>EMA</button>
          <button className={indicatorMode.bands ? 'active' : ''} type="button" title="Bollinger band scaffold" onClick={() => setIndicatorMode((current) => ({ ...current, bands: !current.bands }))}>BB</button>
          <button className={indicatorMode.volume ? 'active' : ''} type="button" title="Volume" onClick={() => setIndicatorMode((current) => ({ ...current, volume: !current.volume }))}>Vol</button>
          <select value={compareMode} onChange={(event) => setCompareMode(event.currentTarget.value)}>
            <option>YES + NO</option>
            <option>YES only</option>
            <option>Implied NO</option>
          </select>
          <select value={layoutMode} onChange={(event) => setLayoutMode(event.currentTarget.value)} title="Layout">
            <option value="1">1 chart</option>
            <option value="2v">2 vertical</option>
            <option value="2h">2 horizontal</option>
            <option value="4">4 grid</option>
          </select>
          <button className={replayEnabled ? 'active' : ''} type="button" title="Replay" onClick={() => setReplayEnabled((current) => !current)}>Replay</button>
          <button type="button" title="Alert scaffold">Alert</button>
          <button type="button" title="Snapshot PNG" onClick={exportSnapshot}>Snapshot</button>
          <button type="button" title="Export loaded CSV" onClick={exportLoadedCsv}>CSV</button>
          <button className={dataWindowOpen ? 'active' : ''} type="button" title="Toggle data window (D)" onClick={() => setDataWindowOpen((current) => !current)}>Data</button>
        </div>

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

        {dataStatus === 'price_loading' || dataStatus === 'metadata_loading' || dataStatus === 'partial' ? (
          <div className="qtv-chart-loading-ribbon">
            <b>{loadingMessage || (dataStatus === 'metadata_loading' ? 'Loading market metadata...' : 'Loading price series...')}</b>
            <span>Coverage {marketCoverageRows ? marketCoverageRows.toLocaleString('en-US') : '--'} · Loaded {(loadedPriceRows ?? allPoints.length).toLocaleString('en-US')} · Backtest {backtestRows.toLocaleString('en-US')}</span>
          </div>
        ) : null}

        {dataWindowOpen && inspect ? (
          <div className={`qtv-data-window ${pinnedPoint ? 'pinned' : ''}`}>
            <header>
              <strong>{pinnedPoint ? 'Pinned Data Window' : hover ? 'Crosshair Data Window' : 'Latest Data Window'}</strong>
              {pinnedPoint ? <button type="button" onClick={() => setPinnedPoint(null)}>Clear</button> : null}
            </header>
            <div><span>Market</span><b>{market.title}</b></div>
            <div><span>Block</span><b>{blockLabel(inspect.point.timestamp)}</b></div>
            <div><span>YES</span><b>{fmtPrice(inspect.yes)} <em>{inspect.yesKind}</em></b></div>
            <div><span>NO</span><b>{fmtPrice(inspect.no)} <em>{inspect.noKind}</em></b></div>
            <div><span>MA</span><b>{inspect.ma === undefined ? '--' : fmtPrice(inspect.ma)}</b></div>
            <div><span>Volume</span><b>{inspect.point.volume.toLocaleString('en-US', { maximumFractionDigits: 2 })}</b></div>
            <div><span>Source</span><b>{priceSource}</b></div>
            <div><span>Window</span><b>{allPoints.length.toLocaleString('en-US')} rows · {scaleMode}</b></div>
            <footer>
              <span className={inspect.deltaYes >= 0 ? 'positive' : 'negative'}>Δ YES {formatSigned(inspect.deltaYes)} ({formatSigned(inspect.deltaYesPct, 2)}%)</span>
              <span className={inspect.deltaNo >= 0 ? 'positive' : 'negative'}>Δ NO {formatSigned(inspect.deltaNo)} ({formatSigned(inspect.deltaNoPct, 2)}%)</span>
            </footer>
          </div>
        ) : null}

        {replayEnabled ? (
          <div className="qtv-replay-controls">
            <button type="button" onClick={() => setReplayPlaying((current) => !current)}>{replayPlaying ? 'Pause' : 'Play'}</button>
            <button type="button" onClick={() => setReplayIndex((current) => Math.max(0, (current ?? 0) - 1))}>Step -</button>
            <button type="button" onClick={() => setReplayIndex((current) => Math.min(rawAllPoints.length - 1, (current ?? 0) + 1))}>Step +</button>
            <span>{replayCutoff ? `block ${blockLabel(replayCutoff)}` : 'choose start'}</span>
            <button type="button" onClick={() => { setReplayEnabled(false); setReplayPlaying(false); setReplayIndex(null); }}>Exit</button>
          </div>
        ) : null}

        <div className="qtv-tv-chart" ref={containerRef} onClick={(event) => handleChartClick(event as unknown as MouseEvent)}>
          {!allPoints.length ? (
            <div className="qtv-chart-empty">
              <strong>
                {dataStatus === 'metadata_loading' ? 'Loading market metadata...' : null}
                {dataStatus === 'price_loading' ? 'Loading price series...' : null}
                {dataStatus === 'error' ? 'Price request failed' : null}
                {dataStatus === 'empty' ? 'No price rows found' : null}
                {['idle', 'loading', 'partial', 'ready'].includes(dataStatus) ? 'No real price rows' : null}
              </strong>
              <span>{loadingMessage || 'Try All window, change source, or choose another outcome.'}</span>
              {onRetry ? <button type="button" onClick={onRetry}>Retry</button> : null}
            </div>
          ) : null}
          {!drawingsHidden ? (
            <svg className="qtv-drawing-layer" aria-hidden="true">
              {[...drawings, ...(pendingDrawing ? [pendingDrawing] : [])].map((drawing) => {
                const first = drawing.points[0];
                const second = drawing.points[1] || drawing.points[0];
                if (!first || !second) return null;
                const a = pointToScreen(first);
                const b = pointToScreen(second);
                if (drawing.kind === 'hline') return <line key={drawing.id} x1="0%" x2="100%" y1={a.y} y2={a.y} />;
                if (drawing.kind === 'vline') return <line key={drawing.id} x1={a.x} x2={a.x} y1="0%" y2="100%" />;
                if (drawing.kind === 'text') return <text key={drawing.id} x={a.x} y={a.y}>{drawing.text || 'Note'}</text>;
                return <line key={drawing.id} className={drawing.kind} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />;
              })}
            </svg>
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
          {replayEnabled && replayCutoff ? (
            <div className="qtv-replay-cursor" style={{ left: `${(Math.max(0, primaryPoints.length - 1) / Math.max(1, rawAllPoints.length - 1)) * 100}%` }} />
          ) : null}
          {pinnedPoint ? (
            <div className="qtv-pinned-actions">
              <button type="button">Run backtest from here</button>
              <button type="button" onClick={() => { setReplayEnabled(true); setReplayIndex(Math.max(0, rawAllPoints.findIndex((point) => point.timestamp >= pinnedPoint.timestamp))); }}>Set replay start</button>
              <button type="button" onClick={exportLoadedCsv}>Export window</button>
            </div>
          ) : null}
        </div>
        {layoutMode !== '1' ? (
          <div className={`qtv-layout-scaffold layout-${layoutMode}`}>
            {Array.from({ length: layoutMode === '4' ? 3 : 1 }).map((_, index) => (
              <div key={index}>
                <strong>Synced pane {index + 2}</strong>
                <span>{market.title}</span>
                <em>Crosshair and market synced · configure source/outcome next</em>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
