import type { PanelRuntimeStatus } from '@/panels/types';

export const ALPHA_LIMIT = 8;
export const ALPHA_REFRESH_MS = 30_000;
export const ALPHA_MAX_AGE_MS = 300_000;
export const ALPHA_RESOURCE_KEY = `alpha-signal:global:token-flow-v1:${ALPHA_LIMIT}`;
export interface AlphaSignal {
  id: string; marketId: number; tokenId: string; marketTitle: string;
  side: 'BUY' | 'SELL'; logicalOutcome: 'YES' | 'NO'; outcome: string;
  timestamp: string | null; price: number;
  metrics: { totalNotional: number; netFlowNotional: number; netDirectionStrength: number;
    marketShare: number; uniqueTraderCount: number; tradeCount: number; score: number };
}
export interface AlphaPayload {
  policyVersion: 'token-flow-v1'; scope: 'global'; generatedAt: string;
  status: 'ok' | 'empty' | 'partial' | 'degraded' | 'stale';
  items: AlphaSignal[]; candidates: AlphaCandidate[]; windowMinutes: number; baselineMinutes: number;
  sourceObservedAt: string | null; error: string | null;
  coverage: { candidateCount: number; verifiedCount: number; rejectedCount: number;
    rejectionReasons: Record<string, number>; truncated: boolean };
}
export type AlphaCandidate = Omit<AlphaSignal, 'logicalOutcome' | 'outcome' | 'price' | 'metrics'> & {
  qualification: 'labels-unavailable'; metrics: Omit<AlphaSignal['metrics'], 'score'>;
};
const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown) => typeof value === 'string' ? value.trim() : '';
function number(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER) {
  if ((typeof value !== 'number' && typeof value !== 'string') || value === '') throw new Error('Unknown Alpha metric');
  const n = Number(value);
  if (!Number.isFinite(n) || n < min || n > max) throw new Error('Invalid Alpha metric');
  return n;
}
function date(value: unknown): string | null {
  const valueText = text(value);
  return valueText && Number.isFinite(Date.parse(valueText)) ? valueText : null;
}
function signal(value: unknown): AlphaSignal {
  const row = record(value), metrics = record(row.metrics), capabilities = record(row.outcomeSemanticsCapabilities);
  if (row.outcomeSemanticsValid !== true || !(capabilities.supportsYesNoWording === true || capabilities.supportsDirectionalSemantics === true)
    || !text(row.tokenId) || !text(row.id) || !text(row.marketTitle) || !text(row.sourceOutcomeLabel)
    || !['BUY', 'SELL'].includes(String(row.side)) || !['YES', 'NO'].includes(String(row.logicalOutcome))) throw new Error('Unverified Alpha identity');
  const marketId = number(row.marketId, 1);
  if (!Number.isInteger(marketId)) throw new Error('Invalid Alpha market');
  return { id: text(row.id), marketId, tokenId: text(row.tokenId), marketTitle: text(row.marketTitle),
    side: row.side as AlphaSignal['side'], logicalOutcome: row.logicalOutcome as AlphaSignal['logicalOutcome'],
    outcome: text(row.sourceOutcomeLabel), timestamp: date(row.timestamp), price: number(row.price, 0, 1),
    metrics: { totalNotional: number(metrics.totalNotional), netFlowNotional: number(metrics.netFlowNotional),
      netDirectionStrength: number(metrics.netDirectionStrength, 0, 1), marketShare: number(metrics.marketShare),
      uniqueTraderCount: number(metrics.uniqueTraderCount), tradeCount: number(metrics.tradeCount), score: number(metrics.score, 0, 100) } };
}
function candidate(value: unknown): AlphaCandidate {
  const row = record(value), metrics = record(row.metrics);
  if (row.qualification !== 'labels-unavailable' || row.marketIdentityVerified !== true
    || !text(row.id) || !text(row.tokenId) || !text(row.marketTitle) || !['BUY', 'SELL'].includes(String(row.side))) throw new Error('Invalid token observation');
  return { id: text(row.id), tokenId: text(row.tokenId), marketId: number(row.marketId, 1), marketTitle: text(row.marketTitle),
    qualification: 'labels-unavailable', side: row.side as AlphaCandidate['side'], timestamp: date(row.timestamp),
    metrics: { totalNotional: number(metrics.totalNotional), netFlowNotional: number(metrics.netFlowNotional),
      netDirectionStrength: number(metrics.netDirectionStrength, 0, 1), marketShare: number(metrics.marketShare),
      uniqueTraderCount: number(metrics.uniqueTraderCount), tradeCount: number(metrics.tradeCount) } };
}
export function parseAlphaPayload(value: unknown): AlphaPayload {
  const raw = record(value), generatedAt = date(raw.generatedAt), coverage = record(raw.coverage);
  if (raw.policyVersion !== 'token-flow-v1' || raw.scope !== 'global' || !generatedAt || !Array.isArray(raw.items)
    || raw.items.length > 20 || !['ok', 'empty', 'partial', 'degraded', 'stale'].includes(String(raw.status))) throw new Error('Alpha snapshot unavailable or not verified');
  const seen = new Set<string>(), items: AlphaSignal[] = [], candidates: AlphaCandidate[] = [];
  let invalid = 0;
  for (const entry of raw.items) {
    try { const item = signal(entry); if (seen.has(item.id)) throw new Error('Duplicate Alpha signal'); seen.add(item.id); items.push(item); }
    catch { invalid++; }
  }
  if (raw.candidates != null && (!Array.isArray(raw.candidates) || raw.candidates.length > 20)) throw new Error('Invalid Alpha candidate list');
  for (const entry of (raw.candidates || []) as unknown[]) {
    try { const item = candidate(entry); if (seen.has(item.id)) throw new Error('Duplicate candidate'); seen.add(item.id); candidates.push(item); }
    catch { invalid++; }
  }
  const reasons: Record<string, number> = {};
  for (const [reason, count] of Object.entries(record(coverage.rejectionReasons))) reasons[reason] = number(count);
  if (invalid) reasons.invalidDisplayItem = invalid;
  return { policyVersion: 'token-flow-v1', scope: 'global', generatedAt, items, candidates,
    status: invalid ? items.length || candidates.length ? 'partial' : 'degraded' : raw.status as AlphaPayload['status'],
    windowMinutes: number(raw.windowMinutes, 1, 360), baselineMinutes: number(raw.baselineMinutes, 1, 1440),
    sourceObservedAt: date(raw.sourceObservedAt), error: text(raw.error) || null,
    coverage: { candidateCount: number(coverage.candidateCount), verifiedCount: number(coverage.verifiedCount),
      rejectedCount: number(coverage.rejectedCount) + invalid, rejectionReasons: reasons, truncated: coverage.truncated === true } };
}
export function alphaStatusLabel(value: AlphaPayload, status: PanelRuntimeStatus): string | undefined {
  if (status.error || ['error', 'degraded', 'stale'].includes(status.phase)) return undefined;
  if (value.status === 'stale') return 'STALE';
  if (value.status === 'degraded') return 'UNVERIFIED';
  if (!value.items.length && value.candidates.length) return 'NEEDS LABELS';
  if (value.status === 'partial') return 'PARTIAL';
  return value.items.length ? 'READY' : 'NO MATCH';
}
export function signalDirection(item: AlphaSignal | AlphaCandidate) {
  return item.side === 'BUY' ? 'buy' : 'sell';
}
