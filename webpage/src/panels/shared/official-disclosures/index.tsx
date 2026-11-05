import type { ComponentChildren } from 'preact';
import { PanelDataControls } from '../PanelDataControls';
import { usePanelRuntimeView } from '../../PanelRuntimeView';
import { useI18n } from '@/services/i18n';
import { RuntimeResponseError } from '../../runtime-store';
import type { PanelSnapshotContract } from '../../resource-cache';

export type Source = { lastSuccessAt: string | null; lastAttemptAt: string | null; error?: string | null; stale: boolean; usable: boolean };
export const useCopy = () => { const { locale } = useI18n(); return (zh: string, en: string) => locale.startsWith('zh') ? zh : en; };
export const date = (value?: string | null) => value ? value.slice(0, 10) : '—';
export function DisclosureControls({ children }: { children: ComponentChildren }) {
  const runtime = usePanelRuntimeView();
  return <PanelDataControls fetching={runtime?.status?.fetching} onRefresh={() => runtime?.refresh?.()}>{children}</PanelDataControls>;
}
export function SourceNotice({ source }: { source?: Source }) {
  const t = useCopy();
  if (!source || !source.lastSuccessAt) return <p role="status">{t('此来源尚未取得数据。', 'This source has no successful observation yet.')}</p>;
  if (!source.error && !source.stale) return null;
  return <p role="status" style={{ color: 'var(--ds-color-warning)' }}>{source.stale ? t('更新中断', 'Updates delayed') : t('本轮采集失败', 'Latest acquisition failed')} · {t('保留', 'Retained')} {date(source.lastSuccessAt)}</p>;
}
export function contract<T extends { panelId: string; schemaVersion: number; generatedAt: string }>(id: string, validate: (raw: unknown) => raw is T): PanelSnapshotContract<unknown> {
  return {
    key: `official-disclosures:${id}:v1`, maxAgeMs: 86_400_000, staleAgeMs: 7 * 86_400_000,
    acceptStale: true, cache: { version: 1, maxChars: 240_000 },
    parse(raw) {
      if (!validate(raw) || raw.panelId !== id || raw.schemaVersion !== 1 || !Number.isFinite(Date.parse(raw.generatedAt))) throw new RuntimeResponseError('Invalid official disclosure snapshot');
      return raw;
    },
    updatedAt: raw => validate(raw) ? Date.parse(raw.generatedAt) : null,
  };
}
export const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
export const validSource = (v: unknown): v is Source => record(v) && typeof v.stale === 'boolean' && typeof v.usable === 'boolean' && (v.lastSuccessAt === null || typeof v.lastSuccessAt === 'string');
export const safeUrl = (value: unknown) => typeof value === 'string' && /^https:\/\/(?:www\.)?(?:sec\.gov|federalregister\.gov|govinfo\.gov)\//.test(value);
