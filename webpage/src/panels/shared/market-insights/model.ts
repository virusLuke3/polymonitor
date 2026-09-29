import type { MarketWideAiInsightLens, MarketWideAiInsightResponse } from '@/types';

type RecordValue = Record<string, unknown>;
const record = (value: unknown): value is RecordValue => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const textFields = (value: unknown, fields: string[]) => record(value) && fields.every(key => typeof value[key] === 'string');
const optionalText = (value: RecordValue, keys: string[]) => keys.every(key => value[key] == null || typeof value[key] === 'string');
const textList = (value: unknown) => value === undefined || (Array.isArray(value) && value.every(item => typeof item === 'string'));
const cards = (value: unknown, fields: string[]) => Array.isArray(value) && value.every(item => textFields(item, fields) && optionalText(item as RecordValue, ['severity', 'evidence', 'trend', 'horizon']));

/** Validate the snapshot once at the panel boundary; never assert arbitrary runtime data. */
export function isInsight(value: unknown, lens: MarketWideAiInsightLens): value is MarketWideAiInsightResponse {
  return record(value) && value.lens === lens && textFields(value, ['status', 'brief'])
    && optionalText(value, ['model', 'source', 'cacheStatus', 'generatedAt', 'snapshotGeneratedAt', 'snapshotExpiresAt', 'error'])
    && (value.generationMode === undefined || value.generationMode === 'ai' || value.generationMode === 'rules')
    && cards(value.focus, ['label', 'title', 'summary', 'severity'])
    && cards(value.specialMarkets, ['title', 'why']) && cards(value.themes, ['label', 'title', 'summary'])
    && cards(value.watchlist, ['title', 'reason']) && textList(value.evidence) && textList(value.limitations);
}

export function insightView(value: unknown, lens: MarketWideAiInsightLens, now = Date.now()) {
  const insight = isInsight(value, lens) ? value : null;
  const generatedAt = insight?.snapshotGeneratedAt || insight?.generatedAt;
  const generated = Date.parse(generatedAt || '');
  const expires = Date.parse(insight?.snapshotExpiresAt || '');
  const knownTime = Number.isFinite(generated) && generated <= now + 60_000;
  const stale = insight?.cacheStatus === 'stale-snapshot' || (knownTime && (
    Number.isFinite(expires) ? expires <= now : now - generated > 12 * 60 * 60_000
  ));
  const mode = insight && insight.status === 'live' && insight.generationMode !== 'rules'
    && Boolean(insight.model) && !/fallback/i.test(insight.model || '') && !insight.error ? 'ai' : 'rules';
  const badge = !insight ? 'unavailable' : stale ? 'stale' : !knownTime ? 'unknownTime' : mode;
  return { insight, mode, badge, stale, generatedAt: knownTime ? generatedAt : undefined,
    healthy: Boolean(insight && mode === 'ai' && knownTime && !stale) } as const;
}
export type InsightView = ReturnType<typeof insightView>;
