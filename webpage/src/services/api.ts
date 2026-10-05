import type {
  BootstrapPayload,
  ChartPayload,
  ContentPayload,
  LobPayload,
  MarketWideAiInsightLens,
  MarketWideAiInsightResponse,
  MarketSummary,
  MarketGroupChartPayload,
  MarketGroupDetail,
  MarketGroupOutcome,
  MarketGroupsPayload,
  MarketGroupSort,
  MarketListItem,
  MarketDataQualityPayload,
  MarketsPayload,
  MarketWorkspaceHealth,
  MarketWorkspaceEvidence,
  OraclePayload,
  PriceSummary,
  RuntimeMarketGroup,
  RuntimeBreakingEventRadarPayload,
  RuntimeCommodityTransmissionPayload,
  RuntimeCpiReleaseCalendarPayload,
  RuntimeDefiTokenWatchPayload,
  RuntimeEnergyGasolineShockPayload,
  RuntimeFinanceWatchPayload,
  RuntimeGlobalWeatherMapPayload,
  RuntimeGlobalTransportShippingPayload,
  RuntimeGridEsportsPayload,
  RuntimeFoodRetailBasketPayload,
  RuntimeGeoSanctionsShockPayload,
  RuntimeInflationNowcastPayload,
  RuntimeF1Payload,
  RuntimeJin10Payload,
  RuntimeMacroDriverPayload,
  RuntimeMacroRegistryPayload,
  RuntimeMarketYoutubeChannelsPayload,
  RuntimeMarketTvWirePayload,
  RuntimeCpiReleaseCommandPayload,
  RuntimeNbaMatchupPredictorPayload,
  RuntimeNbaPayload,
  RuntimeNbaIntelPayload,
  RuntimeNewMarketSignalsPayload,
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
import type {
  HazardDetailResponse,
  HazardMapResponse,
  HazardMarketLinksResponse,
} from '@/features/world-event-map/domain/types';

const RAW_BASE = import.meta.env.VITE_POLYDATA_API_BASE_URL || '/wm-api';
const API_BASE = RAW_BASE.endsWith('/') ? RAW_BASE.slice(0, -1) : RAW_BASE;

export class ApiHttpError extends Error {
  readonly retryAfterMs: number | null;
  constructor(readonly status: number, path: string, retryAfter: string | null, readonly verificationPending = false) {
    super(`API ${status} for ${path}`); this.name = 'ApiHttpError';
    const seconds = Number(retryAfter);
    this.retryAfterMs = retryAfter == null ? null : Number.isFinite(seconds) ? Math.max(0, seconds * 1000) : Math.max(0, Date.parse(retryAfter) - Date.now());
  }
}

export class ApiTimeoutError extends Error {
  constructor(path: string, timeoutMs: number) {
    super(`API timeout after ${(timeoutMs / 1000).toFixed(1)}s for ${path}`);
    this.name = 'ApiTimeoutError';
  }
}

function isAbortLikeError(error: unknown) {
  if (!error || typeof error !== 'object') return false;
  const maybe = error as { name?: string; message?: string };
  return maybe.name === 'AbortError'
    || maybe.name === 'ApiTimeoutError'
    || String(maybe.message || '').toLowerCase().includes('signal is aborted');
}

type RuntimeRequest = { priority: number; queuedAt: number; start: () => void; signal?: AbortSignal; abort: () => void };
const runtimeRequests: RuntimeRequest[] = [];
let runtimeRunning = 0;
let runtimePumpScheduled = false;

/** One admission budget for Runtime's shared panels and map sources. No cache or refresh loop. */
export function withRuntimeRequestBudget<T>(run: () => Promise<T>, signal?: AbortSignal, priority = 2): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const abort = () => {
      const index = runtimeRequests.indexOf(task);
      if (index >= 0) runtimeRequests.splice(index, 1);
      signal?.removeEventListener('abort', abort);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const task: RuntimeRequest = { priority, queuedAt: performance.now(), signal, abort, start: () => {
      signal?.removeEventListener('abort', abort);
      runtimeRunning++;
      // The API deadline begins inside run(), after admission, and covers JSON.
      void Promise.resolve().then(run).then(resolve, reject).finally(() => {
        runtimeRunning--; pumpRuntimeRequests();
      });
    }};
    if (signal?.aborted) { abort(); return; }
    signal?.addEventListener('abort', abort, { once: true });
    runtimeRequests.push(task);
    pumpRuntimeRequests();
  });
}

function pumpRuntimeRequests() {
  if (runtimePumpScheduled || !runtimeRequests.length) return;
  runtimePumpScheduled = true;
  // A task boundary lets rendering/input run between completed source bodies.
  setTimeout(() => {
    runtimePumpScheduled = false;
    const limit = typeof matchMedia === 'function' && matchMedia('(max-width: 720px)').matches ? 2 : 3;
    const now = performance.now();
    const effectivePriority = (task: RuntimeRequest) => Math.max(0, task.priority - Math.floor((now - task.queuedAt) / 4000));
    runtimeRequests.sort((a, b) => effectivePriority(a) - effectivePriority(b) || a.queuedAt - b.queuedAt);
    while (runtimeRunning < limit && runtimeRequests.length) {
      const task = runtimeRequests.shift()!;
      if (task.signal?.aborted) task.abort(); else task.start();
    }
  }, 0);
}

