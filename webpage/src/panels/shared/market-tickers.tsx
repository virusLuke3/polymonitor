import type { RuntimeMarketTicker } from '@/types';

export function tickerTone(item: RuntimeMarketTicker) {
  const changePercent = Number(item.changePercent);
  if (!Number.isFinite(changePercent) || changePercent === 0) return 'flat';
  return changePercent > 0 ? 'up' : 'down';
}

export function averageChange(items: RuntimeMarketTicker[]) {
  const changes = items.map((item) => Number(item.changePercent)).filter((value) => Number.isFinite(value));
  if (!changes.length) return null;
  return changes.reduce((sum, value) => sum + value, 0) / changes.length;
}

export function topMover(items: RuntimeMarketTicker[]) {
  return items.reduce<RuntimeMarketTicker | null>((top, item) => {
    const move = Math.abs(Number(item.changePercent));
    if (!Number.isFinite(move)) return top;
    if (!top) return item;
    return move > Math.abs(Number(top.changePercent)) ? item : top;
  }, null);
}

export function sortTickers(items: RuntimeMarketTicker[], sortIndex: Map<string, number>) {
  return [...items].sort((left, right) => {
    const leftIndex = sortIndex.get(left.symbol) ?? Number.MAX_SAFE_INTEGER;
    const rightIndex = sortIndex.get(right.symbol) ?? Number.MAX_SAFE_INTEGER;
    if (leftIndex !== rightIndex) return leftIndex - rightIndex;
    return left.label.localeCompare(right.label);
  });
}

export function commoditySparkline(points: RuntimeMarketTicker['points'], color: string) {
  const clean = (points || [])
    .map((point, index) => ({ index, value: Number(point.value) }))
    .filter((point) => Number.isFinite(point.value));
  if (clean.length < 2) return null;

  const width = 60;
  const height = 18;
  const min = Math.min(...clean.map((point) => point.value));
  const max = Math.max(...clean.map((point) => point.value));
  const span = max - min || 1;
  const path = clean
    .map((point, index) => {
      const x = (point.index / Math.max(clean.length - 1, 1)) * width;
      const y = height - ((point.value - min) / span) * height;
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="mini-sparkline" preserveAspectRatio="none" aria-hidden="true">
      <path d={path} fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export function formatCommodityChange(changePercent?: number | null) {
  if (changePercent == null || !Number.isFinite(Number(changePercent))) return '--';
  const numeric = Number(changePercent);
  return `${numeric > 0 ? '+' : ''}${numeric.toFixed(2)}%`;
}
