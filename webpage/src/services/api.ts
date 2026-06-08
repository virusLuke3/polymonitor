import type {
  BootstrapPayload,
  ChartPayload,
  ContentPayload,
  LobPayload,
  MarketAiInsightPayload,
  MarketAiInsightResponse,
  MarketWideAiInsightLens,
  MarketWideAiInsightResponse,
  MarketSummary,
  MarketGroupChartPayload,
  MarketGroupDetail,
  MarketGroupOutcome,
  MarketGroupsPayload,
  MarketGroupSort,
  MarketListItem,
  MarketsPayload,
  MarketWorkspaceHealth,
  OraclePayload,
  PriceSummary,
  QuantBacktestCreatePayload,
  QuantBacktestEquityPoint,
  QuantBacktestMetric,
  QuantBacktestRun,
  QuantBacktestTrade,
  QuantBlockClosePoint,
  QuantBuildRun,
  QuantFrontendPricePoint,
  QuantListPayload,
  QuantMarketSeriesPayload,
  QuantPriceMarket,
  RuntimeMarketGroup,
  RuntimeCryptoFundingPayload,
  RuntimeCommodityTransmissionPayload,
  RuntimeCpiReleaseCalendarPayload,
  RuntimeDefiTokenWatchPayload,
  RuntimeEnergyGasolineShockPayload,
  RuntimeEquityEventCommandPayload,
  RuntimeFinanceLiquidityRegimePayload,
  RuntimeFinanceMarketAtlasPayload,
  RuntimeFinanceWatchPayload,
  RuntimeGlobalWeatherMapPayload,
  RuntimeGridEsportsPayload,
  RuntimeFoodRetailBasketPayload,
  RuntimeGeoSanctionsShockPayload,
  RuntimeInflationNowcastPayload,
  RuntimeF1Payload,
  RuntimeJin10Payload,
  RuntimeMacroDriverPayload,
  RuntimeMacroRegistryPayload,
  RuntimeNbaMatchupPredictorPayload,
  RuntimeNbaPayload,
  RuntimeNbaIntelPayload,
  RuntimeNewMarketSignalsPayload,
  RuntimeOnchainTradfiPerpRadarPayload,
  RuntimePolybeatsPayload,
  RuntimePolymarketMacroMapPayload,
  RuntimeSignalPayload,
  RuntimeSportsOddsPayload,
  RuntimeTechPanelPayload,
  RuntimeWeatherNewsPayload,
  SystemHealth,
  TradeRow,
  WorkspaceBundle,
  WorkspaceDiagnostics,
  WorkspaceIdentity,
} from '@/types';
import type { WorldCupDashboardPayload, WorldCupIntelPayload } from '@/workspaces/worldcup/types';

const RAW_BASE = import.meta.env.DEV
  ? '/wm-api'
  : (import.meta.env.VITE_POLYDATA_API_BASE_URL || '/wm-api');
const API_BASE = RAW_BASE.endsWith('/') ? RAW_BASE.slice(0, -1) : RAW_BASE;
const AGENT_RESPONSE_TTL_MS = 5 * 60 * 1000;

type AgentCacheEntry<T> = {
  expiresAt: number;
  data: T;
};

const agentResponseCache = new Map<string, AgentCacheEntry<unknown>>();
const agentInflight = new Map<string, Promise<unknown>>();

export class ApiTimeoutError extends Error {
  constructor(path: string, timeoutMs: number) {
    super(`API timeout after ${(timeoutMs / 1000).toFixed(1)}s for ${path}`);
    this.name = 'ApiTimeoutError';
  }
}

export function isAbortLikeError(error: unknown) {
  if (!error || typeof error !== 'object') return false;
  const maybe = error as { name?: string; message?: string };
  return maybe.name === 'AbortError'
    || maybe.name === 'ApiTimeoutError'
    || String(maybe.message || '').toLowerCase().includes('signal is aborted');
}