function apiGetWithTimeout<T>(path: string, timeoutMs = 12000, externalSignal?: AbortSignal, cache?: RequestCache): Promise<T> {
  const run = () => apiGetAdmitted<T>(path, timeoutMs, externalSignal, cache);
  // Bulk dashboard GETs used to bypass the same limit as the map sources.
  // Interactive details/bootstrap still start immediately; catalogue/summary
  // bodies share admission with runtime to avoid a first-screen download burst.
  const bulkDashboard = /^\/(?:market-groups|markets)(?:\?|$)|^\/(?:content|trades\/recent|oracle\/recent|system\/health)(?:\?|$)/.test(path);
  if (!path.startsWith('/runtime/') && !bulkDashboard) return run();
  // Visible quote/signal consumers share the first tier with primary hazards
  // and interactive detail. Bulk map layers cannot starve their refreshes.
  const priority = /^\/runtime\/(?:(signals|trades|markets)\/|crypto\/funding-watch|lob\/books|weather\/temperature-monitor)|natural-hazards\/map.*source=(usgs|nhc|nws)\b|detail|aviation.*viewport|map-query/.test(path) ? 0
    : /natural-hazards|global-transport|transport\/global-shipping|geo-sanctions/.test(path) ? 1 : 2;
  return withRuntimeRequestBudget(run, externalSignal, priority);
}

async function apiGetAdmitted<T>(path: string, timeoutMs = 12000, externalSignal?: AbortSignal, cache?: RequestCache): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  const abortFromExternal = () => controller.abort();
  externalSignal?.addEventListener('abort', abortFromExternal, { once: true });
  try {
    if (externalSignal?.aborted) controller.abort();
    const response = await fetch(`${API_BASE}${path}`, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
      ...(cache ? { cache } : {}),
    });
    if (!response.ok) throw new ApiHttpError(response.status, path, response.headers.get('Retry-After'),
      response.status === 503 && response.headers.get('X-Panel-Verification') === 'pending');
    // Keep timeout and cancellation ownership until the body is consumed.
    return await response.json() as T;
  } catch (error) {
    if (externalSignal?.aborted) throw error;
    if (isAbortLikeError(error)) throw new ApiTimeoutError(path, timeoutMs);
    throw error;
  } finally {
    window.clearTimeout(timer);
    externalSignal?.removeEventListener('abort', abortFromExternal);
  }
}

async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return apiGetWithTimeout<T>(path, 12000, signal);
}

export function fetchBootstrap(signal?: AbortSignal) {
  return apiGet<BootstrapPayload>('/bootstrap', signal);
}

export function fetchMarketSearch(query: string, limit = 12, signal?: AbortSignal) {
  const params = new URLSearchParams({
    q: query.trim(),
    limit: String(limit),
  });
  return apiGetWithTimeout<{ items: MarketListItem[] }>(`/search?${params.toString()}`, 5000, signal);
}

function fetchMarketsPage(page = 1, query = '', pageSize = 160, signal?: AbortSignal) {
  const params = new URLSearchParams({
    page: String(page),
    pageSize: String(pageSize),
    status: 'active',
  });
  if (query.trim()) params.set('q', query.trim());
  return apiGetWithTimeout<MarketsPayload>(`/markets?${params.toString()}`, 3500, signal);
}

