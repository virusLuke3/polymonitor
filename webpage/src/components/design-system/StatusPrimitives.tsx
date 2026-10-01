import type { useI18n } from '@/services/i18n';
import { cleanSourceLabel } from '@/panels/shared/formatters';
import type { ComponentChildren } from 'preact';
import type { PanelRuntimeStatus } from '@/panels/types';

export type OperationalTone = 'positive' | 'warning' | 'critical' | 'info' | 'neutral';

type StatusBadgeProps = {
  label: string;
  tone?: OperationalTone;
  detail?: string | null;
  compact?: boolean;
  className?: string;
};

type RuntimeStatusBadgeProps = {
  status: PanelRuntimeStatus;
  compact?: boolean;
};

type MetricCardProps = {
  eyebrow: string;
  value: ComponentChildren;
  detail?: ComponentChildren;
  tone?: OperationalTone;
};

const POSITIVE_STATES = new Set(['ok', 'ready', 'live', 'fresh', 'online', 'active', 'healthy', 'synced']);
const WARNING_STATES = new Set(['warming', 'aging', 'stale', 'degraded', 'partial', 'limited', 'preserved', 'suspended']);
const CRITICAL_STATES = new Set(['error', 'failed', 'missing', 'offline', 'off', 'unavailable', 'critical']);

export function operationalTone(value?: string | null): OperationalTone {
  const normalized = String(value || '').trim().toLowerCase();
  if (POSITIVE_STATES.has(normalized)) return 'positive';
  if (WARNING_STATES.has(normalized)) return 'warning';
  if (CRITICAL_STATES.has(normalized)) return 'critical';
  if (normalized === 'loading' || normalized === 'observed' || normalized === 'network') return 'info';
  return 'neutral';
}

function formatAge(ageSeconds?: number | null): string {
  if (ageSeconds == null || !Number.isFinite(ageSeconds) || ageSeconds < 0) return '--';
  if (ageSeconds < 5) return 'now';
  if (ageSeconds < 60) return `${Math.round(ageSeconds)}s`;
  if (ageSeconds < 3_600) return `${Math.round(ageSeconds / 60)}m`;
  if (ageSeconds < 86_400) return `${Math.round(ageSeconds / 3_600)}h`;
  return `${Math.round(ageSeconds / 86_400)}d`;
}

export function StatusBadge({
  label,
  tone = operationalTone(label),
  detail,
  compact = false,
  className = '',
}: StatusBadgeProps) {
  return (
    <span
      className={`ds-status-badge is-${tone}${compact ? ' is-compact' : ''}${className ? ` ${className}` : ''}`}
      title={detail || undefined}
    >
      <span className="ds-status-dot" aria-hidden="true" />
      <span>{label}</span>
      {detail && !compact ? <em>{detail}</em> : null}
    </span>
  );
}

export function RuntimeStatusBadge({ status, compact = false }: RuntimeStatusBadgeProps) {
  const phase = status.phase || 'idle';
  const freshness = String(status.freshness || '').trim().toLowerCase();
  const label = status.label || (freshness && phase === 'ready' ? freshness : phase);
  const age = status.ageSeconds ?? (
    status.updatedAt ? Math.max(0, Math.round((Date.now() - status.updatedAt) / 1_000)) : null
  );
  const detail = [
    status.cacheMode ? `cache ${status.cacheMode}` : null,
    age == null ? null : `age ${formatAge(age)}`,
    status.error || null,
  ].filter(Boolean).join(' · ');
  return (
    <StatusBadge
      compact={compact}
      label={label.toUpperCase()}
      tone={operationalTone(status.label || (phase === 'ready' ? freshness || 'ready' : phase))}
      detail={detail}
    />
  );
}

export function MetricCard({
  eyebrow,
  value,
  detail,
  tone = 'neutral',
}: MetricCardProps) {
  return (
    <article className={`ds-metric-card is-${tone}`}>
      <span className="ds-metric-card-eyebrow">{eyebrow}</span>
      <strong>{value}</strong>
      {detail ? <div className="ds-metric-card-detail">{detail}</div> : null}
    </article>
  );
}

type Translator = ReturnType<typeof useI18n>['t'];

export function statusLabel(value: string | null | undefined, t: Translator, additionalLabels: Record<string, Parameters<Translator>[0]> = {}): string {
  const normalized = String(value || 'unknown').trim().toLowerCase().replace(/_/g, '-');
  const known = {
    loading: 'status.loading',
    unknown: 'status.unknown',
    fresh: 'status.fresh',
    aging: 'status.aging',
    stale: 'status.stale',
    ok: 'status.ok',
    missing: 'status.missing',
    partial: 'status.partial',
    critical: 'status.critical',
    degraded: 'status.degraded',
    warning: 'status.warning',
    ready: 'status.ready',
    observed: 'status.observed',
    bound: 'status.bound',
    unbound: 'status.unbound',
    pending: 'status.pending',
    open: 'status.open',
    closed: 'status.closed',
    proposed: 'status.proposed',
    disputed: 'status.disputed',
    resolved: 'status.resolved',
    error: 'status.error',
    snapshot: 'status.snapshot',
    'single-market': 'status.singleMarket',
    'open-no-events': 'status.openNoEvents',
    'not-loaded': 'status.notLoaded',
    'ended-awaiting-oracle': 'status.endedAwaitingOracle',
  } as const;
  const key = additionalLabels[normalized] || known[normalized as keyof typeof known];
  return key ? t(key) : cleanSourceLabel(value);
}