async function apiGetWithTimeout<T>(path: string, timeoutMs = 12000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });
  } catch (error) {
    if (isAbortLikeError(error)) throw new ApiTimeoutError(path, timeoutMs);
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
  if (!response.ok) {
    throw new Error(`API ${response.status} for ${path}`);
  }
  return response.json() as Promise<T>;
}

async function apiGet<T>(path: string): Promise<T> {
  return apiGetWithTimeout<T>(path, 12000);
}

async function apiPostWithTimeout<T>(path: string, body: unknown, timeoutMs = 18000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (error) {
    if (isAbortLikeError(error)) throw new ApiTimeoutError(path, timeoutMs);
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
  if (!response.ok) {
    throw new Error(`API ${response.status} for ${path}`);
  }
  return response.json() as Promise<T>;
}

function agentRequestKey(path: string, body: unknown) {
  return `${path}:${JSON.stringify(body)}`;
}

async function apiPostAgentOnce<T>(path: string, body: unknown, timeoutMs = 18000): Promise<T> {
  const key = agentRequestKey(path, body);
  const now = Date.now();
  const cached = agentResponseCache.get(key);
  if (cached && cached.expiresAt > now) {
    return cached.data as T;
  }
  const inflight = agentInflight.get(key);
  if (inflight) {
    return inflight as Promise<T>;
  }

  const request = apiPostWithTimeout<T>(path, body, timeoutMs)
    .then((data) => {
      agentResponseCache.set(key, { data, expiresAt: Date.now() + AGENT_RESPONSE_TTL_MS });
      return data;
    })
    .finally(() => {
      agentInflight.delete(key);
    });
  agentInflight.set(key, request);
  return request;
}

export function fetchBootstrap() {
  return apiGet<BootstrapPayload>('/bootstrap');
}

export function fetchMarketSearch(query: string, limit = 12) {
  const params = new URLSearchParams({
    q: query.trim(),
    limit: String(limit),
  });
  return apiGetWithTimeout<{ items: MarketListItem[] }>(`/search?${params.toString()}`, 5000);
}

export function fetchMarkets(query = '', pageSize = 160) {
  return fetchMarketsPage(1, query, pageSize);
}

export function fetchMarketsPage(page = 1, query = '', pageSize = 160) {
  const params = new URLSearchParams({
    page: String(page),
    pageSize: String(pageSize),
    status: 'active',
  });
  if (query.trim()) params.set('q', query.trim());
  return apiGetWithTimeout<MarketsPayload>(`/markets?${params.toString()}`, 3500);
}

export async function fetchAllActiveMarkets(query = '', pageSize = 160, maxPages = 8) {
  const items: MarketsPayload['items'] = [];
  let page = 1;
  let total = 0;
  let totalPages = 1;
  let hasMore = false;

  do {
    const payload = await fetchMarketsPage(page, query, pageSize);
    items.push(...(payload.items || []));
    total = payload.pagination?.total || items.length;
    totalPages = payload.pagination?.totalPages || page;
    hasMore = Boolean(payload.pagination?.hasMore);
    page += 1;
  } while (hasMore && page <= maxPages);

  return {
    items,
    pagination: {
      page: 1,
      pageSize: items.length,
      total,
      totalPages,
      hasMore,
    },
  } satisfies MarketsPayload;
}

export function fetchMarketGroups(query = '', pageSize = 80, sort: MarketGroupSort = 'active') {
  const params = new URLSearchParams({
    page: '1',
    pageSize: String(pageSize),
    sort,
  });
  if (query.trim()) params.set('q', query.trim());
  return apiGetWithTimeout<MarketGroupsPayload>(`/market-groups?${params.toString()}`, 3500);
}

export function fetchMarketGroupDetail(eventId: string, timeoutMs = 3500) {
  return apiGetWithTimeout<MarketGroupDetail>(`/market-groups/${encodeURIComponent(eventId)}/detail`, timeoutMs);
}

export function fetchMarketGroupChart(eventId: string, range: '1h' | '6h' | '1d' | '1w' | '1m' | 'all' = '1d', timeoutMs = 4000) {
  return apiGetWithTimeout<MarketGroupChartPayload>(
    `/market-groups/${encodeURIComponent(eventId)}/chart?range=${encodeURIComponent(range)}`,
    timeoutMs,
  );
}

export function fetchSystemHealth() {
  return apiGet<SystemHealth>('/system/health');
}

export function fetchRecentTrades(limit = 24) {
  return apiGet<TradeRow[]>(`/trades/recent?limit=${limit}`);
}

export function fetchRecentOracle(limit = 24) {
  return apiGet<OraclePayload['timeline']>(`/oracle/recent?limit=${limit}`);
}

export type QuantPriceQuery = {
  marketSlug?: string;
  tokenSide?: string;
  tokenId?: string;
  from?: string;
  to?: string;
  fromBlock?: string;
  toBlock?: string;
  limit?: number;
};

export function fetchQuantPriceMarkets(query = '', limit = 40) {
  const params = new URLSearchParams({ limit: String(limit), token_side: 'YES' });
  if (query.trim()) params.set('q', query.trim());
  return apiGetWithTimeout<QuantListPayload<QuantPriceMarket>>(`/quant/markets?${params.toString()}`, 15000);
}

export function fetchQuantPriceEvents(query = '', limit = 40) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (query.trim()) params.set('q', query.trim());
  return apiGetWithTimeout<QuantListPayload<QuantPriceMarket>>(`/quant/events?${params.toString()}`, 15000);
}