export async function fetchAllActiveMarkets(query = '', pageSize = 160, maxPages = 8, signal?: AbortSignal,
  onFirstPage?: (payload: MarketsPayload) => void) {
  const items: MarketsPayload['items'] = [];
  let page = 1;
  let total = 0;
  let totalPages = 1;
  let hasMore = false;

  do {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const payload = await fetchMarketsPage(page, query, pageSize, signal);
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    if (page === 1) onFirstPage?.(payload);
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

export function fetchMarketGroups(query = '', pageSize = 80, sort: MarketGroupSort = 'active', signal?: AbortSignal) {
  const params = new URLSearchParams({
    page: '1',
    pageSize: String(pageSize),
    sort,
  });
  if (query.trim()) params.set('q', query.trim());
  return apiGetWithTimeout<MarketGroupsPayload>(`/market-groups?${params.toString()}`, 9000, signal);
}

export function fetchMarketGroupDetail(eventId: string, timeoutMs = 3500, signal?: AbortSignal) {
  return apiGetWithTimeout<MarketGroupDetail>(`/market-groups/${encodeURIComponent(eventId)}/detail`, timeoutMs, signal);
}

export function fetchMarketGroupChart(
  eventId: string,
  range: '1h' | '6h' | '1d' | '1w' | '1m' | 'all' = '1d',
  timeoutMs = 4000,
  signal?: AbortSignal,
) {
  return apiGetWithTimeout<MarketGroupChartPayload>(
    `/market-groups/${encodeURIComponent(eventId)}/chart?range=${encodeURIComponent(range)}`,
    timeoutMs,
    signal,
  );
}

export async function fetchSystemHealth(signal?: AbortSignal): Promise<SystemHealth> {
  // The public dashboard never requests the operations-only admin endpoint.
  const health = await apiGet<{ status: string; database: boolean; redis: boolean }>('/health', signal);
  return { apiStatus: health.status, redis: health.redis };
}

export function fetchMarketDataQuality(signal?: AbortSignal) {
  return apiGetWithTimeout<MarketDataQualityPayload>('/data-quality/markets', 45_000, signal);
}

export function fetchRecentTrades(limit = 24, signal?: AbortSignal) {
  return apiGet<TradeRow[]>(`/trades/recent?limit=${limit}`, signal);
}

export function fetchRecentOracle(limit = 24, signal?: AbortSignal) {
  return apiGet<OraclePayload['timeline']>(`/oracle/recent?limit=${limit}`, signal);
}

export function fetchLatestContent(limit = 8, signal?: AbortSignal, days = 7) {
  return apiGet<ContentPayload>(`/content/latest?limit=${limit}&days=${days}`, signal);
}

export function fetchRuntimeCommodities(signal?: AbortSignal) {
  return apiGetWithTimeout<RuntimeMarketGroup>('/runtime/markets/commodities', 12000, signal, 'no-store');
}

export function fetchRuntimeCrypto(signal?: AbortSignal) {
  return apiGet<RuntimeMarketGroup>('/runtime/markets/crypto', signal);
}

export function fetchRuntimeCryptoFundingWatch(limit = 80, signal?: AbortSignal) {
  return apiGetWithTimeout<unknown>(`/runtime/crypto/funding-watch?limit=${limit}`, 8000, signal, 'no-store');
}

export function fetchRuntimeDefiTokenWatch(limit = 10, signal?: AbortSignal) {
  return apiGet<RuntimeDefiTokenWatchPayload>(`/runtime/finance/defi-token-watch?limit=${limit}`, signal);
}

export function fetchRuntimeFinanceWatchPanel(panelId: string, limit = 10, signal?: AbortSignal) {
  return apiGet<RuntimeFinanceWatchPayload>(`/runtime/finance/${panelId}?limit=${limit}`, signal);
}

export function fetchRuntimeTechPanel(panelId: string, limit = 10, signal?: AbortSignal) {
  return apiGet<RuntimeTechPanelPayload>(`/runtime/tech/${panelId}?limit=${limit}`, signal);
}

export function fetchRuntimeCommodityEquityTransmission(limit = 8, signal?: AbortSignal) {
  return apiGet<RuntimeCommodityTransmissionPayload>(`/runtime/finance/commodity-equity-transmission?limit=${limit}`, signal);
}

export function fetchRuntimeF1(limit = 10, signal?: AbortSignal) {
  return apiGet<RuntimeF1Payload>(`/runtime/sports/f1?limit=${limit}`, signal);
}

export function fetchRuntimeJin10(limit = 24, signal?: AbortSignal) {
  return apiGet<RuntimeJin10Payload>(`/runtime/macro/jin10?limit=${limit}`, signal);
}

export function fetchRuntimeNba(limit = 10, signal?: AbortSignal) {
  return apiGet<RuntimeNbaPayload>(`/runtime/sports/nba?limit=${limit}`, signal);
}

export function fetchRuntimeNbaIntel(limit = 12, signal?: AbortSignal) {
  return apiGet<RuntimeNbaIntelPayload>(`/runtime/sports/nba-intel?limit=${limit}`, signal);
}

export function fetchRuntimeNbaMatchupPredictor(limit = 8, signal?: AbortSignal) {
  return apiGet<RuntimeNbaMatchupPredictorPayload>(`/runtime/sports/nba-matchup-predictor?limit=${limit}`, signal);
}

export function fetchRuntimeGridEsports(limit = 10, signal?: AbortSignal) {
  return apiGet<RuntimeGridEsportsPayload>(`/runtime/esports/grid-intel?limit=${limit}`, signal);
}

export function fetchRuntimeSportsOdds(limit = 8, signal?: AbortSignal) {
  return apiGet<RuntimeSportsOddsPayload>(`/runtime/sports/odds-monitor?limit=${limit}`, signal);
}

export function fetchRuntimeInflationNowcast(signal?: AbortSignal) {
  return apiGet<RuntimeInflationNowcastPayload>('/runtime/macro/inflation-nowcast', signal);
}

export function fetchRuntimePolymarketMacroMap(limit = 12, signal?: AbortSignal) {
  return apiGet<RuntimePolymarketMacroMapPayload>(`/runtime/macro/polymarket-map?limit=${limit}`, signal);
}

export function fetchRuntimeCpiReleaseCalendar(limit = 8, signal?: AbortSignal) {
  return apiGet<RuntimeCpiReleaseCalendarPayload>(`/runtime/macro/cpi-release-calendar?limit=${limit}`, signal);
}

export function fetchRuntimeEnergyGasolineShock(limit = 6, signal?: AbortSignal) {
  return apiGet<RuntimeEnergyGasolineShockPayload>(`/runtime/macro/energy-gasoline-shock?limit=${limit}`, signal);
}

export function fetchRuntimeGlobalTemperatureMonitor(limit = 60, signal?: AbortSignal) {
  return apiGet<RuntimeGlobalWeatherMapPayload>(`/runtime/weather/temperature-monitor?limit=${limit}`, signal);
}

export function fetchRuntimeWeatherNews(limit = 24, signal?: AbortSignal) {
  return apiGet<RuntimeWeatherNewsPayload>(`/runtime/weather/news?limit=${limit}`, signal);
}

export function fetchRuntimeGlobalTransportShipping(limit = 14, signal?: AbortSignal) {
  return apiGet<RuntimeGlobalTransportShippingPayload>(`/runtime/transport/global-shipping?limit=${limit}`, signal);
}

export function fetchAviationViewport(
  bbox: [number, number, number, number],
  zoom: number,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ bbox: bbox.join(','), zoom: String(zoom), limit: '180' });
  return apiGetWithTimeout<import('@/types').AviationViewportPayload>(
    `/runtime/transport/aviation-viewport?${params.toString()}`,
    // The server has an 8.5s acquisition deadline. Allow bounded network/body
    // transfer time as well; the same signal still cancels obsolete viewports.
    15_000,
    signal,
  );
}

