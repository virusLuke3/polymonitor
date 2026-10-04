import type { PanelRuntimeStatus } from '@/panels/types';
import { RuntimeResponseError } from '@/panels/runtime-store';

export const REFRESH_MS = 15_000, MAX_AGE_MS = 90_000, RETAIN_MS = 900_000;
export type FundingQuote = {
  id: string; asset: string; exchange: 'Binance' | 'Bybit'; symbol: string;
  fundingRatePercent: number; fundingIntervalHours: number | null; fundingRatePercent8h: number | null;
  annualizedPercent: number | null; updatedAt: string; quoteObservedAt: string | null; sourceResponseAt: string | null;
  fetchedAt: string; eligibilityCheckedAt: string; nextFundingTime: string | null; sourceUrl: string;
  acquisitionState: 'ok' | 'retained';
};
export type FundingMarket = { id: string; title: string; url: string; endAt: string | null; relation: 'price-asset' | 'asset-context' };
export type FundingAsset = { id: string; asset: string; quotes: FundingQuote[]; marketCount: number; priceMarketCount: number; relatedMarkets: FundingMarket[] };
export type FundingPayload = {
  kind: 'crypto-funding'; schemaVersion: 3; generatedAt: string; status: string; refreshIntervalSeconds: number;
  assets: FundingAsset[]; sources: Record<string, string>;
  sourceDetails: Record<string, { status: string; catalogStatus: string; lastAttemptAt: string | null; lastSuccessAt: string | null; errorCode: string | null }>;
  coverage: { expectedQuotes: number; succeeded: number; retained: number; missing: number; unknownPeriod: number; totalAssets: number;
    unavailableAssets: Array<{ asset: string; reason: string; marketCount: number }> };
  marketUniverse: { status: string; observedAt: string | null; scannedEvents: number; truncated: boolean };
};
const record = (value: unknown): Record<string, unknown> => value != null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const finite = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;
const count = (value: unknown) => Math.max(0, Math.floor(finite(value) ?? 0));
const date = (value: unknown): string | null => typeof value === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value)) ? value : null;
const token = (value: unknown) => typeof value === 'string' && /^[A-Z0-9]{1,24}$/.test(value) ? value : null;
const timely = (value: string, now: number, maxAge: number) => now - Date.parse(value) >= -30_000 && now - Date.parse(value) <= maxAge;

function parseQuote(value: unknown, asset: string, now: number): FundingQuote | null {
  const raw = record(value), symbol = token(raw.symbol), percent = finite(raw.fundingRatePercent), ratio = finite(raw.fundingRate);
  const updatedAt = date(raw.updatedAt), fetchedAt = date(raw.fetchedAt), eligibilityCheckedAt = date(raw.eligibilityCheckedAt);
  if (!symbol || raw.asset !== asset || percent == null || ratio == null || Math.abs(ratio) > 1 || Math.abs(percent - ratio * 100) > 1e-8) return null;
  if (raw.eligible !== true || raw.contractType !== 'perpetual' || raw.settleCoin !== 'USDT') return null;
  if (raw.exchange !== 'Binance' && raw.exchange !== 'Bybit') return null;
  if (raw.contractStatus !== (raw.exchange === 'Binance' ? 'TRADING' : 'Trading')) return null;
  if (raw.id !== `${raw.exchange.toLowerCase()}:${symbol}` || !symbol.endsWith('USDT')) return null;
  const scaled = new Set(['PEPE', 'SHIB', 'BONK', 'FLOKI', 'XEC', 'SATS', 'RATS', 'CAT']);
  if (symbol !== `${asset}USDT` && !(scaled.has(asset) && new RegExp(`^(1000000|10000|1000)${asset}USDT$`).test(symbol))) return null;
  if (!updatedAt || !fetchedAt || !eligibilityCheckedAt || !timely(updatedAt, now, RETAIN_MS) || !timely(fetchedAt, now, RETAIN_MS) || !timely(eligibilityCheckedAt, now, 1_800_000)) return null;
  const quoteObservedAt = date(raw.quoteObservedAt), sourceResponseAt = date(raw.sourceResponseAt);
  if ((raw.exchange === 'Binance' ? quoteObservedAt : sourceResponseAt) !== updatedAt) return null;
  const rawPeriod = finite(raw.fundingIntervalHours), period = rawPeriod != null && rawPeriod > 0 && rawPeriod <= 24 ? rawPeriod : null;
  return {
    id: raw.id as string, asset, exchange: raw.exchange, symbol, fundingRatePercent: percent,
    fundingIntervalHours: period, fundingRatePercent8h: period ? percent * 8 / period : null,
    annualizedPercent: period ? percent * 24 / period * 365 : null,
    updatedAt, fetchedAt, eligibilityCheckedAt, quoteObservedAt, sourceResponseAt,
    nextFundingTime: date(raw.nextFundingTime),
    sourceUrl: raw.exchange === 'Binance' ? `https://fapi.binance.com/fapi/v1/premiumIndex?symbol=${symbol}`
      : `https://api.bybit.com/v5/market/tickers?category=linear&symbol=${symbol}`,
    acquisitionState: raw.acquisitionState === 'retained' ? 'retained' : 'ok',
  };
}