function appendQuantParams(query: QuantPriceQuery, mode: 'frontend' | 'block') {
  const params = new URLSearchParams();
  if (query.marketSlug?.trim()) params.set('market_slug', query.marketSlug.trim());
  if (query.tokenSide?.trim()) params.set('token_side', query.tokenSide.trim());
  if (query.tokenId?.trim()) params.set('token_id', query.tokenId.trim());
  if (mode === 'frontend') {
    if (query.from?.trim()) params.set('from', query.from.trim());
    if (query.to?.trim()) params.set('to', query.to.trim());
  } else {
    if (query.fromBlock?.trim()) params.set('from_block', query.fromBlock.trim());
    if (query.toBlock?.trim()) params.set('to_block', query.toBlock.trim());
  }
  params.set('limit', String(query.limit || 240));
  return params.toString();
}

export function fetchQuantFrontendPrices(query: QuantPriceQuery = {}) {
  return apiGetWithTimeout<QuantListPayload<QuantFrontendPricePoint>>(
    `/quant/frontend-prices?${appendQuantParams(query, 'frontend')}`,
    15000,
  );
}

export function fetchQuantBlockClosePrices(query: QuantPriceQuery = {}) {
  return apiGetWithTimeout<QuantListPayload<QuantBlockClosePoint>>(
    `/quant/block-close-prices?${appendQuantParams(query, 'block')}`,
    15000,
  );
}

export function fetchQuantMarketPriceSeries(query: QuantPriceQuery & { priceSource?: string; scope?: string; maxOutcomes?: number } = {}) {
  const params = new URLSearchParams();
  if (query.marketSlug?.trim()) params.set('market_slug', query.marketSlug.trim());
  if (query.tokenSide?.trim()) params.set('token_side', query.tokenSide.trim());
  if (query.priceSource?.trim()) params.set('price_source', query.priceSource.trim());
  if (query.scope?.trim()) params.set('scope', query.scope.trim());
  if (query.from?.trim()) params.set('from', query.from.trim());
  if (query.to?.trim()) params.set('to', query.to.trim());
  if (query.fromBlock?.trim()) params.set('from_block', query.fromBlock.trim());
  if (query.toBlock?.trim()) params.set('to_block', query.toBlock.trim());
  params.set('limit', String(query.limit || 2500));
  params.set('max_outcomes', String(query.maxOutcomes || 24));
  return apiGetWithTimeout<QuantMarketSeriesPayload>(`/quant/market-price-series?${params.toString()}`, 20000);
}