export function fetchRuntimeBreakingEventRadar(limit = 12, signal?: AbortSignal) {
  return apiGet<RuntimeBreakingEventRadarPayload>(`/runtime/evidence/breaking-event-radar?limit=${limit}`, signal);
}

export function fetchRuntimeFoodRetailBasket(limit = 8, signal?: AbortSignal) {
  return apiGet<RuntimeFoodRetailBasketPayload>(`/runtime/macro/food-retail-basket?limit=${limit}`, signal);
}

export function fetchRuntimeSupplyTariffImportWatch(limit = 8, signal?: AbortSignal) {
  return apiGet<RuntimeMacroDriverPayload>(`/runtime/macro/supply-tariff-import-watch?limit=${limit}`, signal);
}

export function fetchRuntimeShelterRentOerPressure(limit = 8, signal?: AbortSignal) {
  return apiGet<RuntimeMacroDriverPayload>(`/runtime/macro/shelter-rent-oer-pressure?limit=${limit}`, signal);
}

export function fetchRuntimeLaborWageServicesPressure(limit = 8, signal?: AbortSignal) {
  return apiGet<RuntimeMacroDriverPayload>(`/runtime/macro/labor-wage-services-pressure?limit=${limit}`, signal);
}

export function fetchRuntimeGrowthDemandRecessionTracker(limit = 8, signal?: AbortSignal) {
  return apiGet<RuntimeMacroDriverPayload>(`/runtime/macro/growth-demand-recession-tracker?limit=${limit}`, signal);
}

export function fetchRuntimeFedRatesPolymarketGap(limit = 8, signal?: AbortSignal) {
  return apiGet<RuntimeMacroDriverPayload>(`/runtime/macro/fed-rates-polymarket-gap?limit=${limit}`, signal);
}

export function fetchRuntimeCpiReleaseCommandCenter(limit = 36, signal?: AbortSignal) {
  return apiGet<RuntimeCpiReleaseCommandPayload>(`/runtime/macro/cpi-release-command-center?limit=${limit}`, signal);
}

export function fetchRuntimeCpiComponentsPressureRegistry(limit = 48, signal?: AbortSignal) {
  return apiGet<RuntimeMacroRegistryPayload>(`/runtime/macro/cpi-components-pressure-registry?limit=${limit}`, signal);
}

export function fetchRuntimeGoodsTariffSupplyWatch(limit = 36, signal?: AbortSignal) {
  return apiGet<RuntimeMacroRegistryPayload>(`/runtime/macro/goods-tariff-supply-watch?limit=${limit}`, signal);
}

export function fetchRuntimeLaborServicesInflationMonitor(limit = 36, signal?: AbortSignal) {
  return apiGet<RuntimeMacroRegistryPayload>(`/runtime/macro/labor-services-inflation-monitor?limit=${limit}`, signal);
}

export function fetchRuntimeFedReactionGrowthRiskBoard(limit = 36, signal?: AbortSignal) {
  return apiGet<RuntimeMacroRegistryPayload>(`/runtime/macro/fed-reaction-growth-risk-board?limit=${limit}`, signal);
}

