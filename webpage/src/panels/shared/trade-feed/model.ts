import type { PanelRuntimeStatus } from '@/panels/types';

export const TRADE_REFRESH_MS = 30_000;
export const TRADE_MAX_AGE_MS = 300_000;
export const TRADE_RECOVERY_AGE_MS = 900_000;
export type TradeKind = 'whale-trades' | 'flow-watch';
export interface TradeObservation {
  id: string; marketId: number; marketTitle: string; tokenId: string; txHash: string;
  timestamp: string | null; side: 'BUY' | 'SELL' | 'UNKNOWN';
  outcome: string | null; labelsVerified: boolean; price: number | null; notional: number | null;
  maker: string | null; taker: string | null; severity: string;
  observationType: 'oracle-linked' | 'large-trade'; eventTime: string | null;
}
export interface TradeFeed {
  schemaVersion: 'trade-watch-v1'; kind: TradeKind; generatedAt: string;
  status: 'ok' | 'empty' | 'partial' | 'degraded' | 'stale'; items: TradeObservation[];
  error: string | null; lastAttemptAt: string | null; sourceMode: string;
  refreshIntervalSeconds: number; freshnessWindowSeconds: number;
  coverage: Record<string, number>; sourceStates: Record<string, unknown>;
}
const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown) => typeof value === 'string' ? value.trim() : '';
const date = (value: unknown) => text(value) && Number.isFinite(Date.parse(text(value))) ? text(value) : null;
function number(value: unknown, max = Number.MAX_SAFE_INTEGER) {
  if ((typeof value !== 'number' && typeof value !== 'string') || String(value).trim() === '') return null;
  const result = Number(value);
  return Number.isFinite(result) && result >= 0 && result <= max ? result : null;
}
const address = (value: unknown) => /^0x[0-9a-f]{40}$/i.test(text(value)) ? text(value) : null;
function item(value: unknown): TradeObservation {
  const row = record(value), marketId = number(row.marketId), tokenId = text(row.tokenId);
  const txHash = text(row.txHash).replace(/^0x/, '');
  if (!marketId || !Number.isInteger(marketId) || !tokenId || !/^[0-9a-f]{64}$/i.test(txHash) || !text(row.marketTitle)) throw new Error('Invalid canonical trade identity');
  const side = ['BUY', 'SELL'].includes(String(row.side)) ? row.side as 'BUY' | 'SELL' : 'UNKNOWN';
  const labelsVerified = row.outcomeSemanticsValid === true && Boolean(text(row.sourceOutcomeLabel));
  return { id: [txHash, row.logIndex ?? '', tokenId, side].join(':'), marketId, tokenId, marketTitle: text(row.marketTitle), txHash,
    side, labelsVerified, outcome: labelsVerified ? text(row.sourceOutcomeLabel) : null,
    timestamp: date(row.timestamp), price: number(row.price, 1), notional: number(row.notional),
    maker: address(row.maker), taker: address(row.taker), severity: ['critical', 'elevated', 'watch'].includes(text(row.severity)) ? text(row.severity) : 'unknown',
    observationType: row.observationType === 'oracle-linked' ? 'oracle-linked' : 'large-trade', eventTime: date(row.eventTime) };
}
export function parseTradeFeed(value: unknown, kind: TradeKind): TradeFeed {
  const raw = record(value), generatedAt = date(raw.generatedAt);
  if (raw.schemaVersion !== 'trade-watch-v1' || raw.kind !== kind || !generatedAt || !Array.isArray(raw.items)
    || raw.items.length > 40 || !['ok', 'empty', 'partial', 'degraded', 'stale'].includes(String(raw.status))) throw new Error('Trade snapshot unavailable or warming up');
  const items: TradeObservation[] = [], seen = new Set<string>();
  let rejected = 0;
  for (const entry of raw.items) {
    try { const row = item(entry); if (!seen.has(row.id)) { seen.add(row.id); items.push(row); } }
    catch { rejected++; }
  }
  const coverage: Record<string, number> = {};
  for (const [key, value] of Object.entries(record(raw.coverage))) { const n = number(value); if (n != null) coverage[key] = n; }
  coverage.invalidDisplayCount = rejected;
  if (raw.items.length && !items.length) throw new Error('No canonical trade rows could be displayed');
  return { schemaVersion: 'trade-watch-v1', kind, generatedAt, items,
    status: raw.status === 'stale' || raw.status === 'degraded' ? raw.status : rejected ? 'partial' : raw.status as TradeFeed['status'],
    error: text(raw.error) || null, sourceMode: text(raw.sourceMode), lastAttemptAt: date(raw.lastAttemptAt),
    refreshIntervalSeconds: number(raw.refreshIntervalSeconds) ?? 120, freshnessWindowSeconds: number(raw.freshnessWindowSeconds) ?? 300,
    coverage, sourceStates: record(raw.sourceStates) };
}
export function tradeStatusLabel(value: TradeFeed, status: PanelRuntimeStatus): string | undefined {
  if (status.error || ['error', 'degraded', 'stale'].includes(status.phase)) return undefined;
  if (value.status === 'stale') return 'STALE';
  if (value.status === 'degraded') return 'UNAVAILABLE';
  if (value.status === 'partial') return 'PARTIAL';
  if (!value.items.length) return 'NO MATCH';
  return value.kind === 'flow-watch' && value.items.every(item => item.observationType === 'large-trade') ? 'LARGE TRADES' : 'READY';
}
export const shortIdentity = (value: string) => `${value.slice(0, 8)}…${value.slice(-6)}`;