export function fetchQuantEventPriceSeries(query: QuantPriceQuery & { eventSlug?: string; priceSource?: string; maxOutcomes?: number } = {}) {
  const params = new URLSearchParams();
  const eventSlug = query.eventSlug || query.marketSlug;
  if (eventSlug?.trim()) params.set('event_slug', eventSlug.trim());
  if (query.priceSource?.trim()) params.set('price_source', query.priceSource.trim());
  if (query.from?.trim()) params.set('from', query.from.trim());
  if (query.to?.trim()) params.set('to', query.to.trim());
  if (query.fromBlock?.trim()) params.set('from_block', query.fromBlock.trim());
  if (query.toBlock?.trim()) params.set('to_block', query.toBlock.trim());
  params.set('limit', String(query.limit || 2500));
  params.set('max_outcomes', String(query.maxOutcomes || 100));
  return apiGetWithTimeout<QuantMarketSeriesPayload>(`/quant/event-price-series?${params.toString()}`, 25000);
}

export function fetchQuantBuildStatus(source = '', limit = 24) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (source.trim()) params.set('source', source.trim());
  return apiGetWithTimeout<QuantListPayload<QuantBuildRun>>(`/quant/price-build-status?${params.toString()}`, 8000);
}

export function createQuantBacktestRun(payload: QuantBacktestCreatePayload) {
  return apiPostWithTimeout<{ item: QuantBacktestRun; runId: number; status: string }>('/quant/backtest-runs', payload, 30000);
}

export function fetchQuantBacktestRun(runId: number) {
  return apiGetWithTimeout<{ item: QuantBacktestRun }>(`/quant/backtest-runs/${runId}`, 15000);
}

export function fetchQuantBacktestTrades(runId: number, limit = 10000) {
  return apiGetWithTimeout<QuantListPayload<QuantBacktestTrade>>(`/quant/backtest-runs/${runId}/trades?limit=${limit}`, 20000);
}

export function fetchQuantBacktestEquity(runId: number, limit = 25000) {
  return apiGetWithTimeout<QuantListPayload<QuantBacktestEquityPoint>>(`/quant/backtest-runs/${runId}/equity?limit=${limit}`, 20000);
}

export function fetchQuantBacktestMetrics(runId: number) {
  return apiGetWithTimeout<QuantListPayload<QuantBacktestMetric>>(`/quant/backtest-runs/${runId}/metrics`, 15000);
}

export function fetchLatestContent(limit = 8) {
  return apiGet<ContentPayload>(`/content/latest?limit=${limit}`);
}

export function fetchRuntimeCommodities() {
  return apiGet<RuntimeMarketGroup>('/runtime/markets/commodities');
}

export function fetchRuntimeCrypto() {
  return apiGet<RuntimeMarketGroup>('/runtime/markets/crypto');
}

export function fetchRuntimeCryptoFundingWatch(limit = 18) {
  return apiGet<RuntimeCryptoFundingPayload>(`/runtime/crypto/funding-watch?limit=${limit}`);
}

export function fetchRuntimeDefiTokenWatch(limit = 10) {
  return apiGet<RuntimeDefiTokenWatchPayload>(`/runtime/finance/defi-token-watch?limit=${limit}`);
}

export function fetchRuntimeFinanceWatchPanel(panelId: string, limit = 10) {
  return apiGet<RuntimeFinanceWatchPayload>(`/runtime/finance/${panelId}?limit=${limit}`);
}

export function fetchRuntimeTechPanel(panelId: string, limit = 10) {
  return apiGet<RuntimeTechPanelPayload>(`/runtime/tech/${panelId}?limit=${limit}`);
}

export function fetchRuntimeFinanceMarketAtlas(limit = 16) {
  return apiGet<RuntimeFinanceMarketAtlasPayload>(`/runtime/finance/market-atlas?limit=${limit}`);
}

export function fetchRuntimeEquityEventCommand(limit = 12) {
  return apiGet<RuntimeEquityEventCommandPayload>(`/runtime/finance/equity-event-command?limit=${limit}`);
}

export function fetchRuntimeOnchainTradfiPerpRadar(limit = 12) {
  return apiGet<RuntimeOnchainTradfiPerpRadarPayload>(`/runtime/finance/onchain-tradfi-perp-radar?limit=${limit}`);
}