export function fetchRuntimeGeoSanctionsShock(limit = 2000, signal?: AbortSignal) {
  return apiGet<RuntimeGeoSanctionsShockPayload>(`/runtime/world/geo-sanctions-shock?limit=${limit}`, signal);
}

export function fetchNaturalHazardMapSource(
  source: string,
  zoom: number,
  bbox?: [number, number, number, number],
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ source, limit: '1200', zoom: String(zoom) });
  if (bbox) params.set('bbox', bbox.join(','));
  return apiGetWithTimeout<HazardMapResponse>(
    `/runtime/world/natural-hazards/map?${params.toString()}`,
    10_000,
    signal,
    // The source's absolute staleAfter can precede an intermediary HTTP cache
    // deadline. Revalidate scheduled refreshes; retain ETag/cache reuse.
    'no-cache',
  );
}

export function fetchNaturalHazardDetail(eventId: string, signal?: AbortSignal) {
  return apiGetWithTimeout<HazardDetailResponse>(
    `/runtime/world/natural-hazards/events/${encodeURIComponent(eventId)}`,
    10_000,
    signal,
  );
}

export function fetchNaturalHazardRelatedMarkets(eventId: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ eventId, limit: '8' });
  return apiGetWithTimeout<HazardMarketLinksResponse>(
    `/runtime/world/natural-hazards/related-markets?${params.toString()}`,
    6000,
    signal,
  );
}

export function fetchRuntimeAlpha(limit = 8, signal?: AbortSignal) {
  return apiGet<RuntimeSignalPayload>(`/runtime/signals/alpha?limit=${limit}`, signal);
}

export function fetchRuntimePolybeats(limit = 8, signal?: AbortSignal) {
  return apiGet<RuntimePolybeatsPayload>(`/runtime/panels/polybeats-feed?limit=${limit}`, signal);
}

export function fetchRuntimeMarketTvWire(limit = 24, category?: string | null, signal?: AbortSignal) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (category && category !== 'all') params.set('category', category);
  return apiGet<RuntimeMarketTvWirePayload>(`/runtime/content/market-tv-wire?${params.toString()}`, signal);
}

export function buildRuntimeHlsProxyUrl(hlsUrl: string) {
  const params = new URLSearchParams({ url: hlsUrl });
  return `${API_BASE}/runtime/content/hls-proxy?${params.toString()}`;
}

export function buildRuntimeYoutubeEmbedUrl(videoId: string, options?: { autoplay?: boolean; mute?: boolean; quality?: string }) {
  const params = new URLSearchParams({
    videoId,
    autoplay: options?.autoplay === false ? '0' : '1',
    mute: options?.mute === false ? '0' : '1',
    parentOrigin: window.location.origin,
  });
  if (options?.quality) params.set('vq', options.quality);
  return `${API_BASE}/runtime/content/youtube-embed?${params.toString()}`;
}

export function fetchRuntimeMarketYoutubeChannels(limit = 12, category?: string | null, signal?: AbortSignal) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (category && category !== 'all') params.set('category', category);
  return apiGet<RuntimeMarketYoutubeChannelsPayload>(`/runtime/content/market-youtube-channels?${params.toString()}`, signal);
}

export function fetchRuntimeNewMarketSignals(limit = 12, signal?: AbortSignal) {
  return apiGet<RuntimeNewMarketSignalsPayload>(`/runtime/markets/new-signals?limit=${limit}`, signal);
}

export function fetchRuntimeWhales(limit = 14, signal?: AbortSignal) {
  return apiGetWithTimeout<RuntimeSignalPayload>(`/runtime/trades/whales?limit=${limit}`, 12000, signal, 'no-store');
}

export function fetchRuntimeSuspicious(limit = 12, signal?: AbortSignal) {
  return apiGetWithTimeout<RuntimeSignalPayload>(`/runtime/trades/suspicious?limit=${limit}`, 12000, signal, 'no-store');
}

export type RuntimePanelsPayload = {
  generatedAt?: string;
  status?: string;
  panels?: Record<string, unknown>;
  errors?: Record<string, string>;
  requestId?: string;
  metadata?: Record<string, RuntimePanelMetadata>;
};

export type ApiEnvelopeError = {
  code: string;
  message: string;
  panelId?: string;
  retryable: boolean;
};

export type ApiEnvelope<T> = {
  apiVersion: 'v1';
  requestId: string;
  generatedAt: string;
  status: 'ok' | 'partial' | 'error';
  data: T;
  meta: Record<string, unknown>;
  errors: ApiEnvelopeError[];
};

export type RuntimePanelMetadata = {
  panelId: string;
  route: string;
  status: string;
  cache: {
    mode: string;
    ageSeconds: number | null;
  };
  freshness: {
    state: string;
    observedAt: string | null;
    ageSeconds: number | null;
  };
  limits: {
    default: number | null;
    minimum: number | null;
    maximum: number | null;
  };
};

