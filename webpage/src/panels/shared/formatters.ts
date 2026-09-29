function formatPercent(value?: string | number | null) {
  if (value === null || value === undefined || value === '') return '--';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return `${(numeric * 100).toFixed(1)}%`;
}

function formatCompact(value?: string | number | null) {
  if (value === null || value === undefined || value === '') return '--';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(numeric);
}

function formatCurrencyCompact(value?: string | number | null) {
  if (value === null || value === undefined || value === '') return '--';
  return `$${formatCompact(value)}`;
}

function formatSignedPercent(value?: string | number | null) {
  if (value === null || value === undefined || value === '') return '--';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  const sign = numeric > 0 ? '+' : '';
  return `${sign}${(numeric * 100).toFixed(1)}%`;
}

function signedClass(value?: string | number | null) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric === 0) return 'flat';
  return numeric > 0 ? 'up' : 'down';
}

function formatDate(value?: string | null) {
  if (!value) return '--';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('en-US', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatRelative(value?: string | null) {
  if (!value) return '--';
  const parsed = new Date(value);
  const time = parsed.getTime();
  if (Number.isNaN(time)) return '--';
  const diffMs = time - Date.now();
  const absMs = Math.abs(diffMs);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const suffix = diffMs >= 0 ? '' : ' ago';
  if (absMs < hour) return `${Math.max(1, Math.round(absMs / minute))}m${suffix}`;
  if (absMs < day) return `${Math.round(absMs / hour)}h${suffix}`;
  return `${Math.round(absMs / day)}d${suffix}`;
}

function shortHash(value?: string | null, leading = 10, trailing = 6) {
  if (!value) return '--';
  if (trailing <= 0) {
    return value.length <= leading ? value : `${value.slice(0, leading)}...`;
  }
  if (value.length <= leading + trailing + 3) return value;
  return `${value.slice(0, leading)}...${value.slice(-trailing)}`;
}


export {
  formatPercent,
  formatCompact,
  formatCurrencyCompact,
  formatSignedPercent,
  signedClass,
  formatDate,
  formatRelative,
  shortHash,
};

export function toneClass(value?: string | null) {
  const tone = String(value || 'neutral').toLowerCase();
  if (tone === 'up') return 'tone-up';
  if (tone === 'down') return 'tone-down';
  if (tone === 'watch') return 'tone-watch';
  return 'tone-neutral';
}

export function watchStatusBadge(payload?: { status?: string | null; cacheMode?: string | null } | null) {
  const status = String(payload?.status || '').toLowerCase();
  const cacheMode = String(payload?.cacheMode || '').toLowerCase();
  if (cacheMode.includes('stale')) return 'STALE';
  if (status === 'ok') return 'LIVE';
  if (status === 'degraded' || status === 'partial') return 'PARTIAL';
  if (status === 'empty') return 'WARMING';
  return status ? status.toUpperCase() : 'SEED';
}

export function watchItemKey(item: { id?: string | number | null; url?: string | null; title?: string | null; label?: string | null }, index: number) {
  return String(item.id || item.url || item.title || item.label || index);
}

export function numericValue(value?: number | string | null) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

export function seededStatusBadge(payload?: { status?: string | null; cacheMode?: string | null } | null) {
  const mode = String(payload?.cacheMode || '').toLowerCase();
  const status = String(payload?.status || '').toLowerCase();
  if (mode.includes('stale') || mode.includes('preserved')) return 'STALE';
  if (mode.includes('seed')) return status === 'degraded' ? 'PARTIAL' : 'SEED';
  if (status === 'empty' || status === 'warming') return 'WARM';
  return status === 'degraded' ? 'PARTIAL' : 'LIVE';
}

export function alertSeverityClass(item: { severity?: string | null }) {
  const severity = String(item.severity || '').toLowerCase();
  if (severity === 'alert') return 'alert';
  if (severity === 'watch') return 'watch';
  return 'normal';
}

export function scoreLabel(value?: string | number | null) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? String(Math.round(numeric)) : '--';
}

export function relativeDuration(value?: string | null) {
  if (!value) return '--';
  return formatRelative(value).replace(' ago', '').replace('in ', '');
}

export function compactText(value: string | null | undefined, maxLength: number) {
  const text = String(value || '').trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(1, maxLength - 1)).trim()}...`;
}

export function panelStatus(status?: string | null): 'live' | 'muted' {
  return String(status || '').toLowerCase() === 'ok' ? 'live' : 'muted';
}

function parseTimestamp(value?: string | null): number | null {
  const parsed = Date.parse(String(value || ''));
  return Number.isFinite(parsed) ? parsed : null;
}

export function ageSeconds(value?: string | null): number | null {
  const parsed = parseTimestamp(value);
  return parsed == null ? null : Math.max(0, Math.round((Date.now() - parsed) / 1_000));
}

export function cleanSourceLabel(value?: string | null): string {
  return String(value || 'unknown')
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, (character: string) => character.toUpperCase());
}

export function formatLocalizedCompact(value: string | number | null | undefined, formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string): string {
  const numeric = Number(value);
  return Number.isFinite(numeric)
    ? formatNumber(numeric, { notation: 'compact', maximumFractionDigits: 1 })
    : '--';
}