export function fetchRuntimeFinanceLiquidityRegime(limit = 12) {
  return apiGet<RuntimeFinanceLiquidityRegimePayload>(`/runtime/finance/liquidity-regime?limit=${limit}`);
}

export function fetchRuntimeCommodityEquityTransmission(limit = 8) {
  return apiGet<RuntimeCommodityTransmissionPayload>(`/runtime/finance/commodity-equity-transmission?limit=${limit}`);
}

export function fetchRuntimeF1(limit = 10) {
  return apiGet<RuntimeF1Payload>(`/runtime/sports/f1?limit=${limit}`);
}

export function fetchRuntimeJin10(limit = 24) {
  return apiGet<RuntimeJin10Payload>(`/runtime/macro/jin10?limit=${limit}`);
}

export function fetchRuntimeNba(limit = 10) {
  return apiGet<RuntimeNbaPayload>(`/runtime/sports/nba?limit=${limit}`);
}

export function fetchRuntimeNbaIntel(limit = 12) {
  return apiGet<RuntimeNbaIntelPayload>(`/runtime/sports/nba-intel?limit=${limit}`);
}

export function fetchRuntimeNbaMatchupPredictor(limit = 8) {
  return apiGet<RuntimeNbaMatchupPredictorPayload>(`/runtime/sports/nba-matchup-predictor?limit=${limit}`);
}

export function fetchRuntimeGridEsports(limit = 10) {
  return apiGet<RuntimeGridEsportsPayload>(`/runtime/esports/grid-intel?limit=${limit}`);
}

export function fetchRuntimeSportsOdds(limit = 8) {
  return apiGet<RuntimeSportsOddsPayload>(`/runtime/sports/odds-monitor?limit=${limit}`);
}

export function fetchRuntimeWorldCupIntel(limit = 96) {
  return apiGet<WorldCupIntelPayload>(`/runtime/sports/worldcup-intel?limit=${limit}`);
}

export function fetchRuntimeWorldCupDashboard() {
  return apiGet<WorldCupDashboardPayload>('/runtime/worldcup/dashboard');
}

export function fetchRuntimeInflationNowcast() {
  return apiGet<RuntimeInflationNowcastPayload>('/runtime/macro/inflation-nowcast');
}

export function fetchRuntimePolymarketMacroMap(limit = 12) {
  return apiGet<RuntimePolymarketMacroMapPayload>(`/runtime/macro/polymarket-map?limit=${limit}`);
}

export function fetchRuntimeCpiReleaseCalendar(limit = 8) {
  return apiGet<RuntimeCpiReleaseCalendarPayload>(`/runtime/macro/cpi-release-calendar?limit=${limit}`);
}

export function fetchRuntimeEnergyGasolineShock(limit = 6) {
  return apiGet<RuntimeEnergyGasolineShockPayload>(`/runtime/macro/energy-gasoline-shock?limit=${limit}`);
}

export function fetchRuntimeGlobalWeatherMap(limit = 60) {
  return apiGet<RuntimeGlobalWeatherMapPayload>(`/runtime/weather/global-map?limit=${limit}`);
}

export function fetchRuntimeGlobalTemperatureMonitor(limit = 60) {
  return apiGet<RuntimeGlobalWeatherMapPayload>(`/runtime/weather/temperature-monitor?limit=${limit}`);
}

export function fetchRuntimeWeatherNews(limit = 24) {
  return apiGet<RuntimeWeatherNewsPayload>(`/runtime/weather/news?limit=${limit}`);
}

export function fetchRuntimeFoodRetailBasket(limit = 8) {
  return apiGet<RuntimeFoodRetailBasketPayload>(`/runtime/macro/food-retail-basket?limit=${limit}`);
}

export function fetchRuntimeSupplyTariffImportWatch(limit = 8) {
  return apiGet<RuntimeMacroDriverPayload>(`/runtime/macro/supply-tariff-import-watch?limit=${limit}`);
}

export function fetchRuntimeShelterRentOerPressure(limit = 8) {
  return apiGet<RuntimeMacroDriverPayload>(`/runtime/macro/shelter-rent-oer-pressure?limit=${limit}`);
}

