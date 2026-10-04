import type { PanelSnapshotContract } from '@/panels/resource-cache';
import { usePanelRuntimeView } from '@/panels/PanelRuntimeView';
import type { RuntimeMacroRegistryPayload } from '@/types';
import './macro-runtime.css';

export const macroRefreshPolicy = {
  tier: 'slow' as const, intervalMs: 30_000, staleAfterMs: 45 * 60_000,
  requestTimeoutMs: 12_000, batch: false,
};

export function macroSnapshot(panelId: string, geo = false): PanelSnapshotContract<unknown> {
  const maxAgeMs = geo ? 10 * 60_000 : macroRefreshPolicy.staleAfterMs;
  return {
    key: `macro:${panelId}:latest:v2`, maxAgeMs, staleAgeMs: 24 * 60 * 60_000,
    acceptStale: true, cache: { version: 2, maxChars: 256_000 },
    parse(value) {
      if (!value || typeof value !== 'object') throw new Error('Invalid macro snapshot');
      const payload = value as RuntimeMacroRegistryPayload;
      if (!Array.isArray(payload.items) || typeof payload.status !== 'string') throw new Error('Invalid macro rows/status');
      if (payload.items.length && !Number.isFinite(Date.parse(payload.generatedAt || ''))) throw new Error('Missing macro collection timestamp');
      if (!geo && payload.items.length && (payload.schemaVersion !== 2 || payload.panelId !== panelId)) throw new Error('Incompatible macro snapshot');
      for (const row of payload.items) {
        if (!row || typeof row !== 'object') throw new Error('Invalid macro row');
        for (const key of ['value', 'change'] as const) {
          if (typeof row[key] === 'number' && !Number.isFinite(row[key])) throw new Error('Non-finite macro value');
        }
      }
      return payload;
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

export function MacroRefresh({ payload, sourceMinutes = 30 }: {
  payload?: { generatedAt?: string; status?: string | null; sources?: Record<string, string>; expectedIntervalSeconds?: number } | null;
  sourceMinutes?: number;
}) {
  const runtime = usePanelRuntimeView();
  const problems = Object.entries(payload?.sources || {}).filter(([, state]) => !['ok', 'empty', 'redis-seed', 'sqlite-seed'].includes(state));
  return <div className="wm-macro-refresh" aria-live="polite">
    <div><span>Auto check 30s · Seed {Math.round((payload?.expectedIntervalSeconds ?? sourceMinutes * 60) / 60)}m</span>
      <button type="button" disabled={Boolean(runtime?.status?.fetching)} onClick={() => runtime?.refresh?.()}>
        {runtime?.status?.fetching ? 'Refreshing…' : 'Refresh'}
      </button></div>
    <small>Checked {time(runtime?.status?.checkedAt)} · Snapshot {time(payload?.generatedAt)}</small>
    {runtime?.status?.error ? <p role="status">Refresh failed; keeping available data. {runtime.status.error}</p> : null}
    {problems.length ? <details><summary>{problems.length} source checks incomplete</summary>
      {problems.map(([key, state]) => <div key={key}>{key}: {state}</div>)}</details> : null}
  </div>;
}