type RuntimePanelsEnvelopeData = {
  panels: Record<string, unknown>;
};

type RuntimePanelsEnvelopeMeta = {
  requestedPanelIds?: string[];
  returnedPanelIds?: string[];
  panels?: Record<string, RuntimePanelMetadata>;
};

export async function fetchRuntimePanels(panelIds: string[], limits: Record<string, number> = {}, signal?: AbortSignal) {
  const ids = [...new Set(panelIds.map((panelId) => panelId.trim()).filter(Boolean))];
  const params = new URLSearchParams({ ids: ids.join(',') });
  ids.forEach((panelId) => {
    const limit = limits[panelId];
    if (typeof limit === 'number' && Number.isFinite(limit)) params.set(`limit.${panelId}`, String(limit));
  });
  const envelope = await apiGet<ApiEnvelope<RuntimePanelsEnvelopeData>>(`/v1/runtime/panels?${params.toString()}`, signal);
  const meta = envelope.meta as RuntimePanelsEnvelopeMeta;
  return {
    generatedAt: envelope.generatedAt,
    status: envelope.status,
    panels: envelope.data?.panels || {},
    errors: Object.fromEntries(
      (envelope.errors || [])
        .filter((error) => error.panelId)
        .map((error) => [error.panelId as string, error.code || error.message]),
    ),
    requestId: envelope.requestId,
    metadata: meta.panels || {},
  } satisfies RuntimePanelsPayload;
}

type MarketDetailBundlePayload = {
  market?: MarketSummary | null;
  identity?: WorkspaceIdentity | null;
  diagnostics?: WorkspaceDiagnostics | null;
  health?: MarketWorkspaceHealth | null;
  evidence?: MarketWorkspaceEvidence | null;
  group?: MarketGroupDetail | null;
  selectedOutcome?: MarketGroupOutcome | null;
  price?: PriceSummary | null;
  chart?: ChartPayload | null;
  priceSeries?: ChartPayload['points'];
  trades?: TradeRow[];
  oracle?: OraclePayload | null;
  oracleEvents?: OraclePayload['timeline'];
  content?: ContentPayload | null;
  lob?: LobPayload | null;
  servingSource?: string | null;
  servingUpdatedAt?: string | null;
  generatedAt?: string | null;
  focusStatus?: 'ready' | 'warming' | string | null;
  cacheLayers?: Record<string, unknown> | null;
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
  const oracleSource = payload.oracle || null;
  const oracleSummary = oracleSource?.summary || null;
  const identity = payload.identity || null;
  const oracle = oracleSource || payload.oracleEvents || identity
    ? {
        ...(oracleSource || {}),
        marketId: Number(oracleSource?.marketId ?? identity?.marketId ?? marketId),
        localMarketId: Number(oracleSource?.localMarketId ?? identity?.localMarketId ?? marketId),
        gammaMarketId: oracleSource?.gammaMarketId ?? identity?.gammaMarketId ?? payload.market?.gammaMarketId ?? null,
        questionId: oracleSource?.questionId ?? identity?.questionId ?? payload.market?.questionId ?? null,
        conditionId: oracleSource?.conditionId ?? identity?.conditionId ?? payload.market?.conditionId ?? null,
        oracle: oracleSource?.oracle ?? identity?.oracle ?? payload.market?.oracle ?? null,
        currentStatus: oracleSource?.currentStatus ?? payload.market?.status ?? null,
        completionStatus: oracleSource?.completionStatus ?? oracleSummary?.completionStatus ?? null,
        isTradingClosed: oracleSource?.isTradingClosed ?? oracleSummary?.isTradingClosed ?? false,
        isResolved: oracleSource?.isResolved ?? oracleSummary?.isResolved ?? false,
        isFinal: oracleSource?.isFinal ?? oracleSummary?.isFinal ?? false,
        settlementOutcome: oracleSource?.settlementOutcome ?? oracleSummary?.settlementOutcome ?? null,
        settlementSource: oracleSource?.settlementSource ?? oracleSummary?.settlementSource ?? null,
        summary: oracleSummary,
        timeline: oracleSource?.timeline || payload.oracleEvents || [],
      }
    : null;
  return {
    market: payload.market || null,
    identity,
    diagnostics: payload.diagnostics || null,
    health: payload.health || null,
    evidence: payload.evidence || null,
    group: payload.group || null,
    selectedOutcome: payload.selectedOutcome || null,
    price: payload.price || null,
    chart,
    trades: payload.trades || [],
    oracle,
    content: payload.content || null,
    lob: payload.lob || null,
    servingSource: payload.servingSource || null,
    servingUpdatedAt: payload.servingUpdatedAt || null,
    generatedAt: payload.generatedAt || null,
    focusStatus: payload.focusStatus || null,
    cacheLayers: payload.cacheLayers || null,
  };
}