export function parseFunding(value: unknown, now = Date.now()): FundingPayload {
  const raw = record(value), generatedAt = date(raw.generatedAt);
  if (raw.kind !== 'crypto-funding' || raw.schemaVersion !== 3) throw new RuntimeResponseError('Funding snapshot identity mismatch', false);
  if (!generatedAt || !Array.isArray(raw.assets) || ['warming', 'invalid', 'error', 'unavailable'].includes(String(raw.status))) throw new RuntimeResponseError('Funding sources are not ready; retrying automatically');
  if (!timely(generatedAt, now, RETAIN_MS)) throw new RuntimeResponseError('Funding snapshot is outside its retention window');
  const seen = new Set<string>(), assets: FundingAsset[] = [];
  let rejected = 0;
  for (const entry of raw.assets.slice(0, 120)) {
    const row = record(entry), asset = token(row.asset);
    if (!asset || row.id !== asset || !Array.isArray(row.quotes)) { rejected++; continue; }
    const quotes: FundingQuote[] = [];
    for (const candidate of row.quotes.slice(0, 4)) {
      const quote = parseQuote(candidate, asset, now);
      if (!quote || seen.has(quote.id)) { rejected++; continue; }
      seen.add(quote.id); quotes.push(quote);
    }
    if (!quotes.length) continue;
    const relatedMarkets = (Array.isArray(row.relatedMarkets) ? row.relatedMarkets : []).slice(0, 3).flatMap(value => {
      const market = record(value), endAt = date(market.endAt);
      if (typeof market.id !== 'string' || typeof market.title !== 'string' || typeof market.url !== 'string'
        || !/^https:\/\/polymarket\.com\/event\/[a-zA-Z0-9_-]+$/.test(market.url) || (endAt && Date.parse(endAt) <= now)) return [];
      return [{ id: market.id, title: market.title.slice(0, 220), url: market.url, endAt,
        relation: market.relation === 'price-asset' ? 'price-asset' as const : 'asset-context' as const }];
    });
    assets.push({ id: asset, asset, quotes, marketCount: count(row.marketCount), priceMarketCount: count(row.priceMarketCount), relatedMarkets });
  }
  if (!assets.length) throw new RuntimeResponseError('No qualified funding quotes are available; retrying automatically');
  const quotes = assets.flatMap(asset => asset.quotes), fresh = quotes.filter(quote => quoteState(quote, now) === 'fresh');
  const rawCoverage = record(raw.coverage), sourceDetails: FundingPayload['sourceDetails'] = {};
  for (const [key, value] of Object.entries(record(raw.sourceDetails))) {
    const detail = record(value);
    sourceDetails[key] = { status: String(detail.status || 'unknown'), catalogStatus: String(detail.catalogStatus || 'unknown'),
      lastAttemptAt: date(detail.lastAttemptAt), lastSuccessAt: date(detail.lastSuccessAt), errorCode: typeof detail.errorCode === 'string' ? detail.errorCode : null };
  }
  const sources = Object.fromEntries(Object.entries(record(raw.sources)).map(([key, state]) => [key, String(state)]));
  const marketUniverse = record(raw.marketUniverse);
  return {
    kind: 'crypto-funding', schemaVersion: 3, generatedAt,
    status: raw.status === 'stale' || !fresh.length ? 'stale' : rejected || fresh.length !== quotes.length || fresh.some(q => q.fundingIntervalHours == null)
      || raw.status !== 'ok' || Object.values(sources).some(state => state !== 'ok') ? 'degraded' : 'ok',
    refreshIntervalSeconds: Math.max(15, Math.min(300, finite(raw.refreshIntervalSeconds) ?? 30)), assets, sources, sourceDetails,
    coverage: { expectedQuotes: count(rawCoverage.expectedQuotes), succeeded: fresh.length,
      retained: quotes.filter(q => q.acquisitionState === 'retained').length, missing: count(rawCoverage.missing) + rejected,
      unknownPeriod: quotes.filter(q => q.fundingIntervalHours == null).length, totalAssets: count(raw.totalAssets) || assets.length,
      unavailableAssets: (Array.isArray(rawCoverage.unavailableAssets) ? rawCoverage.unavailableAssets : []).slice(0, 120).flatMap(value => {
        const item = record(value), asset = token(item.asset);
        return asset ? [{ asset, reason: String(item.reason || 'eligibility-unknown'), marketCount: count(item.marketCount) }] : [];
      }) },
    marketUniverse: { status: String(marketUniverse.status || 'unknown'), observedAt: date(marketUniverse.observedAt),
      scannedEvents: count(marketUniverse.scannedEvents), truncated: marketUniverse.truncated === true },
  };
}

