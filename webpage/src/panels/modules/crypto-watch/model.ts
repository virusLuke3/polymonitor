import type { RuntimeMarketTicker } from '@/types';
import type { PanelRuntimeStatus } from '@/panels/types';
import { RuntimeResponseError } from '@/panels/runtime-store';

export const REFRESH_MS = 5000, MAX_AGE_MS = 180_000, RETAIN_MS = 900_000;
export const CRYPTO_SYMBOL_ORDER = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'XRP-USD', 'DOGE-USD', 'ADA-USD', 'AVAX-USD', 'LINK-USD', 'LTC-USD', 'DOT-USD', 'TRX-USD', 'BCH-USD'] as const;
export type CryptoQuote = RuntimeMarketTicker & { quoteAt: string | null; fetchedAt: string | null; changeBasis: string; source: string; acquisitionState: 'ok' | 'retained'; volumeBasis: string };
export type CryptoPayload = { kind: 'crypto'; generatedAt: string; status: string; items: CryptoQuote[]; refreshIntervalSeconds: number; coverage: { expected: number; succeeded: number; retained: number; missing: number } };
const record = (value: unknown): Record<string, unknown> => value != null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const finite = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : null;
const date = (value: unknown) => typeof value === 'string' && Number.isFinite(Date.parse(value)) ? value : null;

export function parseCrypto(value: unknown): CryptoPayload {
  const raw = record(value), generatedAt = date(raw.generatedAt);
  if (raw.kind !== 'crypto') throw new RuntimeResponseError('Snapshot belongs to a different market family', false);
  if (!generatedAt || !Array.isArray(raw.items) || ['error', 'failed', 'unavailable', 'warming'].includes(String(raw.status))) throw new RuntimeResponseError('Invalid crypto snapshot');
  const bySymbol = new Map<string, CryptoQuote>();
  for (const entry of raw.items) {
    const row = record(entry), symbol = String(row.symbol || ''), price = finite(row.price);
    if (!CRYPTO_SYMBOL_ORDER.includes(symbol as typeof CRYPTO_SYMBOL_ORDER[number]) || price == null || price <= 0 || typeof row.id !== 'string' || typeof row.label !== 'string') continue;
    bySymbol.set(symbol, {
      id: row.id, label: row.label, symbol, price, currency: typeof row.currency === 'string' ? row.currency : null,
      changeBasis: typeof row.changeBasis === 'string' ? row.changeBasis : 'unknown',
      changePercent: row.changeBasis === 'rolling-24h' ? finite(row.changePercent) : null,
      marketCap: finite(row.marketCap), volume24h: finite(row.volume24h), volumeBasis: String(row.volumeBasis || 'unknown'),
      quoteAt: date(row.quoteAt), fetchedAt: date(row.fetchedAt), source: typeof row.source === 'string' ? row.source : 'unknown',
      acquisitionState: row.acquisitionState === 'retained' ? 'retained' : 'ok',
      points: (Array.isArray(row.points) ? row.points : []).flatMap(entry => {
        const point = record(entry), timestamp = date(point.timestamp), value = finite(point.value);
        return timestamp && value != null && value > 0 ? [{ timestamp, value }] : [];
      }).slice(-48),
    });
  }
  if (!bySymbol.size) throw new Error('No usable crypto quotes; checking automatically');
  const items = CRYPTO_SYMBOL_ORDER.flatMap(symbol => bySymbol.has(symbol) ? [bySymbol.get(symbol)!] : []);
  const retained = items.filter(item => item.acquisitionState === 'retained').length;
  return {
    kind: 'crypto', generatedAt, status: raw.status === 'stale' ? 'stale' : retained || items.length < CRYPTO_SYMBOL_ORDER.length || ['degraded', 'partial', 'unknown'].includes(String(raw.status)) ? 'degraded' : 'ok',
    items, refreshIntervalSeconds: finite(raw.refreshIntervalSeconds) ?? 60,
    coverage: { expected: CRYPTO_SYMBOL_ORDER.length, succeeded: items.length - retained, retained, missing: CRYPTO_SYMBOL_ORDER.length - items.length },
  };
}

export function cryptoQuoteState(item: CryptoQuote, now = Date.now()) {
  if (item.acquisitionState === 'retained') return 'retained';
  const age = item.quoteAt ? now - Date.parse(item.quoteAt) : NaN;
  return !Number.isFinite(age) || age < -60_000 ? 'unknown' : age >= RETAIN_MS ? 'stale' : 'live';
}
export function cryptoStatusLabel(data: CryptoPayload, status: PanelRuntimeStatus) {
  if (status.error || status.phase === 'stale' || data.status === 'stale') return undefined;
  if (data.status === 'degraded') return 'PARTIAL';
  if (data.items.some(item => cryptoQuoteState(item) === 'stale')) return 'QUOTE STALE';
  if (data.items.some(item => cryptoQuoteState(item) === 'unknown')) return 'TIME UNKNOWN';
  return 'READY';
}