async function fetchMarketDetailBundle(marketId: number, timeoutMs = 6500, signal?: AbortSignal): Promise<WorkspaceBundle> {
  const payload = await apiGetWithTimeout<MarketDetailBundlePayload>(`/markets/${marketId}/detail`, timeoutMs, signal);
  return normalizeMarketBundlePayload(payload, marketId);
}

async function fetchMarketWorkspaceBundle(marketId: number, timeoutMs = 6500, signal?: AbortSignal): Promise<WorkspaceBundle> {
  const payload = await apiGetWithTimeout<MarketDetailBundlePayload>(`/markets/${marketId}/workspace`, timeoutMs, signal);
  return normalizeMarketBundlePayload(payload, marketId);
}

export async function fetchMarketFocusTile(marketId: number, timeoutMs = 2200, signal?: AbortSignal): Promise<WorkspaceBundle> {
  const payload = await apiGetWithTimeout<MarketDetailBundlePayload>(`/markets/${marketId}/focus-tile`, timeoutMs, signal);
  return normalizeMarketBundlePayload(payload, marketId);
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
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ range, interval });
  return apiGetWithTimeout<ChartPayload>(`/markets/${marketId}/chart?${params.toString()}`, timeoutMs, signal);
}

export function fetchMarketContent(marketId: number, limit = 20, timeoutMs = 5000, signal?: AbortSignal, days = 7) {
  return apiGetWithTimeout<ContentPayload>(`/content/market/${marketId}?limit=${limit}&days=${days}`, timeoutMs, signal)
    .then((payload) => {
      if (payload.marketId !== marketId || (payload.scope && payload.scope !== 'market')) {
        throw new Error('Content response scope or market identity mismatch');
      }
      return payload;
    });
}

function fetchMarketLob(marketId: number, timeoutMs = 4000, signal?: AbortSignal) {
  return apiGetWithTimeout<LobPayload>(`/runtime/lob/${marketId}`, timeoutMs, signal);
}

export function fetchWeatherBooks(tokens: string[], signal?: AbortSignal) {
  const params = new URLSearchParams({ tokens: tokens.join(','), _ts: String(Date.now()) });
  return apiGetWithTimeout<{ books: Record<string, LobPayload> }>(`/runtime/lob/books?${params}`, 10_000, signal, 'no-store');
}

export function fetchMarketLobByToken(
  tokenId: string,
  title = '',
  noTokenId = '',
  timeoutMs = 4000,
  signal?: AbortSignal,
  marketId?: number | null,
) {
  const params = new URLSearchParams();
  if (title.trim()) params.set('title', title.trim());
  if (noTokenId.trim()) params.set('noTokenId', noTokenId.trim());
  if (marketId != null && Number.isFinite(Number(marketId))) params.set('marketId', String(marketId));
  params.set('_ts', String(Date.now()));
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return apiGetWithTimeout<LobPayload>(`/runtime/lob/token/${encodeURIComponent(tokenId)}${suffix}`, timeoutMs, signal);
}

function preferLoadedBundle(primary: WorkspaceBundle, secondary: WorkspaceBundle): WorkspaceBundle {
  const primaryOracle = primary.oracle;
  const secondaryOracle = secondary.oracle;
  return {
    market: primary.market || secondary.market,
    identity: primary.identity || secondary.identity,
    diagnostics: primary.diagnostics || secondary.diagnostics,
    health: primary.health || secondary.health,
    evidence: primary.evidence || secondary.evidence,
    group: primary.group || secondary.group,
    selectedOutcome: primary.selectedOutcome || secondary.selectedOutcome,
    price: primary.price || secondary.price,
    chart: primary.chart?.points?.length ? primary.chart : secondary.chart,
    trades: primary.trades?.length ? primary.trades : secondary.trades,
    oracle: primaryOracle ? primaryOracle : secondaryOracle,
    content: secondary.content ?? primary.content,
    lob: primary.lob || secondary.lob,
    servingSource: primary.servingSource || secondary.servingSource,
    servingUpdatedAt: primary.servingUpdatedAt || secondary.servingUpdatedAt,
    generatedAt: primary.generatedAt || secondary.generatedAt,
    focusStatus: primary.focusStatus || secondary.focusStatus,
    cacheLayers: primary.cacheLayers || secondary.cacheLayers,
  };
}

const workspaceBundleInflight = new Map<string, Promise<WorkspaceBundle>>();

function emptyWorkspaceBundle(): WorkspaceBundle {
  return {
    market: null,
    identity: null,
    diagnostics: null,
    health: null,
    evidence: null,
    group: null,
    selectedOutcome: null,
    price: null,
    chart: null,
    trades: [],
    oracle: null,
    content: null,
    lob: null,
    servingSource: null,
    servingUpdatedAt: null,
    generatedAt: null,
    focusStatus: null,
    cacheLayers: null,
  };
}