export function quoteState(quote: FundingQuote, now = Date.now()) {
  if (!timely(quote.updatedAt, now, MAX_AGE_MS)) return 'stale';
  return quote.acquisitionState === 'retained' ? 'retained' : 'fresh';
}

export function assetStats(asset: FundingAsset, now = Date.now()) {
  const quotes = asset.quotes.filter(quote => quoteState(quote, now) === 'fresh' && quote.fundingRatePercent8h != null);
  const strongest = [...quotes].sort((a, b) => Math.abs(b.fundingRatePercent8h!) - Math.abs(a.fundingRatePercent8h!))[0] ?? null;
  const rates = quotes.map(quote => quote.fundingRatePercent8h!);
  const mean = rates.length ? rates.reduce((sum, value) => sum + value, 0) / rates.length : null;
  const positive = rates.some(value => value > 0), negative = rates.some(value => value < 0);
  return { strongest, mean, freshVenues: new Set(quotes.map(q => q.exchange)).size,
    bias: positive && negative ? 'mixed' : positive ? 'longs-pay' : negative ? 'shorts-pay' : rates.length ? 'flat' : 'unknown',
    spread: rates.length >= 2 ? Math.max(...rates) - Math.min(...rates) : null };
}

export function fundingStats(assets: FundingAsset[], now = Date.now()) {
  const quotes = assets.flatMap(asset => asset.quotes).filter(quote => quoteState(quote, now) === 'fresh' && quote.fundingRatePercent8h != null);
  const rows = assets.map(asset => ({ asset, ...assetStats(asset, now) }));
  const top = [...rows].filter(row => row.strongest).sort((a, b) => Math.abs(b.strongest!.fundingRatePercent8h!) - Math.abs(a.strongest!.fundingRatePercent8h!))[0];
  return { top: top?.asset.asset ?? null,
    averageAbs: quotes.length ? quotes.reduce((sum, quote) => sum + Math.abs(quote.fundingRatePercent8h!), 0) / quotes.length : null,
    alerts: rows.filter(row => row.strongest && Math.abs(row.strongest.fundingRatePercent8h!) >= 0.015).length,
    comparableAssets: rows.filter(row => row.strongest).length, quotes: quotes.length };
}

export function percent(value: number | null | undefined, digits = 4) {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

export function fundingStatusLabel(data: FundingPayload, status: PanelRuntimeStatus) {
  if (status.error || status.phase === 'stale' || data.status === 'stale') return undefined;
  if (data.status === 'degraded' || data.assets.some(asset => asset.quotes.some(q => quoteState(q) !== 'fresh'))) return 'PARTIAL';
  return 'READY';
}