export function fetchRuntimeLaborWageServicesPressure(limit = 8) {
  return apiGet<RuntimeMacroDriverPayload>(`/runtime/macro/labor-wage-services-pressure?limit=${limit}`);
}

export function fetchRuntimeGrowthDemandRecessionTracker(limit = 8) {
  return apiGet<RuntimeMacroDriverPayload>(`/runtime/macro/growth-demand-recession-tracker?limit=${limit}`);
}

export function fetchRuntimeFedRatesPolymarketGap(limit = 8) {
  return apiGet<RuntimeMacroDriverPayload>(`/runtime/macro/fed-rates-polymarket-gap?limit=${limit}`);
}

export function fetchRuntimeCpiReleaseCommandCenter(limit = 36) {
  return apiGet<RuntimeMacroRegistryPayload>(`/runtime/macro/cpi-release-command-center?limit=${limit}`);
}

export function fetchRuntimeCpiComponentsPressureRegistry(limit = 48) {
  return apiGet<RuntimeMacroRegistryPayload>(`/runtime/macro/cpi-components-pressure-registry?limit=${limit}`);
}

export function fetchRuntimeGoodsTariffSupplyWatch(limit = 36) {
  return apiGet<RuntimeMacroRegistryPayload>(`/runtime/macro/goods-tariff-supply-watch?limit=${limit}`);
}

export function fetchRuntimeLaborServicesInflationMonitor(limit = 36) {
  return apiGet<RuntimeMacroRegistryPayload>(`/runtime/macro/labor-services-inflation-monitor?limit=${limit}`);
}

export function fetchRuntimeFedReactionGrowthRiskBoard(limit = 36) {
  return apiGet<RuntimeMacroRegistryPayload>(`/runtime/macro/fed-reaction-growth-risk-board?limit=${limit}`);
}

export function fetchRuntimeGeoSanctionsShock(limit = 2000) {
  return apiGet<RuntimeGeoSanctionsShockPayload>(`/runtime/world/geo-sanctions-shock?limit=${limit}`);
}

export function fetchRuntimeAlpha(limit = 8) {
  return apiGet<RuntimeSignalPayload>(`/runtime/signals/alpha?limit=${limit}`);
}

export function fetchRuntimePolybeats(limit = 8) {
  return apiGet<RuntimePolybeatsPayload>(`/runtime/signals/polybeats?limit=${limit}`);
}

export function fetchRuntimeNewMarketSignals(limit = 12) {
  return apiGet<RuntimeNewMarketSignalsPayload>(`/runtime/markets/new-signals?limit=${limit}`);
}

export function fetchRuntimeWhales(limit = 14) {
  return apiGet<RuntimeSignalPayload>(`/runtime/trades/whales?limit=${limit}`);
}

export function fetchRuntimeSuspicious(limit = 12) {
  return apiGet<RuntimeSignalPayload>(`/runtime/trades/suspicious?limit=${limit}`);
}

export type RuntimePanelsPayload = {
  generatedAt?: string;
  status?: string;
  panels?: Record<string, unknown>;
  errors?: Record<string, string>;
};

export function fetchRuntimePanels(panelIds: string[], limits: Record<string, number> = {}) {
  const ids = [...new Set(panelIds.map((panelId) => panelId.trim()).filter(Boolean))];
  const params = new URLSearchParams({ ids: ids.join(',') });
  ids.forEach((panelId) => {
    const limit = limits[panelId];
    if (typeof limit === 'number' && Number.isFinite(limit)) params.set(`limit.${panelId}`, String(limit));
  });
  return apiGet<RuntimePanelsPayload>(`/runtime/panels?${params.toString()}`);
}

export function fetchMarketSummary(marketId: number, timeoutMs = 3500) {
  return apiGetWithTimeout<MarketSummary>(`/markets/${marketId}`, timeoutMs);
}

