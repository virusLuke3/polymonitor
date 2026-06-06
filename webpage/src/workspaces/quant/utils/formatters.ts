import type { MetricStatus } from '../types';

export function toNumber(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

export function fmtPrice(value: unknown) {
  return toNumber(value).toFixed(3);
}

export function fmtPercent(value: unknown) {
  const numeric = toNumber(value);
  const sign = numeric > 0 ? '+' : '';
  return `${sign}${numeric.toFixed(2)}%`;
}

export function fmtCurrency(value: unknown) {
  const numeric = toNumber(value);
  const sign = numeric > 0 ? '+' : '';
  return `${sign}${numeric.toLocaleString('en-US', { maximumFractionDigits: 2 })} USDC`;
}

export function fmtCompact(value: unknown) {
  return toNumber(value).toLocaleString('en-US', { maximumFractionDigits: 2 });
}

export function statusClass(value: number): MetricStatus {
  if (value > 0) return 'positive';
  if (value < 0) return 'negative';
  return 'neutral';
}

export function formatTime(timestamp: number) {
  const date = new Date(timestamp * 1000);
  return date.toISOString().slice(0, 16).replace('T', ' ');
}

export function downloadText(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