export function fetchMarketWideAiSnapshot(lens: MarketWideAiInsightLens, timeoutMs = 8000, signal?: AbortSignal) {
  return apiGetWithTimeout<MarketWideAiInsightResponse>(
    `/runtime/agent/market-wide-insights/${encodeURIComponent(lens)}`,
    timeoutMs,
    signal,
  );
}

export async function fetchWorkspaceBundle(
  marketId: number,
  options: { includeContent?: boolean; contentDays?: number; includeLob?: boolean; signal?: AbortSignal } = {},
): Promise<WorkspaceBundle> {
  const includeContent = Boolean(options.includeContent);
  const includeLob = Boolean(options.includeLob);
  const contentDays = options.contentDays === 30 ? 30 : 7;
  const inflightKey = `${marketId}:${includeContent ? `content:${contentDays}` : 'base'}:${includeLob ? 'lob' : 'no-lob'}`;
  const inflight = options.signal ? null : workspaceBundleInflight.get(inflightKey);
  if (inflight) return inflight;

  const request = (async () => {
    const contentPromise = includeContent
      ? fetchMarketContent(marketId, 20, 8000, options.signal, contentDays)
      : Promise.resolve(null);
    const lobPromise = includeLob ? fetchMarketLob(marketId, 1800, options.signal) : Promise.resolve(null);
    const detailPromise = fetchMarketWorkspaceBundle(marketId, 22000, options.signal)
      .catch((error) => {
        if (options.signal?.aborted) throw error;
        return fetchMarketDetailBundle(marketId, 12000, options.signal);
      });
    const [detailResult, contentResult, lobResult] = await Promise.allSettled([detailPromise, contentPromise, lobPromise]);
    const detailBundle = detailResult.status === 'fulfilled' ? detailResult.value : emptyWorkspaceBundle();
    const secondary: WorkspaceBundle = {
      market: null,
      identity: null,
      diagnostics: null,
      health: null,
      evidence: null,
      group: null,
      selectedOutcome: null,
      price: null,
      chart: null,
      trades: [],
      oracle: null,
      content: contentResult.status === 'fulfilled' ? contentResult.value : {
        scope: 'market', marketId, items: [], count: 0, status: 'unavailable',
        empty_reason: 'content_request_failed', sourceMode: 'database:free-public',
      },
      lob: includeLob && lobResult.status === 'fulfilled' ? lobResult.value : null,
      servingSource: null,
      servingUpdatedAt: null,
      generatedAt: null,
      focusStatus: null,
      cacheLayers: null,
    };
    return preferLoadedBundle(detailBundle, secondary);
  })();

  if (!options.signal) {
    workspaceBundleInflight.set(inflightKey, request);
    void request.finally(() => workspaceBundleInflight.delete(inflightKey));
  }
  return request;
}

export type MapPlace = { id: string; name: string; country: string; countryCode?: string; region: string; lat: number; lon: number };
export type MapForecast = {
  status: string; current: { time?: string; temperature_2m?: number; relative_humidity_2m?: number; wind_speed_10m?: number };
  hourly: { time?: string[]; temperature_2m?: Array<number | null> };
  daily: { time?: string[]; temperature_2m_max?: Array<number | null>; temperature_2m_min?: Array<number | null> };
  dailySampled?: boolean; units: Record<string, string>; sourceUrl: string; source: string; fetchedAt: string; limitations: string[];
};
export function searchMapPlaces(query: string, language: string, signal: AbortSignal) {
  return apiGetWithTimeout<{status: string; places: MapPlace[]}>(`/runtime/weather/map-query?${new URLSearchParams({q: query, language})}`, 16000, signal);
}
export function fetchMapForecast(lat: number, lon: number, signal: AbortSignal) {
  return apiGetWithTimeout<MapForecast>(`/runtime/weather/map-query?${new URLSearchParams({lat: String(lat), lon: String(lon)})}`, 16000, signal);
}

export function fetchTransportMapSource(source: 'faa' | 'ais', signal: AbortSignal) {
  return apiGetWithTimeout<{status: string; events: unknown[]; updatedAt?: string; message?: string}>(`/runtime/transport/map?source=${source}`, 18000, signal);
}
export function searchMapAirports(query: string, signal: AbortSignal) {
  return apiGetWithTimeout<{places: MapPlace[]}>(`/runtime/transport/map?${new URLSearchParams({source: 'airports', q: query})}`, 20000, signal);
}
export function fetchMapInfrastructure(bbox: number[], signal: AbortSignal) {
  return apiGetWithTimeout<{status: string; events: unknown[]; updatedAt?: string; message?: string}>(`/runtime/world/infrastructure?${new URLSearchParams({bbox: bbox.join(',')})}`, 15000, signal);
}

export function fetchMapSignalSource(source: string, signal?: AbortSignal) {
  return apiGetWithTimeout<{status: string; events: unknown[]; message?: string; updatedAt?: string}>(`/runtime/world/signals?source=${encodeURIComponent(source)}`, 18000, signal);
}
