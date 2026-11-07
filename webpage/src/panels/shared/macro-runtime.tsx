import type { PanelSnapshotContract } from '@/panels/resource-cache';
import { usePanelRuntimeView } from '@/panels/PanelRuntimeView';
import type { RuntimeMacroRegistryPayload } from '@/types';
import './macro-runtime.css';

export const macroRefreshPolicy = {
  tier: 'slow' as const, intervalMs: 30 * 60_000, staleAfterMs: 45 * 60_000,
  requestTimeoutMs: 12_000, batch: false,
};

/** Reapply on cache restore and the existing Runtime expiry sweep; never renew clocks. */
export function projectMacroDisplay(value: unknown, now = Date.now()): unknown {
  if (!value || typeof value !== 'object') return value;
  const payload = value as Record<string, any>;
  const policy = payload.displayRetention || {};
  const maxAge = Math.max(1, Number(policy.maxAgeSeconds) || 64800) * 1000;
  const actualAge = Math.max(1, Number(policy.actualMaxAgeSeconds) || 5400) * 1000;
  const valid = (clock: unknown, age: number) => {
    const observed = Date.parse(String(clock || ''));
    return Number.isFinite(observed) && now - observed >= -60000 && now - observed < age;
  };
  const original = Array.isArray(payload.items) ? payload.items : [];
  const items = original.filter((row: any) => valid(row.fetchedAt || row.metadata?.fetchedAt || row.metadata?.verifiedAt, maxAge));
  let changed = items.length !== original.length;
  const events = Array.isArray(payload.events) ? payload.events.map((event: any) => {
    const result = { ...event };
    if (!valid(event.fetchedAt, actualAge) && (event.actual != null || event.previous != null || event.surprise != null)) {
      Object.assign(result, { actual: null, previous: null, surprise: null, actualLabel: '--', previousLabel: '--', surpriseLabel: '--', actualStatus: 'expired' });
      changed = true;
    }
    if (!valid(event.forecastFetchedAt, maxAge) && (event.forecast != null || event.surprise != null)) {
      Object.assign(result, { forecast: null, surprise: null, forecastLabel: '--', surpriseLabel: '--', forecastStatus: 'expired' });
      changed = true;
    }
    return result;
  }) : undefined;
  if (!changed) return value;
  const sources = { ...payload.sources };
  const expiredKeys = new Set(original.filter((row: any) => !items.includes(row)).map((row: any) => row.key));
  for (const key of Object.keys(sources)) {
    if ((!items.length || expiredKeys.has(key)) && ['ok', 'empty'].includes(sources[key])) sources[key] = 'expired';
  }
  const summary = { ...payload.summary, rowCount: items.length, topMover: null,
    topLabel: null, pressureScore: null, bias: 'unknown' };
  if (events) for (const field of ['actual', 'previous', 'forecast']) {
    summary[`${field}Count`] = events.filter((event: any) => event[field] != null).length;
  }
  return { ...payload, items, ...(events ? { events } : {}), summary, sources,
    status: items.length || events?.some((event: any) => event.actual != null || event.forecast != null || event.previous != null) ? 'degraded' : 'expired' };
}

export function macroSnapshot(panelId: string, geo = false, family: 'registry' | 'source' = 'registry'): PanelSnapshotContract<unknown> {
  const maxAgeMs = geo ? 10 * 60_000 : macroRefreshPolicy.staleAfterMs;
  return {
    key: `macro:${panelId}:latest:v2`, maxAgeMs, staleAgeMs: (geo ? 24 : 18) * 60 * 60_000,
    acceptStale: true, cache: { version: 2, maxChars: 256_000 },
    revalidate: geo ? undefined : projectMacroDisplay,
    parse(value) {
      if (!value || typeof value !== 'object') throw new Error('Invalid macro snapshot');
      const payload = value as RuntimeMacroRegistryPayload;
      if (!Array.isArray(payload.items) || typeof payload.status !== 'string') throw new Error('Invalid macro rows/status');
      if (payload.items.length && !Number.isFinite(Date.parse(payload.generatedAt || ''))) throw new Error('Missing macro collection timestamp');
      if (!geo && family === 'registry' && payload.items.length && (payload.schemaVersion !== 2 || payload.panelId !== panelId)) throw new Error('Incompatible macro snapshot');
      const sanctions = (value as { sanctionsItems?: unknown }).sanctionsItems;
      if (geo && sanctions != null && (!Array.isArray(sanctions) || sanctions.some(row => !row || typeof row !== 'object'))) throw new Error('Invalid sanctions sample');
      for (const row of payload.items) {
        if (!row || typeof row !== 'object') throw new Error('Invalid macro row');
        for (const key of ['value', 'change'] as const) {
          if (typeof row[key] === 'number' && !Number.isFinite(row[key])) throw new Error('Non-finite macro value');
        }
      }
      return geo ? payload : projectMacroDisplay(payload);
    },
    updatedAt(value) {
      const date = Date.parse((value as RuntimeMacroRegistryPayload).generatedAt || '');
      return Number.isFinite(date) ? date : null;
    },
    shouldPersist: value => Boolean((value as RuntimeMacroRegistryPayload).items?.length),
  };
}

function time(value?: string | number | null) {
  if (value == null) return '--';
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : '--';
}

export function MacroRefresh({ payload }: {
  payload?: { generatedAt?: string; status?: string | null; sources?: Record<string, string>; optionalSources?: Record<string, string>; expectedIntervalSeconds?: number } | null;
}) {
  const runtime = usePanelRuntimeView();
  const problems = Object.entries({...payload?.sources, ...Object.fromEntries(Object.entries(payload?.optionalSources || {}).map(([key, value]) => [`Optional ${key}`, value]))}).filter(([, state]) => !['ok', 'empty', 'redis-seed', 'sqlite-seed'].includes(state));
  return <div className="wm-macro-refresh" aria-live="polite">
    <div>
      <button type="button" disabled={Boolean(runtime?.status?.fetching)} onClick={() => runtime?.refresh?.()}>
        {runtime?.status?.fetching ? 'Refreshing…' : 'Refresh'}
      </button></div>
    <small>Checked {time(runtime?.status?.checkedAt)} · Snapshot {time(payload?.generatedAt)}</small>
    {runtime?.status?.error ? <p role="status">Refresh failed; keeping available data. {runtime.status.error}</p> : null}
    {problems.length ? <details><summary>{problems.length} source checks incomplete</summary>
      {problems.map(([key, state]) => <div key={key}>{key}: {state}</div>)}</details> : null}
  </div>;
}
