import { RuntimeResponseError } from '@/panels/runtime-store';

export type Point = { t: number; v: number };
export type Asset = 'BTC' | 'ETH' | 'SOL' | 'XRP';
export const ASSETS: Asset[] = ['BTC', 'ETH', 'SOL', 'XRP'];
export type Quote = { price?: number | null; bid?: number | null; ask?: number | null; sourceResponseAt?: string; mark?: number | null; index?: number | null; oi?: number | null; oiValue?: number | null; fundingPercent?: number | null };
export type CryptoAsset = {
  asset?: Asset; venue?: string; symbol?: string; status?: string; quoteCurrency?: string;
  spot?: Quote; linear?: Quote; spotHistory?: Point[]; linearHistory?: Point[]; oiHistory?: Point[];
  fundingHistory?: Point[]; basisHistory?: Point[]; basisBps?: number | null; premiumBps?: number | null;
  flow?: { buy: number | null; sell: number | null; net: number | null; count: number; limit: number; from: number | null; to: number | null; cvd: Point[]; trades: { id: string; t: number; price: number; size: number; side: string }[] };
  depth?: { bids: number[][]; asks: number[][]; levels: number; imbalance: number | null; observedAt?: string; method: string };
  errors?: Record<string, string>;
};
export type Reference = {
  status?: string; error?: string; marketError?: string; history?: Point[]; spotHistory?: Point[];
  latest?: { value?: string; full_accuracy_value?: string; event_at_ms?: number; received_at_ms?: number; feed_id?: string; precision?: string; window_seconds?: number };
  market?: { asset: string; market_id: string; condition_id: string; slug: string; outcomes: Record<string,string>; starts_at_ms: number; ends_at_ms: number;
    rule_version: string; rule_url: string; window_seconds: number; price_kind: string; comparator: string;
    anchor?: { value: string; source: string; precision: string }; opening_alignment?: { status: string } };
  quotes?: Record<string, { token: string; bid: number; ask: number; observedAt: string; receivedAt: number; history?: Point[]; quality?: string; snapshotAt?: string; upstreamCompleteness?: string }>;
};
export type OptionBand = { strike: number; lowerStrike: number; upperStrike: number; probability: number; low: number; high: number; iv: number | null; instruments: string[] };
export type OptionExpiry = { expiry: string; underlying: number; bands: OptionBand[] };
export type Stablecoin = { asset: string; source: string; price: number | null; deviationBps: number | null; receivedAt?: string; status: string; history?: Point[]; observedStressSeconds?: number | null };
export type InflowRow = { date: string; exchange: string; inflow: number; outflow: number; net: number; transactions: number };
export type StrategyInputs = {
  kind: 'crypto-strategy'; schemaVersion: 1; generatedAt: string; collectedAt: number; status: string;
  assets: Partial<Record<Asset,CryptoAsset>>; references: Partial<Record<Asset,Reference>>;
  options: Partial<Record<Asset,{ asset?: string; source?: string; observedAt?: string; method?: string; expiries?: OptionExpiry[] }>>;
  stablecoins: Stablecoin[]; inflows: { mode: string; rows: InflowRow[]; datasetId?: string; transactions?: number; labelSemantics?: string; reason?: string };
};

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const series = (v: unknown) => v === undefined || Array.isArray(v) && v.every(p => object(p) && finite(p.t) && finite(p.v));
const invalid = () => { throw new RuntimeResponseError('Invalid crypto source fields', false); };
export function parseInputs(value: unknown): StrategyInputs {
  if (!object(value) || value.kind !== 'crypto-strategy' || value.schemaVersion !== 1) throw new RuntimeResponseError('Crypto input identity mismatch', false);
  if (value.status === 'warming' || typeof value.generatedAt !== 'string' || !Number.isFinite(Date.parse(value.generatedAt))) throw new RuntimeResponseError('Crypto source is warming');
  if (!object(value.assets) || !object(value.references) || !object(value.options) || !Array.isArray(value.stablecoins)
      || !object(value.inflows) || !Array.isArray(value.inflows.rows)) throw new RuntimeResponseError('Invalid crypto input schema', false);
  for (const [asset, row] of Object.entries(value.assets)) {
    if (!ASSETS.includes(asset as Asset) || !object(row) || (row.asset != null && row.asset !== asset)) throw new RuntimeResponseError('Crypto asset mismatch', false);
    for (const key of ['spotHistory','linearHistory','oiHistory','fundingHistory','basisHistory']) if (!series(row[key])) invalid();
    if (row.flow != null && (!object(row.flow) || !series(row.flow.cvd) || !Array.isArray(row.flow.trades)
      || !row.flow.trades.every(r => object(r) && finite(r.t) && finite(r.price) && finite(r.size) && typeof r.id === 'string'))) invalid();
    if (row.depth != null && (!object(row.depth) || !['bids','asks'].every(k => Array.isArray(row.depth && (row.depth as Record<string, unknown>)[k])
      && ((row.depth as Record<string, unknown>)[k] as unknown[]).every(r => Array.isArray(r) && r.length >= 2 && finite(r[0]) && finite(r[1]))))) invalid();
  }
  for (const [asset,row] of Object.entries(value.references)) {
    if (!ASSETS.includes(asset as Asset) || !object(row) || !series(row.history) || !series(row.spotHistory)) invalid();
    if (!object(row)) continue;
    if (row.market != null && (!object(row.market) || row.market.asset !== asset || !finite(row.market.ends_at_ms) || !finite(row.market.starts_at_ms))) invalid();
    if (row.quotes != null && (!object(row.quotes) || !Object.values(row.quotes).every(q => object(q) && finite(q.bid) && finite(q.ask)
      && q.bid >= 0 && q.ask <= 1 && q.bid <= q.ask && finite(q.receivedAt) && series(q.history)))) invalid();
  }
  for (const row of Object.values(value.options)) {
    if (!object(row) || (row.expiries != null && (!Array.isArray(row.expiries) || !row.expiries.every(e => object(e)
      && typeof e.expiry === 'string' && Number.isFinite(Date.parse(e.expiry)) && finite(e.underlying) && e.underlying > 0 && Array.isArray(e.bands)
      && e.bands.every(b => object(b) && ['strike','lowerStrike','upperStrike','probability','low','high'].every(k => finite(b[k]))
      && Number(b.probability) >= 0 && Number(b.probability) <= 1 && Array.isArray(b.instruments) && b.instruments.every(i => typeof i === 'string')))))) invalid();
  }
  if (!value.stablecoins.every(r => object(r) && typeof r.asset === 'string' && typeof r.source === 'string'
    && (r.price == null || finite(r.price) && r.price > 0) && series(r.history))) invalid();
  if (!value.inflows.rows.every(r => object(r) && typeof r.date === 'string' && Number.isFinite(Date.parse(r.date))
    && typeof r.exchange === 'string' && ['inflow','outflow','net','transactions'].every(k => finite(r[k])))) invalid();
  return value as unknown as StrategyInputs;
}

export function validPoints(points: Point[] = []): Point[] {
  return (Array.isArray(points) ? points : []).filter(p => p && Number.isFinite(p.t) && Number.isFinite(p.v)).sort((a,b) => a.t-b.t);
}
export function change(points: Point[] = [], minutes = 15): number | null {
  const rows = validPoints(points), last = rows[rows.length-1];
  if (!last) return null;
  const target = last.t - minutes * 60000;
  const first = rows.find(p => p.t >= target && p.t <= target + 60000);
  return first && first.t < last.t && first.v > 0 ? (last.v / first.v - 1) * 100 : null;
}
export function referenceUsable(ref: Reference | undefined, now = Date.now()) {
  const market = ref?.market, at = ref?.latest?.event_at_ms;
  return !!market && market.starts_at_ms <= now && market.ends_at_ms > now && !!at && now-at >= -1000 && now-at <= 15000
    && ref?.latest?.window_seconds === market.window_seconds && ref.status === 'ok';
}
export function marketUrl(ref?: Reference): string | null {
  const slug = ref?.market?.slug;
  return slug && /^[a-zA-Z0-9-]+$/.test(slug) ? `https://polymarket.com/event/${slug}` : null;
}
