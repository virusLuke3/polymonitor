import type { RuntimeMarketTicker } from '@/types';
import type { PanelRuntimeStatus } from '@/panels/types';

export const COMMODITY_SYMBOLS = ['^VIX', 'GC=F', 'SI=F', 'HG=F', 'PL=F', 'PA=F', 'ALI=F', 'CL=F', 'BZ=F', 'NG=F', 'TTF=F', 'RB=F', 'HO=F', 'URA', 'LIT', 'COAL', 'ZW=F', 'ZC=F', 'ZS=F', 'ZR=F', 'KC=F', 'SB=F', 'CC=F', 'CT=F'];
export const FX_SYMBOLS = ['EURUSD=X', 'GBPUSD=X', 'USDJPY=X', 'USDCNY=X', 'USDINR=X', 'AUDUSD=X', 'USDCHF=X', 'USDCAD=X', 'USDTRY=X'];
const SYMBOLS = [...COMMODITY_SYMBOLS, ...FX_SYMBOLS];
export const REFRESH_MS = 20_000;
export const MAX_AGE_MS = 180_000;
export const RETAIN_MS = 15 * 60_000;
export type Quote = RuntimeMarketTicker & {
  quoteAt: string | null; fetchedAt: string | null;
  marketState: 'open' | 'closed' | 'unknown'; acquisitionState: 'ok' | 'retained';
  changeBasis: string; instrumentType: string | null; sessionVolume: number | null;
};
export type CommodityPayload = {
  kind: 'commodities'; generatedAt: string; status: string; items: Quote[];
  refreshIntervalSeconds: number;
  coverage: { expected: number; succeeded: number; retained: number; missing: number; failedSymbols: string[] };
};
const record = (value: unknown): Record<string, unknown> => value != null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
export const finite = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;
const date = (value: unknown): string | null => typeof value === 'string' && Number.isFinite(Date.parse(value)) ? value : null;

export function parseCommodities(value: unknown): CommodityPayload {
  const raw = record(value), generatedAt = date(raw.generatedAt);
  if (raw.kind !== 'commodities' || !generatedAt || !Array.isArray(raw.items)) throw new Error('Commodity snapshot is unavailable or invalid');
  const bySymbol = new Map<string, Quote>();
  for (const entry of raw.items) {
    const row = record(entry), symbol = String(row.symbol || ''), price = finite(row.price);
    if (!SYMBOLS.includes(symbol) || !row.id || !row.label || price == null) continue;
    const points = (Array.isArray(row.points) ? row.points : []).flatMap(entry => {
      const point = record(entry), timestamp = date(point.timestamp), value = finite(point.value);
      return timestamp && value != null ? [{ timestamp, value }] : [];
    }).slice(-48);
    bySymbol.set(symbol, {
      id: String(row.id), label: String(row.label), symbol, price, points,
      currency: typeof row.currency === 'string' ? row.currency : null,
      changePercent: row.changeBasis === 'previous-close' ? finite(row.changePercent) : null,
      changeBasis: String(row.changeBasis || 'unknown'), quoteAt: date(row.quoteAt), fetchedAt: date(row.fetchedAt),
      instrumentType: typeof row.instrumentType === 'string' ? row.instrumentType : null,
      marketState: row.marketState === 'open' || row.marketState === 'closed' ? row.marketState : 'unknown',
      acquisitionState: row.acquisitionState === 'retained' ? 'retained' : 'ok', sessionVolume: finite(row.sessionVolume),
    });
  }
  if (!bySymbol.size) throw new Error('No usable commodity quotes; checking again automatically');
  const items = SYMBOLS.flatMap(symbol => bySymbol.has(symbol) ? [bySymbol.get(symbol)!] : []);
  const retained = items.filter(item => item.acquisitionState === 'retained').length;
  const missingSymbols = SYMBOLS.filter(symbol => !bySymbol.has(symbol));
  const retainedSymbols = items.filter(item => item.acquisitionState === 'retained').map(item => item.symbol);
  const failedSymbols = [...new Set([...missingSymbols, ...retainedSymbols])];
  return {
    kind: 'commodities', generatedAt,
    status: raw.status === 'stale' ? 'stale' : failedSymbols.length || raw.status === 'degraded' ? 'degraded' : 'ok',
    items, refreshIntervalSeconds: finite(raw.refreshIntervalSeconds) ?? 60,
    coverage: { expected: SYMBOLS.length, succeeded: items.length - retained, retained, missing: missingSymbols.length, failedSymbols },
  };
}

export function quoteState(item: Quote, now = Date.now()) {
  if (item.acquisitionState === 'retained') return 'retained';
  const quoteAt = item.quoteAt ? Date.parse(item.quoteAt) : NaN;
  const age = now - quoteAt;
  if (!Number.isFinite(age) || age < -60_000) return 'unknown';
  if (item.marketState === 'closed' && age < 4 * 86400_000) return 'closed';
  if (age > 30 * 60_000) return 'stale';
  return item.marketState === 'open' ? 'open' : 'unknown';
}
export function dailyMovers(items: Quote[], now = Date.now()) {
  return items.filter(item => item.changePercent != null && ['open', 'closed'].includes(quoteState(item, now)));
}
export function commodityClass(item: Quote) {
  if (item.symbol.endsWith('=X')) return 'FX';
  if (item.symbol === '^VIX') return 'INDEX';
  if (['URA', 'LIT', 'COAL'].includes(item.symbol)) return 'ETF';
  if (['GC=F', 'SI=F', 'HG=F', 'PL=F', 'PA=F', 'ALI=F'].includes(item.symbol)) return 'METALS';
  if (['CL=F', 'BZ=F', 'NG=F', 'TTF=F', 'RB=F', 'HO=F', 'MTF=F'].includes(item.symbol)) return 'ENERGY';
  return 'AGRI';
}
export function formatPrice(item: Quote) {
  if (item.price == null) return '—';
  const value = item.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: item.symbol.endsWith('=X') ? 4 : 2 });
  if (item.symbol.endsWith('=X') || item.instrumentType === 'INDEX' || item.symbol === '^VIX') return value;
  if (item.currency === 'USX') return `${value}¢`;
  if (item.currency === 'USD') return `$${value}`;
  if (item.currency === 'EUR') return `€${value}`;
  return `${value}${item.currency ? ` ${item.currency}` : ''}`;
}
export function commodityStatusLabel(data: CommodityPayload, status: PanelRuntimeStatus) {
  if (status.error || status.phase === 'stale' || data.status === 'stale') return undefined;
  if (data.status === 'degraded') return 'PARTIAL';
  if (data.items.every(item => quoteState(item) === 'closed')) return 'CLOSED';
  if (data.items.some(item => ['unknown', 'stale'].includes(quoteState(item)))) return 'LIMITED';
  return 'READY';
}
