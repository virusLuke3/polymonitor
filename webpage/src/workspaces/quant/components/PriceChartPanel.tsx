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
import { fmtPrice, fmtProbabilityPercent, formatTime } from '../utils/formatters';

type ScaleMode = 'full' | 'auto' | 'local';
type EventDisplayMode = 'top3' | 'top5' | 'top10' | 'all' | 'selected';
type EventSortMode = 'probability' | 'outcome' | 'volume' | 'change';
type EventSideMode = 'auto' | 'yes' | 'no' | 'both';
type EventLabelMode = 'selected' | 'top' | 'all';
type TooltipMode = 'compact' | 'full';
type DataWindowMode = 'compact' | 'expanded';
type DataWindowDock = 'floating' | 'left' | 'right';
type ChartViewMode = 'raw' | 'normalized' | 'direct' | 'implied';
type RangeSelection = { startX: number; currentX: number } | null;
type LogicalRangeState = { from: number; to: number } | null;
type LogicalRangeLike = LogicalRangeState | undefined;

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
  eventMode?: boolean;
  selectedTokenId?: string;
  selectedOutcomeLabel?: string;
  pinnedOutcomeKeys?: string[];
  hiddenOutcomeKeys?: string[];
  soloOutcomeKey?: string;
  onPinnedOutcomeKeysChange?: (keys: string[]) => void;
  onHiddenOutcomeKeysChange?: (keys: string[]) => void;
  onSoloOutcomeKeyChange?: (key: string) => void;
  onOutcomeSelect?: (tokenId: string, side: 'YES' | 'NO') => void;
  onRetry?: () => void;
  viewportResetKey?: string;
  onViewportModeChange?: (mode: 'preset' | 'custom') => void;
  onVisibleWindowChange?: (windowRange: { fromX: number; toX: number; pointCount: number; viewportWidth: number }) => void;
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

type DataWindowSettings = {
  visible: boolean;
  minimized: boolean;
  mode: DataWindowMode;
  dock: DataWindowDock;
  x?: number;
  y?: number;
};

type OutcomeGroup = {
  key: string;
  label: string;
  fullLabel: string;
  tokenId?: string;
  tokenSide: string;
  order: number;
  points: PricePoint[];
};

const SERIES_COLORS = ['#3b82f6', '#f59e0b', '#22c55e', '#ef4444', '#06b6d4', '#a855f7', '#f97316', '#84cc16', '#ec4899', '#14b8a6', '#eab308', '#94a3b8', '#60a5fa', '#fb7185'];

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

function outcomeKey(point: PricePoint) {
  return point.outcomeKey || point.outcomeShortLabel || point.outcomeLabel || point.tokenSide || point.tokenId || 'YES';
}

function outcomeGroups(points: PricePoint[]): OutcomeGroup[] {
  const groups = new Map<string, PricePoint[]>();
  points.forEach((point) => {
    const key = outcomeKey(point);
    const rows = groups.get(key) || [];
    rows.push(point);
    groups.set(key, rows);
  });
  return Array.from(groups.entries())
    .map(([key, rows], index) => {
      const sorted = sortUnique(rows);
      const sample = sorted[sorted.length - 1] || rows[0];
      return {
        key,
        label: sample?.outcomeShortLabel || sample?.outcomeLabel || key,
        fullLabel: sample?.outcomeFullLabel || sample?.outcomeLabel || key,
        tokenId: sample?.tokenId,
        tokenSide: (sample?.tokenSide || 'YES').toUpperCase(),
        order: index,
        points: sorted,
      };
    })
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
  const byTime = new Map<number, number>();
  points
    .filter((point) => Number.isFinite(point.timestamp))
    .forEach((point) => {
      const key = Math.floor(point.timestamp);
      byTime.set(key, (byTime.get(key) || 0) + Math.max(0, point.volume));
    });
  return Array.from(byTime.entries())
    .sort(([left], [right]) => left - right)
    .map(([timestamp, volume]) => ({
      time: timestamp as Time,
      value: volume,
      color: 'rgba(148,163,184,0.24)',
    }));
}

function formatSigned(value: number, digits = 3) {
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}`;
}

function latestClose(group: { points: PricePoint[] }) {
  return group.points[group.points.length - 1]?.close ?? 0;
}

function priceKindForPoint(point: PricePoint, tokenSide: string) {
  return tokenSide === 'NO' ? point.noPriceKind || 'direct' : point.yesPriceKind || 'direct';
}

function applyChartViewMode(groups: OutcomeGroup[], viewMode: ChartViewMode): OutcomeGroup[] {
  if (viewMode === 'raw') return groups;
  if (viewMode === 'direct' || viewMode === 'implied') {
    return groups
      .map((group) => ({
        ...group,
        points: group.points.filter((point) => priceKindForPoint(point, group.tokenSide) === viewMode),
      }))
      .filter((group) => group.points.length);
  }
  const sumsByBlock = new Map<number, number>();
  groups
    .filter((group) => group.tokenSide === 'YES')
    .forEach((group) => {
      group.points.forEach((point) => {
        const key = Math.floor(point.timestamp);
        sumsByBlock.set(key, (sumsByBlock.get(key) || 0) + Math.max(0, point.close));
      });
    });
  return groups
    .map((group) => ({
      ...group,
      points: group.points.map((point) => {
        const sum = sumsByBlock.get(Math.floor(point.timestamp)) || 0;
        if (group.tokenSide !== 'YES' || sum <= 0) return point;
        const close = Math.max(0, Math.min(1, point.close / sum));
        return {
          ...point,
          close,
          yesPrice: close,
          noPrice: Math.max(0, Math.min(1, 1 - close)),
        };
      }),
    }))
    .filter((group) => group.points.length);
}

function latestVolume(group: { points: PricePoint[] }) {
  return group.points[group.points.length - 1]?.volume ?? 0;
}

function latestChange(group: { points: PricePoint[] }) {
  const latest = group.points[group.points.length - 1]?.close ?? 0;
  const previous = group.points[Math.max(0, group.points.length - 2)]?.close ?? latest;
  return latest - previous;
}

function colorWithOpacity(hex: string, opacity: number) {
  const clean = hex.replace('#', '');
  const value = Number.parseInt(clean.length === 3 ? clean.split('').map((ch) => ch + ch).join('') : clean, 16);
  if (!Number.isFinite(value)) return hex;
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${opacity})`;
}

function persistedState<T extends string>(key: string, fallback: T): T {
  try {
    return (window.localStorage.getItem(key) as T) || fallback;
  } catch {
    return fallback;
  }
}

function persistedStringArray(key: string) {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) || '[]');
    return Array.isArray(parsed) ? parsed.filter((value) => typeof value === 'string') : [];
  } catch {
    return [];
  }
}

function persistedDataWindowSettings(): DataWindowSettings {
  try {
    const parsed = JSON.parse(window.localStorage.getItem('polymonitor.quant.dataWindowSettings') || '{}') as Partial<DataWindowSettings>;
    return {
      visible: typeof parsed.visible === 'boolean' ? parsed.visible : false,
      minimized: typeof parsed.minimized === 'boolean' ? parsed.minimized : false,
      mode: parsed.mode === 'expanded' ? 'expanded' : 'compact',
      dock: parsed.dock === 'left' || parsed.dock === 'right' ? parsed.dock : 'floating',
      x: Number.isFinite(parsed.x) ? Number(parsed.x) : 12,
      y: Number.isFinite(parsed.y) ? Number(parsed.y) : 122,
    };
  } catch {
    return { visible: false, minimized: false, mode: 'compact', dock: 'floating', x: 12, y: 122 };
  }
}

function clampDataWindowPosition(x: number, y: number, bounds?: DOMRect | null) {
  if (!bounds) return { x: Math.max(8, x), y: Math.max(48, y) };
  const maxX = Math.max(8, bounds.width - 240);
  const maxY = Math.max(56, bounds.height - 130);
  return {
    x: Math.max(8, Math.min(maxX, x)),
    y: Math.max(56, Math.min(maxY, y)),
  };
}

function axisPercentFromIndex(index: number, points: PricePoint[], range?: LogicalRangeLike) {
  if (!points.length || index < 0) return null;
  if (range && Number.isFinite(range.from) && Number.isFinite(range.to) && range.to > range.from) {
    return ((index - range.from) / (range.to - range.from)) * 100;
  }
  return (index / Math.max(1, points.length - 1)) * 100;
}

function axisPercentStyle(percent: number | null) {
  if (percent === null || !Number.isFinite(percent) || percent < -6 || percent > 106) return null;
  return `${Math.max(-3, Math.min(103, percent))}%`;
}

function markerPosition(signal: Signal, points: PricePoint[], range?: LogicalRangeLike) {
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
  const left = axisPercentStyle(axisPercentFromIndex(bestIndex, points, range));
  if (!left) return null;
  return {
    signal,
    point,
    index: bestIndex,
    left,
    top: `${Math.max(7, Math.min(84, (1 - point.close) * 100))}%`,
  };
}

