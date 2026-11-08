import type { VNode } from 'preact';
import { fetchExternalPanel } from '@/services/api';
import { runtimePanelFromRenderer } from '../../definePanel';
import { RuntimeResponseError } from '../../runtime-store';

export type EvidenceSource = { id: string; label?: string; lastSuccessAt: string | null; lastAttemptAt?: string | null; usable: boolean; stale: boolean; error?: string | null; maxRetentionSeconds?: number; staleAfterSeconds?: number };
export type BasePayload = { panelId: string; schemaVersion: number; generatedAt: string | null; status: string; sources: EvidenceSource[]; coverage?: string };
export const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
export function isBasePayload(v: unknown): v is BasePayload {
  return record(v) && typeof v.panelId === 'string' && v.schemaVersion === 1
    && (v.generatedAt === null || typeof v.generatedAt === 'string' && Number.isFinite(Date.parse(v.generatedAt)))
    && typeof v.status === 'string' && Array.isArray(v.sources) && v.sources.length <= 100
    && v.sources.every(s => record(s) && typeof s.id === 'string' && typeof s.usable === 'boolean' && typeof s.stale === 'boolean'
      && (s.lastSuccessAt === null || typeof s.lastSuccessAt === 'string' && Number.isFinite(Date.parse(s.lastSuccessAt))));
}

export function externalPanel<T extends BasePayload>(options: {
  id: string; title: string; description: string; render: (data: T | undefined) => VNode;
  validate: (value: unknown) => value is T; intervalMs?: number; maxAgeMs?: number; retentionMs?: number;
}) {
  const { id, title, description, validate, render } = options;
  return runtimePanelFromRenderer({ [id]: { render: ctx => render(ctx.runtimeData[id] as T | undefined) } }, {
    id, title, description, eyebrow: 'external', defaultEnabled: true,
    snapshot: {
      key: `external:${id}:v1`, maxAgeMs: options.maxAgeMs ?? 10800000,
      staleAgeMs: options.retentionMs ?? 7 * 86400000, acceptStale: true,
      cache: { version: 1, maxChars: 200000 },
      parse(value) {
        if (!isBasePayload(value) || value.panelId !== id || !validate(value)) throw new RuntimeResponseError('Invalid domain snapshot');
        for (const source of value.sources) {
          if (!source.usable || !source.lastSuccessAt) continue;
          const age = Date.now() - Date.parse(source.lastSuccessAt);
          if (age < -60000 || source.maxRetentionSeconds !== undefined
            && (!Number.isFinite(source.maxRetentionSeconds) || age > source.maxRetentionSeconds * 1000)) {
            throw new RuntimeResponseError('Source component exceeds its original retention');
          }
        }
        return value;
      },
      updatedAt: value => isBasePayload(value) && value.generatedAt ? Date.parse(value.generatedAt) : null,
    },
  }, { tier: 'slow', batch: false, intervalMs: options.intervalMs ?? 600000,
    staleAfterMs: options.maxAgeMs ?? 10800000, requestTimeoutMs: 20000,
    retry: { attempts: 1, baseDelayMs: 5000, maxDelayMs: 5000 },
    fetchData: ctx => fetchExternalPanel(id, ctx?.signal),
  });
}