type MarketDetailBundlePayload = {
  market?: MarketSummary | null;
  identity?: WorkspaceIdentity | null;
  diagnostics?: WorkspaceDiagnostics | null;
  health?: MarketWorkspaceHealth | null;
  group?: MarketGroupDetail | null;
  selectedOutcome?: MarketGroupOutcome | null;
  price?: PriceSummary | null;
  chart?: ChartPayload | null;
  priceSeries?: ChartPayload['points'];
  trades?: TradeRow[];
  oracle?: OraclePayload | null;
  oracleEvents?: OraclePayload['timeline'];
  content?: ContentPayload | null;
  servingSource?: string | null;
  servingUpdatedAt?: string | null;
  generatedAt?: string | null;
};

function normalizeMarketBundlePayload(payload: MarketDetailBundlePayload, marketId: number): WorkspaceBundle {
  const chart = payload.chart || (
    payload.priceSeries
      ? {
          marketId,
          localMarketId: marketId,
          range: '1d',
          interval: '5m',
          kind: 'probability',
          points: payload.priceSeries,
        }
      : null
  );
  return {
    market: payload.market || null,
    identity: payload.identity || null,
    diagnostics: payload.diagnostics || null,
    health: payload.health || null,
    group: payload.group || null,
    selectedOutcome: payload.selectedOutcome || null,
    price: payload.price || null,
    chart,
    trades: payload.trades || [],
    oracle: payload.oracle || (
      payload.oracleEvents
        ? {
            marketId,
            localMarketId: marketId,
            timeline: payload.oracleEvents,
          }
        : null
    ),
    content: payload.content || null,
    lob: null,
  };
}

export async function fetchMarketDetailBundle(marketId: number, timeoutMs = 6500): Promise<WorkspaceBundle> {
  const payload = await apiGetWithTimeout<MarketDetailBundlePayload>(`/markets/${marketId}/detail`, timeoutMs);
  return normalizeMarketBundlePayload(payload, marketId);
}

export async function fetchMarketWorkspaceBundle(marketId: number, timeoutMs = 6500): Promise<WorkspaceBundle> {
  const payload = await apiGetWithTimeout<MarketDetailBundlePayload>(`/markets/${marketId}/workspace`, timeoutMs);
  return normalizeMarketBundlePayload(payload, marketId);
}

export function fetchMarketPrice(marketId: number, timeoutMs = 5000) {
  return apiGetWithTimeout<PriceSummary>(`/markets/${marketId}/price`, timeoutMs);
}

type MarketChartRange = '1h' | '6h' | '1d' | '1w' | '1m' | 'all' | string;

function intervalForMarketChartRange(range: MarketChartRange) {
  switch (range) {
    case '1h':
      return '1m';
    case '6h':
      return '3m';
    case '1d':
      return '5m';
    case '1w':
      return '1h';
    case '1m':
    case 'all':
      return '4h';
    default:
      return '5m';
  }
}

export function fetchMarketChart(
  marketId: number,
  range: MarketChartRange = '1d',
  interval = intervalForMarketChartRange(range),
  timeoutMs = 6500,
) {
  const params = new URLSearchParams({ range, interval });
  return apiGetWithTimeout<ChartPayload>(`/markets/${marketId}/chart?${params.toString()}`, timeoutMs);
}

export function fetchMarketTrades(marketId: number, limit = 24, timeoutMs = 4000) {
  return apiGetWithTimeout<TradeRow[]>(`/markets/${marketId}/trades?limit=${limit}`, timeoutMs);
}

export function fetchMarketOracle(marketId: number, timeoutMs = 2200) {
  return apiGetWithTimeout<OraclePayload>(`/markets/${marketId}/oracle`, timeoutMs);
}

export function fetchMarketContent(marketId: number, limit = 20, timeoutMs = 5000) {
  return apiGetWithTimeout<ContentPayload>(`/content/market/${marketId}?limit=${limit}`, timeoutMs);
}

export function fetchMarketLob(marketId: number, timeoutMs = 4000) {
  return apiGetWithTimeout<LobPayload>(`/runtime/lob/${marketId}`, timeoutMs);
}