function nearestPointIndex(points: PricePoint[], timestamp: number) {
  if (!points.length) return -1;
  let bestIndex = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  points.forEach((point, index) => {
    const distance = Math.abs(point.timestamp - timestamp);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestIndex;
}

function niceBlockStep(rawStep: number) {
  if (!Number.isFinite(rawStep) || rawStep <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const unit = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return Math.max(1, Math.floor(unit * magnitude));
}

function blockAxisTicks(points: PricePoint[], maxTicks = 8, visibleRange?: LogicalRangeLike) {
  if (!points.length) return [];
  const rawFromIndex = visibleRange ? Math.max(0, Math.min(points.length - 1, Math.floor(visibleRange.from))) : 0;
  const rawToIndex = visibleRange ? Math.max(rawFromIndex, Math.min(points.length - 1, Math.ceil(visibleRange.to))) : points.length - 1;
  const visibleSpan = rawToIndex - rawFromIndex;
  const rangeLooksUsable = !visibleRange || visibleSpan >= Math.min(8, Math.max(1, points.length - 1));
  const fromIndex = rangeLooksUsable ? rawFromIndex : 0;
  const toIndex = rangeLooksUsable ? rawToIndex : points.length - 1;
  const visible = points.slice(fromIndex, toIndex + 1);
  const first = Math.floor(visible[0]?.timestamp || points[0]?.timestamp || 0);
  const last = Math.floor(visible[visible.length - 1]?.timestamp || first);
  if (!Number.isFinite(first) || !Number.isFinite(last)) return [];
  if (first === last) {
    return [{ key: first, label: blockLabel(first), left: '0%', edge: 'start' as const, level: 0, major: true }];
  }
  const blockRange = Math.max(1, last - first);
  const step = niceBlockStep(blockRange / Math.max(1, maxTicks - 1));
  const ticks: number[] = [first];
  for (let value = Math.ceil(first / step) * step; value < last; value += step) {
    if (value > first) ticks.push(value);
  }
  ticks.push(last);
  const sorted = Array.from(new Set(ticks)).sort((left, right) => left - right);
  const minGapPercent = maxTicks <= 5 ? 14 : 11;
  const filtered: number[] = [];
  sorted.forEach((value, index) => {
    if (index === 0) {
      filtered.push(value);
      return;
    }
    if (index === sorted.length - 1) {
      const previous = filtered[filtered.length - 1];
      if (previous !== undefined && ((value - first) / blockRange) * 100 - ((previous - first) / blockRange) * 100 < minGapPercent) {
        filtered[filtered.length - 1] = value;
      } else {
        filtered.push(value);
      }
      return;
    }
    const left = ((value - first) / blockRange) * 100;
    const previous = filtered[filtered.length - 1];
    const previousLeft = previous !== undefined ? ((previous - first) / blockRange) * 100 : -100;
    if (filtered.length < maxTicks && left - previousLeft >= minGapPercent && left <= 100 - minGapPercent) {
      filtered.push(value);
    }
  });
  if (filtered[filtered.length - 1] !== last) {
    filtered[filtered.length - 1] = last;
  }
  return filtered.map((value, index) => {
    const left = ((value - first) / blockRange) * 100;
    return {
      key: value,
      label: blockLabel(value),
      left: `${Math.max(0, Math.min(100, left))}%`,
      edge: index === 0 ? 'start' : index === filtered.length - 1 ? 'end' : 'middle',
      level: index % 2,
      major: index === 0 || index === filtered.length - 1 || index % 2 === 0,
    };
  });
}

function normalizeLogicalRange(range: { from: number; to: number } | null): LogicalRangeState {
  if (!range || !Number.isFinite(range.from) || !Number.isFinite(range.to)) return null;
  return { from: range.from, to: range.to };
}

function logicalRangesClose(left: LogicalRangeState, right: LogicalRangeState) {
  if (!left && !right) return true;
  if (!left || !right) return false;
  return Math.abs(left.from - right.from) < 0.02 && Math.abs(left.to - right.to) < 0.02;
}

function clampLogicalRange(range: { from: number; to: number }, totalPoints: number) {
  const fullSpan = Math.max(1, totalPoints - 1);
  const minSpan = Math.min(fullSpan, 8);
  const maxSpan = Math.max(minSpan, fullSpan + 4);
  const rawSpan = Math.max(0.01, range.to - range.from);
  const span = Math.max(minSpan, Math.min(maxSpan, rawSpan));
  const maxRight = fullSpan + 2;
  const minLeft = -2;
  let from = range.from;
  let to = from + span;
  if (from < minLeft) {
    from = minLeft;
    to = from + span;
  }
  if (to > maxRight) {
    to = maxRight;
    from = to - span;
  }
  return { from, to };
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

function pointToScreenSafe(point: PricePoint, points: PricePoint[], range?: LogicalRangeLike) {
  const index = points.findIndex((row) => Math.floor(row.timestamp) === Math.floor(point.timestamp));
  const left = axisPercentStyle(axisPercentFromIndex(index >= 0 ? index : 0, points, range)) || '0%';
  return {
    x: left,
    y: `${Math.max(8, Math.min(86, (1 - clampProbability(point.close)) * 100))}%`,
  };
}

function percentNumber(value: string | undefined) {
  const numeric = Number(String(value || '').replace('%', ''));
  return Number.isFinite(numeric) ? numeric : 0;
}

function robustPriceRange(points: PricePoint[], paddingRatio: number) {
  const values = points
    .map((point) => point.close)
    .filter((value) => Number.isFinite(value) && value >= 0 && value <= 1);
  if (!values.length) return { minValue: 0, maxValue: 1 };
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = Math.max(0.015, max - min);
  const paddedMin = Math.max(0, min - spread * paddingRatio);
  const paddedMax = Math.min(1, max + spread * paddingRatio);
  if (paddedMax - paddedMin < 0.01) {
    const center = (paddedMin + paddedMax) / 2;
    return {
      minValue: Math.max(0, center - 0.005),
      maxValue: Math.min(1, center + 0.005),
    };
  }
  return {
    minValue: paddedMin,
    maxValue: paddedMax,
  };
}

function scaleProvider(mode: ScaleMode, points: PricePoint[], visiblePoints: PricePoint[] = points) {
  if (mode === 'auto') {
    return () => ({ priceRange: robustPriceRange(visiblePoints, 0.28) });
  }
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
      minValue: Math.max(0, min - spread * 0.3),
      maxValue: Math.min(1, max + spread * 0.3),
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
  eventMode = false,
  selectedTokenId = '',
  selectedOutcomeLabel = '',
  pinnedOutcomeKeys,
  hiddenOutcomeKeys,
  soloOutcomeKey,
  onPinnedOutcomeKeysChange,
  onHiddenOutcomeKeysChange,
  onSoloOutcomeKeyChange,
  onOutcomeSelect,
  onRetry,
  viewportResetKey = '',
  onViewportModeChange,
  onVisibleWindowChange,
}: PriceChartPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<SeriesRefs>({ lines: new Map(), ma: null, volume: null });
  const pointsRef = useRef<PricePoint[]>([]);
  const dataWindowDragRef = useRef<{ startX: number; startY: number; baseX: number; baseY: number } | null>(null);
  const suppressViewportModeRef = useRef(false);
  const onVisibleWindowChangeRef = useRef<typeof onVisibleWindowChange>(onVisibleWindowChange);
  const lastWindowNotifyRef = useRef('');
  const visibleLogicalRangeRef = useRef<LogicalRangeState>(null);
  const lastFitRequestKeyRef = useRef('');
  const lastTradeFocusKeyRef = useRef('');
  const onViewportModeChangeRef = useRef(onViewportModeChange);
  const [hover, setHover] = useState<PricePoint | null>(null);
  const [pinnedPoint, setPinnedPoint] = useState<PricePoint | null>(null);
  const [visibleLogicalRange, setVisibleLogicalRange] = useState<LogicalRangeState>(null);
  const [dataWindowSettings, setDataWindowSettings] = useState<DataWindowSettings>(persistedDataWindowSettings);
  const [dataWindowMenuOpen, setDataWindowMenuOpen] = useState(false);
  const [scaleMode, setScaleMode] = useState<ScaleMode>('auto');
  const [activeTool, setActiveTool] = useState('cursor');
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [pendingDrawing, setPendingDrawing] = useState<Drawing | null>(null);
  const [drawingsLocked, setDrawingsLocked] = useState(false);
  const [drawingsHidden, setDrawingsHidden] = useState(false);
  const [chartType, setChartType] = useState('Block-close line');
  const [indicatorMode, setIndicatorMode] = useState({ ma: true, ema: false, bands: false, rsi: false, volume: true });
  const [displayMode, setDisplayMode] = useState<EventDisplayMode>(() => persistedState('polydata.quant.event.displayMode', 'top5'));
  const [eventSortMode, setEventSortMode] = useState<EventSortMode>(() => persistedState('polydata.quant.event.sortMode', 'probability'));
  const [compareMode, setCompareMode] = useState<EventSideMode>(() => persistedState('polydata.quant.event.sideMode', 'auto'));
  const [labelMode, setLabelMode] = useState<EventLabelMode>(() => persistedState('polydata.quant.event.labelMode', 'top'));
  const [tooltipMode, setTooltipMode] = useState<TooltipMode>(() => persistedState('polydata.quant.event.tooltipMode', 'compact'));
  const [chartViewMode, setChartViewMode] = useState<ChartViewMode>(() => persistedState('polydata.quant.chart.viewMode', 'raw'));
  const [showLowProbability, setShowLowProbability] = useState(false);
  const [outcomeManagerOpen, setOutcomeManagerOpen] = useState(false);
  const [outcomeManagerQuery, setOutcomeManagerQuery] = useState('');
  const [layoutMode, setLayoutMode] = useState('1');
  const [internalPinnedOutcomeKeys, setInternalPinnedOutcomeKeys] = useState<string[]>(() => persistedStringArray('polydata.quant.chart.pinnedOutcomes'));
  const [internalHiddenOutcomeKeys, setInternalHiddenOutcomeKeys] = useState<string[]>(() => persistedStringArray('polydata.quant.chart.hiddenOutcomes'));
  const [internalSoloOutcomeKey, setInternalSoloOutcomeKey] = useState<string>('');
  const [rangeZoomEnabled, setRangeZoomEnabled] = useState(false);
  const [rangeSelection, setRangeSelection] = useState<RangeSelection>(null);
  const [replayEnabled, setReplayEnabled] = useState(false);
  const [replayPlaying, setReplayPlaying] = useState(false);
  const [replayIndex, setReplayIndex] = useState<number | null>(null);

  const rawAllPoints = useMemo(() => sortUnique(prices), [prices]);
  const fitRequestKey = `${market.slug}|${priceSource}|${scaleMode}|${viewportResetKey}`;
  const replayCutoff = replayEnabled && replayIndex !== null ? rawAllPoints[Math.min(replayIndex, rawAllPoints.length - 1)]?.timestamp : null;
  const replayPrices = useMemo(() => (
    replayCutoff ? prices.filter((point) => point.timestamp <= replayCutoff) : prices
  ), [prices, replayCutoff]);
  const rawGroupedOutcomes = useMemo(() => outcomeGroups(replayPrices), [replayPrices]);
  const yesOutcomeCount = useMemo(() => rawGroupedOutcomes.filter((group) => group.tokenSide === 'YES').length, [rawGroupedOutcomes]);
  const effectiveSideMode = compareMode === 'auto' ? 'yes' : compareMode;
  const sideFilteredOutcomes = useMemo(() => rawGroupedOutcomes.filter((group) => {
    if (effectiveSideMode === 'both') return true;
    if (effectiveSideMode === 'yes') return group.tokenSide === 'YES';
    if (effectiveSideMode === 'no') return group.tokenSide === 'NO';
    return true;
  }), [effectiveSideMode, rawGroupedOutcomes]);
  const viewFilteredOutcomes = useMemo(() => applyChartViewMode(sideFilteredOutcomes, chartViewMode), [chartViewMode, sideFilteredOutcomes]);
  const effectivePinnedOutcomeKeys = pinnedOutcomeKeys ?? internalPinnedOutcomeKeys;
  const effectiveHiddenOutcomeKeys = hiddenOutcomeKeys ?? internalHiddenOutcomeKeys;
  const effectiveSoloOutcomeKey = soloOutcomeKey ?? internalSoloOutcomeKey;
  const displayedOutcomeCount = eventMode ? sideFilteredOutcomes.length : (yesOutcomeCount || sideFilteredOutcomes.length);
  const selectedGroup = useMemo(() => viewFilteredOutcomes.find((group) => (
    (selectedTokenId && group.tokenId === selectedTokenId)
    || (selectedOutcomeLabel && group.label === selectedOutcomeLabel)
  )) || viewFilteredOutcomes[0] || null, [selectedOutcomeLabel, selectedTokenId, viewFilteredOutcomes]);
  const sortedOutcomes = useMemo(() => viewFilteredOutcomes.slice().sort((left, right) => {
    if (eventSortMode === 'outcome') return left.order - right.order;
    if (eventSortMode === 'volume') return latestVolume(right) - latestVolume(left);
    if (eventSortMode === 'change') return Math.abs(latestChange(right)) - Math.abs(latestChange(left));
    return latestClose(right) - latestClose(left);
  }), [eventSortMode, viewFilteredOutcomes]);
  const visibleOutcomeGroups = useMemo(() => {
    const hidden = new Set(effectiveHiddenOutcomeKeys);
    const pinned = new Set(effectivePinnedOutcomeKeys);
    const available = sortedOutcomes.filter((group) => !hidden.has(group.key));
    if (effectiveSoloOutcomeKey) {
      const solo = available.find((group) => group.key === effectiveSoloOutcomeKey);
      return solo ? [solo] : available.slice(0, 1);
    }
    if (!eventMode) return available;
    if (displayMode === 'selected') return selectedGroup ? [selectedGroup] : available.slice(0, 1);
    const topLimit = displayMode === 'top3' ? 3 : displayMode === 'top10' ? 10 : displayMode === 'all' ? sortedOutcomes.length : 5;
    const visible = new Map<string, (typeof sortedOutcomes)[number]>();
    available.slice(0, topLimit).forEach((group) => visible.set(group.key, group));
    available.filter((group) => pinned.has(group.key)).forEach((group) => visible.set(group.key, group));
    if (showLowProbability) {
      available.filter((group) => latestClose(group) >= 0.05).forEach((group) => visible.set(group.key, group));
    }
    if (selectedGroup) visible.set(selectedGroup.key, selectedGroup);
    return Array.from(visible.values()).sort((left, right) => {
      if (eventSortMode === 'outcome') return left.order - right.order;
      return latestClose(right) - latestClose(left);
    });
  }, [displayMode, effectiveHiddenOutcomeKeys, effectivePinnedOutcomeKeys, effectiveSoloOutcomeKey, eventMode, eventSortMode, selectedGroup, showLowProbability, sortedOutcomes]);
  const allPoints = useMemo(() => visibleOutcomeGroups.flatMap((group) => group.points).sort((left, right) => left.timestamp - right.timestamp), [visibleOutcomeGroups]);
  const primaryPoints = selectedGroup?.points || visibleOutcomeGroups[0]?.points || allPoints;
  const latestPoint = primaryPoints[primaryPoints.length - 1] || null;
  const latest = hover || latestPoint;
  const previous = primaryPoints[Math.max(0, primaryPoints.length - 2)];
  const delta = latest && previous ? latest.close - previous.close : 0;
  const deltaPct = latest && previous?.close ? (delta / previous.close) * 100 : 0;
  const minPrice = primaryPoints.reduce((min, point) => Math.min(min, point.close), Number.POSITIVE_INFINITY);
  const maxPrice = primaryPoints.reduce((max, point) => Math.max(max, point.close), Number.NEGATIVE_INFINITY);
  const volumeTotal = allPoints.reduce((sum, point) => sum + (Number.isFinite(point.volume) ? point.volume : 0), 0);
  const selectedLatest = selectedGroup ? latestClose(selectedGroup) : latest?.close || 0;
  const allYesSum = rawGroupedOutcomes.filter((group) => group.tokenSide === 'YES').reduce((sum, group) => sum + latestClose(group), 0);
  const visibleYesSum = visibleOutcomeGroups.filter((group) => group.tokenSide === 'YES').reduce((sum, group) => sum + latestClose(group), 0);
  const sumWarning = eventMode && Math.abs(allYesSum - 1) > 0.08;
  const maPoints = useMemo(() => {
    const closes = primaryPoints.map((point) => point.close);
    const ma = movingAverage(closes, Math.min(40, Math.max(3, Math.floor(primaryPoints.length / 20))));
    return primaryPoints.map((point, index) => ({ ...point, close: ma[index] ?? point.close }));
  }, [primaryPoints]);
  const dataWindowPoint = pinnedPoint || hover || latestPoint;
  const dataWindowMaPoint = dataWindowPoint ? nearestPoint(maPoints, dataWindowPoint.timestamp) : null;
  const dataWindowInspect = pointSnapshot(dataWindowPoint, latestPoint, dataWindowMaPoint);
  const hoverMaPoint = hover ? nearestPoint(maPoints, hover.timestamp) : null;
  const hoverInspect = pointSnapshot(hover, latestPoint, hoverMaPoint);
  const hoverScreen = hover ? pointToScreenSafe(hover, primaryPoints, visibleLogicalRange) : null;
  const hoverTooltipSide = percentNumber(hoverScreen?.x) > 68 ? 'left-side' : '';
  const hoverBlockAxisLeft = hoverScreen?.x || '0%';
  const blockTicks = useMemo(() => blockAxisTicks(primaryPoints, 8, visibleLogicalRange), [primaryPoints, visibleLogicalRange]);
  const managerOutcomes = useMemo(() => {
    const query = outcomeManagerQuery.trim().toLowerCase();
    return sortedOutcomes.filter((group) => {
      if (!query) return true;
      return `${group.fullLabel} ${group.label} ${group.tokenId || ''} ${group.tokenSide}`.toLowerCase().includes(query);
    });
  }, [outcomeManagerQuery, sortedOutcomes]);
  const hiddenOutcomeCount = effectiveHiddenOutcomeKeys.length;
  const pinnedOutcomeCount = effectivePinnedOutcomeKeys.length;
  const markers = useMemo(() => signals.map((signal) => markerPosition(signal, primaryPoints, visibleLogicalRange)).filter(Boolean), [primaryPoints, signals, visibleLogicalRange]);
  const focusedMarkers = markers.filter((marker) => marker?.signal.tradeId === selectedTradeId);
  const selectedTradeSignals = useMemo(() => (
    selectedTradeId ? signals.filter((signal) => signal.tradeId === selectedTradeId).sort((left, right) => left.timestamp - right.timestamp) : []
  ), [selectedTradeId, signals]);
  const selectedTradeEntrySignal = selectedTradeSignals.find((signal) => signal.action === 'OPEN' || signal.action === 'BUY') || selectedTradeSignals[0] || null;
  const selectedTradeExitSignal = selectedTradeSignals.find((signal) => signal.action === 'CLOSE' || signal.action === 'SELL') || selectedTradeSignals[selectedTradeSignals.length - 1] || null;
  const selectedTradeFocus = useMemo(() => {
    if (!selectedTradeId || !selectedTradeSignals.length || !primaryPoints.length) return null;
    const startSignal = selectedTradeEntrySignal || selectedTradeSignals[0];
    const endSignal = selectedTradeExitSignal || selectedTradeSignals[selectedTradeSignals.length - 1];
    if (!startSignal || !endSignal) return null;
    const startIndex = nearestPointIndex(primaryPoints, startSignal.timestamp);
    const endIndex = nearestPointIndex(primaryPoints, endSignal.timestamp);
    if (startIndex < 0 || endIndex < 0) return null;
    const leftIndex = Math.min(startIndex, endIndex);
    const rightIndex = Math.max(startIndex, endIndex);
    const entryPoint = primaryPoints[startIndex] || null;
    const exitPoint = primaryPoints[endIndex] || null;
    const entryLeftPercent = axisPercentFromIndex(startIndex, primaryPoints, visibleLogicalRange);
    const exitLeftPercent = axisPercentFromIndex(endIndex, primaryPoints, visibleLogicalRange);
    const left = axisPercentFromIndex(leftIndex, primaryPoints, visibleLogicalRange);
    const right = axisPercentFromIndex(rightIndex, primaryPoints, visibleLogicalRange);
    const entryLeft = axisPercentStyle(entryLeftPercent);
    const exitLeft = axisPercentStyle(exitLeftPercent);
    const bandLeft = axisPercentStyle(left);
    const bandRight = axisPercentStyle(right);
    const pnl = (endSignal.price - startSignal.price) * (startSignal.size || endSignal.size || 0);
    if (!entryLeft || !exitLeft || !bandLeft || !bandRight || left === null || right === null) return null;
    return {
      id: selectedTradeId,
      startSignal,
      endSignal,
      startIndex,
      endIndex,
      entryPoint,
      exitPoint,
      entryLeft,
      exitLeft,
      bandLeft,
      bandWidth: `${Math.max(0.15, Math.min(100, Math.abs(right - left)))}%`,
      pnl,
      bars: Math.abs(endIndex - startIndex),
    };
  }, [primaryPoints, selectedTradeEntrySignal, selectedTradeExitSignal, selectedTradeId, selectedTradeSignals, visibleLogicalRange]);
  const rangeSelectionStyle = rangeSelection && containerRef.current ? {
    left: `${Math.min(rangeSelection.startX, rangeSelection.currentX) - containerRef.current.getBoundingClientRect().left}px`,
    width: `${Math.abs(rangeSelection.currentX - rangeSelection.startX)}px`,
  } : undefined;

  function setChartVisibleRange(range: { from: number; to: number }, viewportMode: 'preset' | 'custom' = 'custom') {
    const next = clampLogicalRange(range, primaryPoints.length);
    chartRef.current?.timeScale().setVisibleLogicalRange(next);
    visibleLogicalRangeRef.current = next;
    setVisibleLogicalRange((current) => (logicalRangesClose(current, next) ? current : next));
    onViewportModeChange?.(viewportMode);
  }

  function fitData() {
    suppressViewportModeRef.current = true;
    chartRef.current?.timeScale().fitContent();
    visibleLogicalRangeRef.current = null;
    setVisibleLogicalRange(null);
    onViewportModeChange?.('preset');
    window.setTimeout(() => {
      suppressViewportModeRef.current = false;
    }, 0);
  }

  function zoomLogicalRange(factor: number) {
    const scale = chartRef.current?.timeScale();
    if (!scale) return;
    const range = scale.getVisibleLogicalRange();
    if (!range) return;
    const center = (range.from + range.to) / 2;
    const half = ((range.to - range.from) * factor) / 2;
    setChartVisibleRange({ from: center - half, to: center + half });
  }

  function logicalIndexFromClientX(clientX: number) {
    const box = containerRef.current?.getBoundingClientRect();
    if (!box) return 0;
    const ratio = Math.max(0, Math.min(1, (clientX - box.left) / box.width));
    const range = normalizeLogicalRange(chartRef.current?.timeScale().getVisibleLogicalRange() || null)
      || visibleLogicalRangeRef.current
      || { from: 0, to: Math.max(1, primaryPoints.length - 1) };
    return range.from + ratio * Math.max(1, range.to - range.from);
  }

  function commitRangeZoom(selection: RangeSelection) {
    if (!selection) return;
    const left = Math.min(selection.startX, selection.currentX);
    const right = Math.max(selection.startX, selection.currentX);
    if (Math.abs(right - left) < 18) return;
    setChartVisibleRange({
      from: logicalIndexFromClientX(left),
      to: logicalIndexFromClientX(right),
    });
  }

  function handleChartWheel(event: WheelEvent) {
    if (rangeZoomEnabled || primaryPoints.length < 2) return;
    event.preventDefault();
    event.stopPropagation();

    const scale = chartRef.current?.timeScale();
    const box = containerRef.current?.getBoundingClientRect();
    if (!scale || !box) return;
    const current = normalizeLogicalRange(scale.getVisibleLogicalRange()) || { from: 0, to: Math.max(1, primaryPoints.length - 1) };
    const span = Math.max(1, current.to - current.from);
    const isTrackpadPan = Math.abs(event.deltaX) > Math.abs(event.deltaY) || event.shiftKey;

    if (isTrackpadPan) {
      const delta = Math.abs(event.deltaX) > 0 ? event.deltaX : event.deltaY;
      const shift = (delta / Math.max(260, box.width)) * span;
      setChartVisibleRange({ from: current.from + shift, to: current.to + shift });
      return;
    }

    const cursorRatio = Math.max(0, Math.min(1, (event.clientX - box.left) / box.width));
    const anchor = current.from + span * cursorRatio;
    const wheelMagnitude = Math.min(3, Math.max(0.25, Math.abs(event.deltaY) / 120));
    const zoomFactor = (event.deltaY > 0 ? 1.18 : 0.84) ** wheelMagnitude;
    const nextSpan = span * zoomFactor;
    setChartVisibleRange({
      from: anchor - nextSpan * cursorRatio,
      to: anchor + nextSpan * (1 - cursorRatio),
    });
  }

  const updatePinnedOutcomeKeys = (next: string[] | ((current: string[]) => string[])) => {
    const value = typeof next === 'function' ? next(effectivePinnedOutcomeKeys) : next;
    setInternalPinnedOutcomeKeys(value);
    onPinnedOutcomeKeysChange?.(value);
  };

  const updateHiddenOutcomeKeys = (next: string[] | ((current: string[]) => string[])) => {
    const value = typeof next === 'function' ? next(effectiveHiddenOutcomeKeys) : next;
    setInternalHiddenOutcomeKeys(value);
    onHiddenOutcomeKeysChange?.(value);
  };

  const updateSoloOutcomeKey = (next: string | ((current: string) => string)) => {
    const value = typeof next === 'function' ? next(effectiveSoloOutcomeKey) : next;
    setInternalSoloOutcomeKey(value);
    onSoloOutcomeKeyChange?.(value);
  };

  const togglePinnedOutcome = (key: string) => {
    updatePinnedOutcomeKeys((current) => (current.includes(key) ? current.filter((item) => item !== key) : [...current, key]));
    updateHiddenOutcomeKeys((current) => current.filter((item) => item !== key));
  };

  const toggleHiddenOutcome = (key: string) => {
    updateHiddenOutcomeKeys((current) => (current.includes(key) ? current.filter((item) => item !== key) : [...current, key]));
    updatePinnedOutcomeKeys((current) => current.filter((item) => item !== key));
    if (effectiveSoloOutcomeKey === key) updateSoloOutcomeKey('');
  };

  const resetOutcomeVisibility = () => {
    updateHiddenOutcomeKeys([]);
    updatePinnedOutcomeKeys([]);
    updateSoloOutcomeKey('');
    setShowLowProbability(false);
  };

  useEffect(() => {
    window.localStorage.setItem('polydata.quant.event.displayMode', displayMode);
    window.localStorage.setItem('polydata.quant.event.sortMode', eventSortMode);
    window.localStorage.setItem('polydata.quant.event.sideMode', compareMode);
    window.localStorage.setItem('polydata.quant.event.labelMode', labelMode);
    window.localStorage.setItem('polydata.quant.event.tooltipMode', tooltipMode);
    window.localStorage.setItem('polydata.quant.chart.viewMode', chartViewMode);
  }, [chartViewMode, compareMode, displayMode, eventSortMode, labelMode, tooltipMode]);

  useEffect(() => {
    window.localStorage.setItem('polydata.quant.chart.pinnedOutcomes', JSON.stringify(effectivePinnedOutcomeKeys));
    window.localStorage.setItem('polydata.quant.chart.hiddenOutcomes', JSON.stringify(effectiveHiddenOutcomeKeys));
  }, [effectiveHiddenOutcomeKeys, effectivePinnedOutcomeKeys]);

  useEffect(() => {
    window.localStorage.setItem('polymonitor.quant.dataWindowSettings', JSON.stringify(dataWindowSettings));
  }, [dataWindowSettings]);

  useEffect(() => {
    const onPointerMove = (event: PointerEvent) => {
      const drag = dataWindowDragRef.current;
      if (!drag) return;
      const bounds = containerRef.current?.parentElement?.getBoundingClientRect();
      const next = clampDataWindowPosition(
        drag.baseX + event.clientX - drag.startX,
        drag.baseY + event.clientY - drag.startY,
        bounds,
      );
      setDataWindowSettings((current) => ({ ...current, dock: 'floating', x: next.x, y: next.y }));
    };
    const onPointerUp = () => {
      dataWindowDragRef.current = null;
    };
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerUp);
    return () => {
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      window.removeEventListener('pointercancel', onPointerUp);
    };
  }, []);

  useEffect(() => {
    pointsRef.current = primaryPoints;
  }, [primaryPoints]);

  useEffect(() => {
    onViewportModeChangeRef.current = onViewportModeChange;
  }, [onViewportModeChange]);

  useEffect(() => {
    onVisibleWindowChangeRef.current = onVisibleWindowChange;
  }, [onVisibleWindowChange]);

  useEffect(() => {
    if (!selectedTradeFocus || !chartRef.current || !primaryPoints.length) return;
    const focusKey = `${selectedTradeFocus.id}|${selectedTradeFocus.startIndex}|${selectedTradeFocus.endIndex}|${primaryPoints.length}`;
    if (lastTradeFocusKeyRef.current === focusKey) return;
    lastTradeFocusKeyRef.current = focusKey;
    const span = Math.max(1, Math.abs(selectedTradeFocus.endIndex - selectedTradeFocus.startIndex));
    const padding = Math.max(8, Math.ceil(span * 0.45), Math.ceil(primaryPoints.length * 0.018));
    suppressViewportModeRef.current = true;
    chartRef.current.timeScale().setVisibleLogicalRange({
      from: Math.max(0, Math.min(selectedTradeFocus.startIndex, selectedTradeFocus.endIndex) - padding),
      to: Math.min(primaryPoints.length - 1, Math.max(selectedTradeFocus.startIndex, selectedTradeFocus.endIndex) + padding),
    });
    setPinnedPoint(selectedTradeFocus.entryPoint || nearestPoint(primaryPoints, selectedTradeFocus.startSignal.timestamp));
    onViewportModeChangeRef.current?.('custom');
    window.setTimeout(() => {
      suppressViewportModeRef.current = false;
    }, 0);
  }, [primaryPoints, selectedTradeFocus]);

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
        if (rangeSelection || rangeZoomEnabled) {
          setRangeSelection(null);
          setRangeZoomEnabled(false);
          return;
        }
        if (document.activeElement instanceof HTMLElement && document.activeElement.closest('.qtv-data-window')) {
          setPinnedPoint(null);
          setDataWindowSettings((current) => ({ ...current, visible: false, minimized: false }));
        } else {
          setPinnedPoint(null);
        }
        setPendingDrawing(null);
      }
      if (event.key.toLowerCase() === 'd' && !(event.target instanceof HTMLInputElement)) {
        event.preventDefault();
        if (event.shiftKey) {
          if (hover) {
            setPinnedPoint(hover);
            setDataWindowSettings((current) => ({ ...current, visible: true, minimized: false }));
          } else {
            setPinnedPoint(null);
          }
          return;
        }
        setDataWindowSettings((current) => ({ ...current, visible: !current.visible, minimized: false }));
      }
      if (event.key.toLowerCase() === 'f' && !(event.target instanceof HTMLInputElement)) {
        event.preventDefault();
        fitData();
      }
      if ((event.key === '+' || event.key === '=') && !(event.target instanceof HTMLInputElement)) {
        event.preventDefault();
        zoomLogicalRange(0.72);
      }
      if (event.key === '-' && !(event.target instanceof HTMLInputElement)) {
        event.preventDefault();
        zoomLogicalRange(1.35);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [rangeSelection, rangeZoomEnabled]);

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
        visible: false,
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
        priceFormatter: (value: number) => fmtProbabilityPercent(value),
        timeFormatter: (time: Time) => priceSource.includes('block') ? `block ${blockLabel(Number(time))}` : formatTime(Number(time)),
      },
      crosshair: {
        horzLine: { color: 'rgba(148,163,184,0.42)', labelBackgroundColor: '#1f2937' },
        vertLine: { color: 'rgba(148,163,184,0.28)', labelBackgroundColor: '#1f2937' },
      },
      handleScroll: {
        mouseWheel: false,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: false,
        pinch: true,
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
    });
    observer.observe(container);

    const handleVisibleLogicalRange = (range: { from: number; to: number } | null) => {
      const normalized = normalizeLogicalRange(range);
      visibleLogicalRangeRef.current = normalized;
      setVisibleLogicalRange((current) => (logicalRangesClose(current, normalized) ? current : normalized));
      if (suppressViewportModeRef.current || !normalized || pointsRef.current.length < 2) return;
      const span = Math.max(0, normalized.to - normalized.from);
      const fullSpan = Math.max(1, pointsRef.current.length - 1);
      const coversFullDataset = normalized.from <= 1.5 && normalized.to >= fullSpan - 1.5 && span >= fullSpan - 3;
      onViewportModeChange?.(coversFullDataset ? 'preset' : 'custom');
      if (!coversFullDataset && onVisibleWindowChangeRef.current) {
        const currentPoints = pointsRef.current;
        const fromIndex = Math.max(0, Math.min(currentPoints.length - 1, Math.floor(normalized.from)));
        const toIndex = Math.max(0, Math.min(currentPoints.length - 1, Math.ceil(normalized.to)));
        const fromPoint = currentPoints[fromIndex];
        const toPoint = currentPoints[toIndex];
        const fromX = Number(fromPoint?.timestamp);
        const toX = Number(toPoint?.timestamp);
        if (Number.isFinite(fromX) && Number.isFinite(toX)) {
          const nextKey = `${Math.floor(fromX)}:${Math.ceil(toX)}:${toIndex - fromIndex}`;
          if (nextKey !== lastWindowNotifyRef.current) {
            lastWindowNotifyRef.current = nextKey;
            const width = Math.max(360, Math.floor(containerRef.current?.clientWidth || 1200));
            onVisibleWindowChangeRef.current({
              fromX,
              toX,
              pointCount: Math.max(1, toIndex - fromIndex + 1),
              viewportWidth: width,
            });
          }
        }
      }
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(handleVisibleLogicalRange);

    return () => {
      observer.disconnect();
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(handleVisibleLogicalRange);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = { lines: new Map(), ma: null, volume: null };
    };
  }, [priceSource, scaleMode]);

  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series.ma || !series.volume) return;
    const activeKeys = new Set(visibleOutcomeGroups.map((group) => group.key));
    Array.from(series.lines.entries()).forEach(([key, line]) => {
      if (!activeKeys.has(key)) {
        chart.removeSeries(line);
        series.lines.delete(key);
      }
    });
    visibleOutcomeGroups.forEach((group, index) => {
      const autoscaleInfoProvider = scaleProvider(scaleMode, group.points, allPoints);
      const baseColor = SERIES_COLORS[group.order % SERIES_COLORS.length] || '#3b82f6';
      const isSelected = selectedGroup?.key === group.key;
      const isTopLabel = index < 3;
      const opacity = !eventMode || isSelected ? 1 : displayMode === 'all' && index >= 5 ? 0.32 : 0.82;
      const lineWidth = !eventMode ? 2 : isSelected ? 3 : displayMode === 'all' && index >= 5 ? 1 : 2;
      const showPriceLine = !eventMode
        || isSelected
        || labelMode === 'all'
        || (labelMode === 'top' && isTopLabel);
      let line = series.lines.get(group.key);
      if (!line) {
        line = chart.addSeries(LineSeries, {
          color: colorWithOpacity(baseColor, opacity),
          lineWidth,
          priceLineVisible: showPriceLine,
          priceLineColor: baseColor,
          priceLineWidth: 1,
          title: group.fullLabel,
          autoscaleInfoProvider,
        });
        series.lines.set(group.key, line);
      }
      line.applyOptions({
        color: colorWithOpacity(baseColor, opacity),
        lineWidth,
        priceLineVisible: showPriceLine,
        priceLineColor: baseColor,
        title: `${group.fullLabel} ${fmtProbabilityPercent(latestClose(group))}`,
        autoscaleInfoProvider,
      });
      line.setData(lineData(group.points));
    });
    series.ma.setData(indicatorMode.ma ? lineData(maPoints) : []);
    series.volume.setData(indicatorMode.volume ? volumeData(allPoints) : []);
    if (allPoints.length && lastFitRequestKeyRef.current !== fitRequestKey) {
      suppressViewportModeRef.current = true;
      chart.timeScale().fitContent();
      visibleLogicalRangeRef.current = null;
      setVisibleLogicalRange(null);
      lastFitRequestKeyRef.current = fitRequestKey;
      onViewportModeChange?.('preset');
      window.setTimeout(() => {
        suppressViewportModeRef.current = false;
      }, 0);
    }
  }, [allPoints, displayMode, eventMode, fitRequestKey, indicatorMode.ma, indicatorMode.volume, labelMode, maPoints, scaleMode, selectedGroup, visibleOutcomeGroups]);

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
    const x = axisPercentStyle(axisPercentFromIndex(index >= 0 ? index : 0, primaryPoints, visibleLogicalRange)) || '0%';
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
      setDataWindowSettings((current) => ({ ...current, visible: true, minimized: false, mode: current.mode || 'compact' }));
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

  const hasLoadedPrices = allPoints.length > 0;
  const isLoadingPrices = ['loading', 'metadata_loading', 'price_loading', 'warming', 'partial'].includes(dataStatus) && !hasLoadedPrices;
  const rowsText = isLoadingPrices
    ? 'Loading...'
    : hasLoadedPrices
      ? allPoints.length.toLocaleString('en-US')
      : dataStatus === 'empty'
        ? 'No price rows'
        : '--';
  const selectedText = hasLoadedPrices && selectedGroup ? `${selectedGroup.fullLabel} ${fmtPrice(selectedLatest)}` : '--';
  const sumText = eventMode && hasLoadedPrices ? fmtPrice(chartViewMode === 'normalized' ? 1 : allYesSum) : '--';
  const visibleSumText = eventMode && hasLoadedPrices ? fmtPrice(visibleYesSum) : '--';
  const latestPriceText = latest && hasLoadedPrices ? fmtPrice(latest.close) : '--';
  const loadingTitle = dataStatus === 'metadata_loading'
    ? 'Loading market metadata'
    : dataStatus === 'price_loading'
      ? eventMode ? 'Loading event price series' : 'Loading market price series'
      : dataStatus === 'warming'
        ? 'Building historical price tile'
      : dataStatus === 'partial'
        ? 'Partial coverage loaded'
        : dataStatus === 'error'
          ? 'Price request failed'
          : dataStatus === 'empty'
            ? 'No price rows found'
            : 'Waiting for real price rows';
  const updateDataWindow = (patch: Partial<DataWindowSettings>) => {
    setDataWindowSettings((current) => ({ ...current, ...patch }));
  };
  const startDataWindowDrag = (event: PointerEvent) => {
    if ((event.target as HTMLElement | null)?.closest('button')) return;
    event.preventDefault();
    const base = clampDataWindowPosition(dataWindowSettings.x ?? 12, dataWindowSettings.y ?? 122, containerRef.current?.parentElement?.getBoundingClientRect());
    dataWindowDragRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      baseX: base.x,
      baseY: base.y,
    };
    setDataWindowSettings((current) => ({ ...current, dock: 'floating', x: base.x, y: base.y }));
  };
  const dataWindowStyle = dataWindowSettings.dock === 'floating'
    ? {
      left: `${dataWindowSettings.x ?? 12}px`,
      top: `${dataWindowSettings.y ?? 122}px`,
    }
    : undefined;

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
          <div className="qtv-toolbar-group">
            <span>Chart</span>
            <select value={chartType} onChange={(event) => setChartType(event.currentTarget.value)}>
              <option>Block-close line</option>
              <option>Line</option>
              <option>Step line</option>
              <option>Area</option>
              <option disabled>Candles requires OHLC</option>
            </select>
            <button type="button" title="Fit visible data (F)" onClick={fitData}>Fit</button>
            <button type="button" title="Zoom in (+)" onClick={() => zoomLogicalRange(0.72)}>+</button>
            <button type="button" title="Zoom out (-)" onClick={() => zoomLogicalRange(1.35)}>-</button>
            <button
              className={rangeZoomEnabled ? 'active' : ''}
              type="button"
              title="Drag on chart to box zoom"
              onClick={() => {
                setRangeZoomEnabled((current) => !current);
                setRangeSelection(null);
              }}
            >
              Range
            </button>
          </div>
          <div className="qtv-toolbar-group">
            <span>Indicators</span>
            <button className={indicatorMode.ma ? 'active' : ''} type="button" title="Moving average" onClick={() => setIndicatorMode((current) => ({ ...current, ma: !current.ma }))}>MA</button>
            <button className={indicatorMode.ema ? 'active' : ''} type="button" title="EMA is queued for the next indicator pass" disabled>EMA</button>
            <button className={indicatorMode.bands ? 'active' : ''} type="button" title="Bollinger bands are queued for the next indicator pass" disabled>BB</button>
            <button className={indicatorMode.volume ? 'active' : ''} type="button" title="Volume" onClick={() => setIndicatorMode((current) => ({ ...current, volume: !current.volume }))}>Vol</button>
          </div>
          {eventMode ? (
            <div className="qtv-toolbar-group">
              <span>Outcomes</span>
              <select value={displayMode} onChange={(event) => setDisplayMode(event.currentTarget.value as EventDisplayMode)} title="Visible outcomes">
                <option value="top3">Top 3</option>
                <option value="top5">Top 5</option>
                <option value="top10">Top 10</option>
                <option value="all">All</option>
                <option value="selected">Selected</option>
              </select>
              <select value={eventSortMode} onChange={(event) => setEventSortMode(event.currentTarget.value as EventSortMode)} title="Outcome sort">
                <option value="probability">Probability</option>
                <option value="outcome">Outcome order</option>
                <option value="volume">Volume</option>
                <option value="change">Change</option>
              </select>
              <button
                className={outcomeManagerOpen ? 'active' : ''}
                type="button"
                title="Manage outcome lines"
                onClick={() => setOutcomeManagerOpen((current) => !current)}
              >
                Manage
              </button>
            </div>
          ) : null}
          <details className="qtv-toolbar-group qtv-display-menu">
            <summary>Display</summary>
            <div>
              <label>Side<select value={compareMode} onChange={(event) => setCompareMode(event.currentTarget.value as EventSideMode)}>
                <option value="auto">Auto side</option>
                <option value="yes">YES</option>
                <option value="no">NO</option>
                <option value="both">YES + NO</option>
              </select></label>
              {eventMode ? (
                <>
                  <label>Labels<select value={labelMode} onChange={(event) => setLabelMode(event.currentTarget.value as EventLabelMode)} title="Right labels">
                    <option value="selected">Selected labels</option>
                    <option value="top">Top labels</option>
                    <option value="all">All labels</option>
                  </select></label>
                  <label>Tooltip<select value={tooltipMode} onChange={(event) => setTooltipMode(event.currentTarget.value as TooltipMode)} title="Tooltip mode">
                    <option value="compact">Compact</option>
                    <option value="full">Full</option>
                  </select></label>
                  <label>View<select value={chartViewMode} onChange={(event) => setChartViewMode(event.currentTarget.value as ChartViewMode)} title="Price view mode">
                    <option value="raw">Raw probability</option>
                    <option value="normalized">Normalized event share</option>
                    <option value="direct">Direct only</option>
                    <option value="implied">Implied only</option>
                  </select></label>
                  <button className={showLowProbability ? 'active' : ''} type="button" title="Show low-probability outcomes" onClick={() => setShowLowProbability((current) => !current)}>Low probability</button>
                  <button type="button" title="Reset pinned, hidden, and solo outcome lines" onClick={resetOutcomeVisibility}>Reset lines</button>
                </>
              ) : null}
              <label>Layout<select value={layoutMode} onChange={(event) => setLayoutMode(event.currentTarget.value)} title="Layout">
                <option value="1">Single chart</option>
                <option value="2v">2 vertical</option>
                <option value="2h">2 horizontal</option>
                <option value="4">4 grid</option>
              </select></label>
            </div>
          </details>
          <div className="qtv-toolbar-group">
            <span>Actions</span>
            <button className={replayEnabled ? 'active' : ''} type="button" title="Replay" onClick={() => setReplayEnabled((current) => !current)}>Replay</button>
            <button type="button" title="Alert scaffold">Alert</button>
            <button type="button" title="Snapshot PNG" onClick={exportSnapshot}>Snapshot</button>
            <button type="button" title="Export loaded CSV" onClick={exportLoadedCsv}>CSV</button>
            <span className="qtv-data-control">
              <button
                className={dataWindowSettings.visible ? 'active' : ''}
                type="button"
                title="Data Window"
                onClick={() => {
                  updateDataWindow({ visible: !dataWindowSettings.visible, minimized: false });
                  setDataWindowMenuOpen(false);
                }}
              >
                Data{pinnedPoint ? ' •' : ''}
              </button>
              <button className={dataWindowMenuOpen ? 'active' : ''} type="button" title="Data Window menu" onClick={() => setDataWindowMenuOpen((current) => !current)}>▾</button>
              {dataWindowMenuOpen ? (
                <div className="qtv-data-menu">
                  <button type="button" onClick={() => updateDataWindow({ visible: true, minimized: false })}>Show Data Window</button>
                  <button type="button" onClick={() => updateDataWindow({ visible: false, minimized: false })}>Hide Data Window</button>
                  <button type="button" onClick={() => updateDataWindow({ mode: 'compact', visible: true, minimized: false })}>Compact</button>
                  <button type="button" onClick={() => updateDataWindow({ mode: 'expanded', visible: true, minimized: false })}>Expanded</button>
                  <button type="button" onClick={() => updateDataWindow({ dock: 'floating', visible: true, minimized: false })}>Floating</button>
                  <button type="button" onClick={() => updateDataWindow({ dock: 'left', visible: true, minimized: false })}>Dock left</button>
                  <button type="button" onClick={() => updateDataWindow({ dock: 'right', visible: true, minimized: false })}>Dock right</button>
                  <button type="button" onClick={() => setPinnedPoint(null)}>Clear pinned point</button>
                </div>
              ) : null}
            </span>
          </div>
        </div>

        <div className="qtv-chart-info">
          <div className="qtv-chart-meta">
            <strong>{market.title}</strong>
            <span>{market.category} · {eventMode ? `${displayedOutcomeCount} outcomes` : 'outcome probability'} · {priceSource}</span>
            <div className="qtv-indicator-legend">
              <span>Rows <b>{rowsText}</b></span>
              <span>View <b>{chartViewMode}</b></span>
              <span>Range <i>{hasLoadedPrices ? pointLabel(primaryPoints[0], priceSource) : '--'}</i> <em>{hasLoadedPrices ? pointLabel(primaryPoints[primaryPoints.length - 1], priceSource) : '--'}</em></span>
              <span>Volume <b>{hasLoadedPrices ? volumeTotal.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '--'}</b></span>
              <span>Selected <b title={selectedGroup?.fullLabel}>{selectedText}</b></span>
              {eventMode ? (
                <span title="Binary market prices may not sum exactly to 100% due to spread, stale data, independent markets, fees, or direct/implied price differences.">
                  Sum <b className={sumWarning && hasLoadedPrices ? 'negative' : ''}>{sumText}</b>
                  <em>visible {visibleSumText}</em>
                </span>
              ) : null}
            </div>
            <div className="qtv-outcome-legend">
              {visibleOutcomeGroups.slice(0, 8).map((group) => {
                const point = group.points[group.points.length - 1];
                const isSelected = selectedGroup?.key === group.key;
                const isPinned = effectivePinnedOutcomeKeys.includes(group.key);
                const isSolo = effectiveSoloOutcomeKey === group.key;
                return (
                  <span
                    key={group.key}
                    className={`qtv-legend-item ${isSelected ? 'active' : ''} ${isPinned ? 'pinned' : ''} ${isSolo ? 'solo' : ''}`}
                    title={group.fullLabel}
                  >
                    <button
                      type="button"
                      onClick={() => {
                        if (group.tokenId) onOutcomeSelect?.(group.tokenId, group.tokenSide === 'NO' ? 'NO' : 'YES');
                      }}
                    >
                      <i style={{ backgroundColor: SERIES_COLORS[group.order % SERIES_COLORS.length] }} />
                      <span>{group.fullLabel}</span> <b>{fmtPrice(point?.close || 0)}</b>
                    </button>
                    <button className={isPinned ? 'active micro' : 'micro'} type="button" title={isPinned ? 'Unpin outcome line' : 'Pin outcome line'} onClick={() => togglePinnedOutcome(group.key)}>P</button>
                    <button className={isSolo ? 'active micro' : 'micro'} type="button" title={isSolo ? 'Clear solo outcome' : 'Solo outcome'} onClick={() => updateSoloOutcomeKey(isSolo ? '' : group.key)}>S</button>
                    <button className="micro danger" type="button" title="Hide outcome line" onClick={() => toggleHiddenOutcome(group.key)}>H</button>
                  </span>
                );
              })}
              {eventMode && sortedOutcomes.length > visibleOutcomeGroups.length ? (
                <button type="button" onClick={() => setDisplayMode('all')}>+{sortedOutcomes.length - visibleOutcomeGroups.length} more</button>
              ) : null}
            </div>
          </div>
          <div className="qtv-ohlc">
            <span>Block {latest ? blockLabel(latest.timestamp) : '--'}</span>
            <span>Price {latestPriceText}</span>
            <span>Min {Number.isFinite(minPrice) ? fmtPrice(minPrice) : '--'}</span>
            <span>Max {Number.isFinite(maxPrice) ? fmtPrice(maxPrice) : '--'}</span>
            <b className={delta >= 0 ? 'positive' : 'negative'}>{hasLoadedPrices ? `${formatSigned(delta)} (${formatSigned(deltaPct, 2)}%)` : '--'}</b>
          </div>
          <div className="qtv-scale-switch" aria-label="Chart scale mode">
            {SCALE_MODES.map(([mode, label]) => (
              <button key={mode} className={scaleMode === mode ? 'active' : ''} type="button" onClick={() => setScaleMode(mode)}>{label}</button>
            ))}
          </div>
        </div>

        {eventMode && outcomeManagerOpen ? (
          <div className="qtv-outcome-manager">
            <header>
              <div>
                <strong>Outcome Manager</strong>
                <span>{visibleOutcomeGroups.length.toLocaleString('en-US')} visible · {pinnedOutcomeCount.toLocaleString('en-US')} pinned · {hiddenOutcomeCount.toLocaleString('en-US')} hidden</span>
              </div>
              <button type="button" title="Close outcome manager" onClick={() => setOutcomeManagerOpen(false)}>Close</button>
            </header>
            <div className="qtv-outcome-manager-search">
              <input
                value={outcomeManagerQuery}
                placeholder="Search outcomes, token IDs, sides"
                onInput={(event) => setOutcomeManagerQuery(event.currentTarget.value)}
              />
              <button type="button" onClick={() => setDisplayMode('all')}>Show all</button>
              <button type="button" onClick={resetOutcomeVisibility}>Reset</button>
            </div>
            <div className="qtv-outcome-manager-list">
              {managerOutcomes.map((group) => {
                const latestGroupPoint = group.points[group.points.length - 1];
                const isSelected = selectedGroup?.key === group.key;
                const isVisible = visibleOutcomeGroups.some((visibleGroup) => visibleGroup.key === group.key);
                const isPinned = effectivePinnedOutcomeKeys.includes(group.key);
                const isHidden = effectiveHiddenOutcomeKeys.includes(group.key);
                const isSolo = effectiveSoloOutcomeKey === group.key;
                return (
                  <div
                    key={`manager-${group.key}`}
                    className={`${isSelected ? 'selected' : ''} ${isVisible ? 'visible' : ''} ${isHidden ? 'hidden' : ''}`}
                  >
                    <button
                      type="button"
                      title={group.fullLabel}
                      onClick={() => {
                        if (group.tokenId) onOutcomeSelect?.(group.tokenId, group.tokenSide === 'NO' ? 'NO' : 'YES');
                      }}
                    >
                      <i style={{ backgroundColor: SERIES_COLORS[group.order % SERIES_COLORS.length] }} />
                      <span>{group.fullLabel}</span>
                      <b>{fmtPrice(latestGroupPoint?.close || 0)}</b>
                    </button>
                    <em>{group.tokenSide}</em>
                    <button className={isPinned ? 'active' : ''} type="button" onClick={() => togglePinnedOutcome(group.key)}>{isPinned ? 'Pinned' : 'Pin'}</button>
                    <button className={isSolo ? 'active' : ''} type="button" onClick={() => updateSoloOutcomeKey(isSolo ? '' : group.key)}>{isSolo ? 'Solo on' : 'Solo'}</button>
                    <button className={isHidden ? 'danger active' : 'danger'} type="button" onClick={() => toggleHiddenOutcome(group.key)}>{isHidden ? 'Hidden' : 'Hide'}</button>
                  </div>
                );
              })}
              {!managerOutcomes.length ? (
                <div className="empty">
                  <strong>No outcomes matched</strong>
                  <span>Clear the search query or switch side/view filters.</span>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {((!hasLoadedPrices && (dataStatus === 'price_loading' || dataStatus === 'metadata_loading' || dataStatus === 'warming' || dataStatus === 'partial' || dataStatus === 'loading'))
          || (hasLoadedPrices && (dataStatus === 'warming' || dataStatus === 'partial' || dataStatus === 'price_loading'))) ? (
          <div className="qtv-chart-loading-ribbon">
            <b>{loadingMessage || loadingTitle}</b>
            <span>Outcomes {eventMode ? displayedOutcomeCount.toLocaleString('en-US') : '--'} · Source {priceSource}</span>
            <span>Coverage {marketCoverageRows ? marketCoverageRows.toLocaleString('en-US') : '--'} · Loaded {hasLoadedPrices ? (loadedPriceRows ?? allPoints.length).toLocaleString('en-US') : 'Loading...'} · Backtest {backtestRows ? backtestRows.toLocaleString('en-US') : '--'}</span>
          </div>
        ) : null}

        {dataWindowSettings.visible && dataWindowSettings.minimized ? (
          <button
            className={`qtv-data-window-chip dock-${dataWindowSettings.dock}`}
            type="button"
            onClick={() => updateDataWindow({ minimized: false, visible: true })}
          >
            Data Window {pinnedPoint ? 'Pinned' : 'Latest'}
          </button>
        ) : null}

        {dataWindowSettings.visible && !dataWindowSettings.minimized && dataWindowInspect ? (
          <div
            className={`qtv-data-window ${pinnedPoint ? 'pinned' : ''} ${dataWindowSettings.mode} dock-${dataWindowSettings.dock}`}
            style={dataWindowStyle}
            tabIndex={0}
          >
            <header onPointerDown={(event) => startDataWindowDrag(event as unknown as PointerEvent)}>
              <strong>{dataWindowSettings.mode === 'compact' ? 'Data Window' : 'Expanded Data Window'}</strong>
              <i>{pinnedPoint ? 'Pinned' : hover ? 'Hover' : 'Latest'}</i>
              <button type="button" title="Minimize" onClick={() => updateDataWindow({ minimized: true })}>_</button>
              {pinnedPoint ? <button type="button" title="Clear pinned point" onClick={() => setPinnedPoint(null)}>Clear</button> : null}
              <button type="button" title="Close" onClick={() => updateDataWindow({ visible: false, minimized: false })}>×</button>
            </header>
            <div><span>Block</span><b>{blockLabel(dataWindowInspect.point.timestamp)}</b></div>
            <div>
              <span>Outcome</span>
              <b title={dataWindowInspect.point.outcomeFullLabel || dataWindowInspect.point.outcomeLabel || selectedGroup?.fullLabel}>
                {dataWindowInspect.point.outcomeFullLabel || dataWindowInspect.point.outcomeLabel || selectedGroup?.fullLabel || 'Outcome'}
              </b>
            </div>
            <div><span>YES</span><b>{fmtPrice(dataWindowInspect.yes)} <em>{dataWindowInspect.yesKind}</em></b></div>
            <div><span>NO</span><b>{fmtPrice(dataWindowInspect.no)} <em>{dataWindowInspect.noKind}</em></b></div>
            <div><span>Source</span><b>{priceSource}</b></div>
            {visibleOutcomeGroups.slice(0, 3).map((group) => {
              const point = nearestPoint(group.points, dataWindowInspect.point.timestamp);
              return (
                <div key={group.key} title={group.fullLabel}>
                  <span>{group.fullLabel}</span>
                  <b>{fmtPrice(point?.close ?? latestClose(group))}</b>
                </div>
              );
            })}
            {dataWindowSettings.mode === 'expanded' ? (
              <>
                <div><span>Market</span><b>{market.title}</b></div>
                <div><span>MA</span><b>{dataWindowInspect.ma === undefined ? '--' : fmtPrice(dataWindowInspect.ma)}</b></div>
                <div><span>Volume</span><b>{dataWindowInspect.point.volume.toLocaleString('en-US', { maximumFractionDigits: 2 })}</b></div>
                <div><span>Window</span><b>{allPoints.length.toLocaleString('en-US')} rows · {scaleMode}</b></div>
                <footer>
                  <span className={dataWindowInspect.deltaYes >= 0 ? 'positive' : 'negative'}>Δ YES {formatSigned(dataWindowInspect.deltaYes)} ({formatSigned(dataWindowInspect.deltaYesPct, 2)}%)</span>
                  <span className={dataWindowInspect.deltaNo >= 0 ? 'positive' : 'negative'}>Δ NO {formatSigned(dataWindowInspect.deltaNo)} ({formatSigned(dataWindowInspect.deltaNoPct, 2)}%)</span>
                </footer>
              </>
            ) : null}
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

        <div
          className={`qtv-tv-chart ${rangeZoomEnabled ? 'range-enabled' : ''}`}
          ref={containerRef}
          onWheel={(event) => handleChartWheel(event as unknown as WheelEvent)}
          onPointerDown={(event) => {
            const shouldRangeZoom = rangeZoomEnabled || event.shiftKey || event.altKey;
            if (!shouldRangeZoom) return;
            event.preventDefault();
            setRangeSelection({ startX: event.clientX, currentX: event.clientX });
          }}
          onPointerMove={(event) => {
            if (!rangeSelection) return;
            setRangeSelection({ ...rangeSelection, currentX: event.clientX });
          }}
          onPointerUp={() => {
            if (!rangeSelection) return;
            commitRangeZoom(rangeSelection);
            setRangeSelection(null);
            setRangeZoomEnabled(false);
          }}
          onPointerCancel={() => setRangeSelection(null)}
          onClick={(event) => {
            if (rangeZoomEnabled || rangeSelection) return;
            handleChartClick(event as unknown as MouseEvent);
          }}
        >
          {!allPoints.length ? (
            <div className="qtv-chart-empty">
              <strong>{loadingTitle}</strong>
              <span>{loadingMessage || 'Preparing event metadata and block-close coverage.'}</span>
              <dl>
                <div><dt>Outcomes</dt><dd>{eventMode ? displayedOutcomeCount.toLocaleString('en-US') : '--'}</dd></div>
                <div><dt>Source</dt><dd>{priceSource}</dd></div>
                <div><dt>Coverage</dt><dd>{marketCoverageRows ? marketCoverageRows.toLocaleString('en-US') : '--'}</dd></div>
                <div><dt>Loaded rows</dt><dd>{isLoadingPrices ? 'Loading...' : rowsText}</dd></div>
              </dl>
              <div className="qtv-chart-empty-actions">
                {onRetry ? <button type="button" onClick={onRetry}>Retry</button> : null}
                <button type="button" onClick={() => setDisplayMode('all')}>Show members</button>
                <button type="button" onClick={() => setScaleMode('full')}>Full scale</button>
              </div>
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
          {selectedTradeFocus ? (
            <>
              <div className="qtv-trade-focus-band" style={{ left: selectedTradeFocus.bandLeft, width: selectedTradeFocus.bandWidth }} />
              <div className="qtv-trade-focus-marker-line entry" style={{ left: selectedTradeFocus.entryLeft }} />
              <div className="qtv-trade-focus-marker-line exit" style={{ left: selectedTradeFocus.exitLeft }} />
              <div className="qtv-trade-focus-card">
                <header>
                  <strong>{selectedTradeFocus.id}</strong>
                  <button type="button" onClick={fitData}>Reset view</button>
                </header>
                <dl>
                  <div><dt>Entry</dt><dd>{blockLabel(selectedTradeFocus.startSignal.timestamp)} · {fmtPrice(selectedTradeFocus.startSignal.price)}</dd></div>
                  <div><dt>Exit</dt><dd>{blockLabel(selectedTradeFocus.endSignal.timestamp)} · {fmtPrice(selectedTradeFocus.endSignal.price)}</dd></div>
                  <div><dt>Bars</dt><dd>{selectedTradeFocus.bars.toLocaleString('en-US')}</dd></div>
                  <div><dt>Move</dt><dd className={selectedTradeFocus.endSignal.price >= selectedTradeFocus.startSignal.price ? 'positive' : 'negative'}>{formatSigned(selectedTradeFocus.endSignal.price - selectedTradeFocus.startSignal.price)}</dd></div>
                </dl>
              </div>
            </>
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
          {focusedMarkers.length && !selectedTradeFocus ? <div className="qtv-trade-focus-pill">{selectedTradeId} entry / exit located</div> : null}
          {rangeSelectionStyle ? <div className="qtv-range-selection" style={rangeSelectionStyle} /> : null}
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
          {hoverInspect && hoverScreen ? (
            <>
              <div className="qtv-hover-crosshair-x" style={{ left: hoverScreen.x }} />
              <div className="qtv-hover-crosshair-y" style={{ top: hoverScreen.y }} />
              <div className="qtv-hover-price-tag" style={{ top: hoverScreen.y }}>
                <span>{fmtPrice(hoverInspect.yes)}</span>
                <b>{blockLabel(hoverInspect.point.timestamp)}</b>
              </div>
            </>
          ) : null}
          {hoverInspect && hoverScreen && (!pinnedPoint || Math.floor(pinnedPoint.timestamp) !== Math.floor(hoverInspect.point.timestamp)) ? (
            <div className={`qtv-hover-tooltip ${tooltipMode} ${hoverTooltipSide}`} style={{ left: hoverScreen.x, top: hoverScreen.y }}>
              <strong>{hoverInspect.point.outcomeFullLabel || hoverInspect.point.outcomeLabel || selectedGroup?.fullLabel || 'Outcome'}</strong>
              <span>Block {blockLabel(hoverInspect.point.timestamp)}</span>
              <b>YES {fmtPrice(hoverInspect.yes)} · NO {fmtPrice(hoverInspect.no)}</b>
              {visibleOutcomeGroups.slice(0, tooltipMode === 'full' ? 8 : 5).map((group) => {
                const point = nearestPoint(group.points, hoverInspect.point.timestamp);
                return (
                  <em key={group.key} title={group.fullLabel}>
                    <i style={{ backgroundColor: SERIES_COLORS[group.order % SERIES_COLORS.length] }} />
                    <span>{group.fullLabel}</span>
                    <b>{fmtPrice(point?.close ?? latestClose(group))}</b>
                  </em>
                );
              })}
            </div>
          ) : null}
        </div>
        {priceSource.includes('block') && hasLoadedPrices ? (
          <div className="qtv-block-tick-axis" aria-label="Visible block number axis">
            {blockTicks.map((tick) => (
              <span key={tick.key} className={`${tick.edge} ${tick.major ? 'major' : 'minor'} level-${tick.level}`} style={{ left: tick.left }}>
                <i />
                <b>{tick.label}</b>
              </span>
            ))}
            {hover ? <strong style={{ left: hoverBlockAxisLeft }}>Block {blockLabel(hover.timestamp)}</strong> : null}
          </div>
        ) : (
          <div className="qtv-block-tick-axis empty" aria-hidden="true" />
        )}
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