export function fetchMarketLobByToken(tokenId: string, title = '', noTokenId = '', timeoutMs = 4000) {
  const params = new URLSearchParams();
  if (title.trim()) params.set('title', title.trim());
  if (noTokenId.trim()) params.set('noTokenId', noTokenId.trim());
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return apiGetWithTimeout<LobPayload>(`/runtime/lob/token/${encodeURIComponent(tokenId)}${suffix}`, timeoutMs);
}

function preferLoadedBundle(primary: WorkspaceBundle, secondary: WorkspaceBundle): WorkspaceBundle {
  const primaryOracle = primary.oracle;
  const secondaryOracle = secondary.oracle;
  return {
    market: primary.market || secondary.market,
    identity: primary.identity || secondary.identity,
    diagnostics: primary.diagnostics || secondary.diagnostics,
    health: primary.health || secondary.health,
    group: primary.group || secondary.group,
    selectedOutcome: primary.selectedOutcome || secondary.selectedOutcome,
    price: primary.price || secondary.price,
    chart: primary.chart?.points?.length ? primary.chart : secondary.chart,
    trades: primary.trades?.length ? primary.trades : secondary.trades,
    oracle: primaryOracle ? primaryOracle : secondaryOracle,
    content: primary.content?.items?.length ? primary.content : secondary.content,
    lob: primary.lob || secondary.lob,
  };
}

const workspaceBundleInflight = new Map<string, Promise<WorkspaceBundle>>();

function emptyWorkspaceBundle(): WorkspaceBundle {
  return {
    market: null,
    identity: null,
    diagnostics: null,
    health: null,
    group: null,
    selectedOutcome: null,
    price: null,
    chart: null,
    trades: [],
    oracle: null,
    content: null,
    lob: null,
  };
}

export function fetchMarketAiInsights(payload: MarketAiInsightPayload, timeoutMs = 20000) {
  return apiPostAgentOnce<MarketAiInsightResponse>('/agent/market-insights', payload, timeoutMs);
}

export function fetchMarketWideAiSnapshot(lens: MarketWideAiInsightLens, timeoutMs = 8000) {
  return apiGetWithTimeout<MarketWideAiInsightResponse>(
    `/runtime/agent/market-wide-insights/${encodeURIComponent(lens)}`,
    timeoutMs,
  );
}

export async function fetchWorkspaceBundle(marketId: number, options: { includeContent?: boolean; includeLob?: boolean } = {}): Promise<WorkspaceBundle> {
  const includeContent = Boolean(options.includeContent);
  const includeLob = Boolean(options.includeLob);
  const inflightKey = `${marketId}:${includeContent ? 'content' : 'base'}:${includeLob ? 'lob' : 'no-lob'}`;
  const inflight = workspaceBundleInflight.get(inflightKey);
  if (inflight) return inflight;

  const request = (async () => {
    const contentPromise = includeContent
      ? fetchMarketContent(marketId, 20, 3800)
      : Promise.resolve(null);
    const lobPromise = includeLob ? fetchMarketLob(marketId, 1800) : Promise.resolve(null);
    const detailPromise = fetchMarketWorkspaceBundle(marketId, 4200)
      .catch(() => fetchMarketDetailBundle(marketId, 4200));
    const [detailResult, contentResult, lobResult] = await Promise.allSettled([detailPromise, contentPromise, lobPromise]);
    const detailBundle = detailResult.status === 'fulfilled' ? detailResult.value : emptyWorkspaceBundle();
    const secondary: WorkspaceBundle = {
      market: null,
      identity: null,
      diagnostics: null,
      health: null,
      group: null,
      selectedOutcome: null,
      price: null,
      chart: null,
      trades: [],
      oracle: null,
      content: contentResult.status === 'fulfilled' ? contentResult.value : null,
      lob: includeLob && lobResult.status === 'fulfilled' ? lobResult.value : null,
    };
    return preferLoadedBundle(detailBundle, secondary);
  })();

  workspaceBundleInflight.set(inflightKey, request);
  void request.finally(() => workspaceBundleInflight.delete(inflightKey));
  return request;
}
