import { type ComponentChildren } from 'preact';
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { FocusedMarketStrip } from '@/components/FocusedMarketStrip';
import { PanelLoading } from '@/components/Panel';
import WeatherDeckMap from '@/components/WeatherDeckMap';
import { WeatherMapCityInspector } from '@/components/WeatherMapCityInspector';
import { WorldGlobe, type WorldGlobeStatusMetrics } from '@/components/WorldGlobe';
import { DEFAULT_PANEL_IDS, PANEL_LIBRARY, PANEL_REGISTRY, RUNTIME_PANEL_MODULES } from '@/panels/registry';
import { fetchPanelRuntimeData, getRefreshablePanels, mergeRuntimeData } from '@/panels/runtime-store';
import { formatCompact, formatCurrencyCompact, formatDate, formatPercent, formatRelative } from '@/panels/shared/formatters';
import { QuantWorkspace } from '@/workspaces/quant/QuantWorkspace';
import { WorldCupWorkspace } from '@/workspaces/worldcup/WorldCupWorkspace';
import {
  fetchAllActiveMarkets,
  fetchBootstrap,
  fetchLatestContent,
  fetchMarketContent,
  fetchMarketChart,
  fetchMarketGroupChart,
  fetchMarketGroupDetail,
  fetchMarketGroups,
  fetchMarketLob,
  fetchMarketPrice,
  fetchMarketSearch,
  fetchMarketTrades,
  fetchRecentOracle,
  fetchRecentTrades,
  fetchRuntimeGlobalWeatherMap,
  fetchSystemHealth,
  fetchWorkspaceBundle,
} from '@/services/api';
import { buildWorldClockRows, CORE_WORLD_CLOCKS, normalizeTimezone, type WorldClockLocation } from '@/utils/worldClock';
import type {
  BootstrapPayload,
  ContentItem,
  MarketGroupChartPayload,
  MarketGroupChartRange,
  MarketGroupDetail,
  MarketListItem,
  MarketGroupItem,
  MarketGroupsPayload,
  MarketGroupSort,
  MarketsPayload,
  MarketSummary,
  OracleEvent,
  PanelRenderContext,
  RuntimeF1Payload,
  RuntimeGeoSanctionsShockItem,
  RuntimeGeoSanctionsShockPayload,
  RuntimeGlobalWeatherMapPayload,
  RuntimeInflationNowcastPayload,
  RuntimeJin10Payload,
  RuntimeMarketGroup,
  RuntimeNbaIntelPayload,
  RuntimeNbaMatchupPredictorPayload,
  RuntimeNbaPayload,
  RuntimeSignalPayload,
  SystemHealth,
  TradeRow,
  WorkspaceBundle,
} from '@/types';
import type { PanelRuntimeData } from '@/panels/types';

type LayerToggle = {
  id: string;
  label: string;
  icon: string;
  enabled: boolean;
  hint?: string;
};

type RegionKey = 'global' | 'america' | 'mena' | 'eu' | 'asia' | 'latam' | 'africa' | 'oceania';
type MapViewMode = '3d' | '2d' | 'heatmap' | 'density';
type CommandPaletteTab = 'markets' | 'panels' | 'commands';
const PANEL_STORAGE_KEY = 'polydata:workspace-panels:v4';
const PANEL_LAYOUT_STORAGE_KEY = 'polydata:workspace-panel-layout:v4';
const MARKET_GROUP_SORT_STORAGE_KEY = 'wm:marketGroupSort:v1';
const VIEW_STORAGE_KEY = 'polydata:map-view:v2';
const WORKSPACE_MODE_STORAGE_KEY = 'polydata:workspace-mode:v1';
const REGION_STORAGE_KEY = 'polydata:region:v1';
const LIBRARY_STORAGE_KEY = 'polydata:panel-library-open:v1';
const ZOOM_STORAGE_KEY = 'polydata:map-zoom:v2';
const GEO_SHOCK_STORAGE_KEY = 'polydata:seed:world:geo-sanctions-shock:v1';
const GEO_SHOCK_LOCAL_STALE_MS = 24 * 60 * 60 * 1000;
const APP_VERSION = 'v0.2.1';
const FAST_MARKETS_PAGE_SIZE = 80;
const SEARCH_MARKETS_PAGE_SIZE = 120;
const SITE_NAV_LINKS = [
  { label: 'Blog', href: '/blog/' },
  { label: 'Docs', href: '/docs/documentation/' },
  { label: 'Paper', href: 'https://arxiv.org/pdf/2604.20421', external: true },
  { label: 'GitHub', href: 'https://github.com/virusLuke3/polymonitor', external: true },
  { label: 'Quant', href: '/quant' },
];
const INTERVAL_RUNTIME_PANELS = RUNTIME_PANEL_MODULES.filter(
  (panel) => typeof panel.fetchData === 'function' && Number(panel.refresh?.intervalMs || 0) > 0,
);
const FAST_RUNTIME_PANELS = getRefreshablePanels(RUNTIME_PANEL_MODULES, 'fast').filter((panel) => !panel.refresh?.intervalMs);
const SLOW_RUNTIME_PANELS = getRefreshablePanels(RUNTIME_PANEL_MODULES, 'slow').filter((panel) => !panel.refresh?.intervalMs);

const INITIAL_LAYERS: LayerToggle[] = [
  { id: 'markets', label: 'Polymarket Markets', icon: '◎', enabled: true, hint: 'ACTIVE' },
  { id: 'oracle', label: 'Oracle Events', icon: '◌', enabled: true, hint: 'LIVE' },
  { id: 'trade', label: 'OrderFilled Tape', icon: '↗', enabled: true, hint: 'CHAIN' },
  { id: 'lob', label: 'Runtime LOB', icon: '▦', enabled: true, hint: 'BOOK' },
  { id: 'intel', label: 'Linked Intel', icon: '✦', enabled: true, hint: 'NEWS' },
  { id: 'ucdp', label: 'UCDP Conflicts', icon: '△', enabled: true, hint: 'CONFLICT' },
];

const REGION_OPTIONS: Array<{ value: RegionKey; label: string }> = [
  { value: 'global', label: 'Global' },
  { value: 'america', label: 'Americas' },
  { value: 'mena', label: 'MENA' },
  { value: 'eu', label: 'Europe' },
  { value: 'asia', label: 'Asia' },
  { value: 'latam', label: 'LATAM' },
  { value: 'africa', label: 'Africa' },
  { value: 'oceania', label: 'Oceania' },
];
const MAP_VIEW_OPTIONS: Array<{ value: MapViewMode; label: string }> = [
  { value: '3d', label: '3D Globe' },
  { value: '2d', label: '2D Map' },
  { value: 'heatmap', label: 'Heatmap' },
  { value: 'density', label: 'Risk Density' },
];

function isMapViewMode(value: unknown): value is MapViewMode {
  return value === '3d' || value === '2d' || value === 'heatmap' || value === 'density';
}

const MAP_BOTTOM_PANEL_IDS: string[] = [];
const FOCUSED_STRIP_PANEL_IDS = new Set(['active-markets', 'price-chart', 'lob-depth', 'global-orderfilled', 'oracle-feed']);
const MARKET_WORKSPACE_PANEL_IDS = new Set([
  'market-summary',
  'featured-market',
  'price-implications',
  'price-chart',
  'sample-chain-trades',
  'lob-depth',
  'oracle-timeline',
  'related-news',
]);
const PANEL_ROW_RESIZE_STEP = 200;
const PANEL_COL_RESIZE_STEP = 260;
const PANEL_DRAG_THRESHOLD = 8;
const PANEL_MIN_ROW_SPAN = 1;
const PANEL_MAX_ROW_SPAN = 4;
const PANEL_MIN_COL_SPAN = 1;
const PANEL_MAX_COL_SPAN = 3;

type PanelLayoutPrefs = Record<string, { rowSpan?: number; colSpan?: number }>;
type PanelSizeHint = 'default' | 'wide' | 'tall' | undefined;
type WorkspaceMode = 'world' | 'worldcup';

function clampSpan(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, Math.round(value)));
}

function defaultPanelRowSpan(size: PanelSizeHint) {
  return size === 'tall' ? 2 : 1;
}

function defaultPanelColSpan(size: PanelSizeHint) {
  return size === 'wide' ? 2 : 1;
}

function getPanelLayout(layoutPrefs: PanelLayoutPrefs, panelId: string, size: PanelSizeHint) {
  const saved = layoutPrefs[panelId] || {};
  return {
    rowSpan: clampSpan(saved.rowSpan ?? defaultPanelRowSpan(size), PANEL_MIN_ROW_SPAN, PANEL_MAX_ROW_SPAN),
    colSpan: clampSpan(saved.colSpan ?? defaultPanelColSpan(size), PANEL_MIN_COL_SPAN, PANEL_MAX_COL_SPAN),
  };
}

function reorderPanelIds(panelIds: string[], draggedPanelId: string, targetPanelId: string, insertAfter: boolean) {
  if (draggedPanelId === targetPanelId) return panelIds;
  const next = panelIds.filter((panelId) => panelId !== draggedPanelId);
  const targetIndex = next.indexOf(targetPanelId);
  if (targetIndex === -1) return panelIds;
  next.splice(targetIndex + (insertAfter ? 1 : 0), 0, draggedPanelId);
  return next;
}

function clampMapZoom(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 1;
  return Math.max(1, Math.min(4, Math.round(numeric)));
}

function isLiveStatus(status?: string | null) {
  const normalized = String(status || '').trim().toLowerCase();
  return normalized === 'active' || normalized === 'proposed';
}

type DefaultMarketCandidate = Pick<MarketSummary, 'id' | 'slug' | 'title' | 'category' | 'tags' | 'status'>;

function isSuppressedDefaultMarket(market?: Partial<DefaultMarketCandidate> | null) {
  const text = [
    market?.title,
    market?.slug,
    market?.category,
    ...(market?.tags || []),
  ].filter(Boolean).join(' ').toLowerCase();
  return (
    text.includes(' up or down - ')
    || text.includes('updown-5m')
    || text.includes('updown-15m')
    || text.includes('recurring')
    || text.includes('hide-from-new')
    || text.includes('onchain-registry')
    || text.includes('on-chain recovered market')
  );
}

function pickDefaultMarketId(markets: MarketListItem[], featured?: MarketSummary | null) {
  const firstLive = markets.find((market) => isLiveStatus(market.status) && !isSuppressedDefaultMarket(market));
  if (firstLive) return firstLive.id;
  const firstEligible = markets.find((market) => !isSuppressedDefaultMarket(market));
  if (firstEligible) return firstEligible.id;
  if (featured && !isSuppressedDefaultMarket(featured)) return featured.id;
  return markets[0]?.id ?? featured?.id ?? null;
}

function pickDefaultMarketGroup(groups: MarketGroupItem[]) {
  const liveGroups = groups.filter((group) => Number(group.tradeCount24h || 0) > 0);
  return (
    liveGroups.find((group) => Number(group.volume24h || 0) > 0 && Number(group.outcomeCount || 0) > 1)
    || liveGroups.find((group) => Number(group.outcomeCount || 0) > 1)
    || liveGroups[0]
    || null
  );
}

function currentUtcClock(now: Date) {
  return now.toLocaleString('en-GB', {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZone: 'UTC',
    hour12: false,
  }).replace(',', '').toUpperCase() + ' UTC';
}

function LiveUtcClock() {
  const [clockNow, setClockNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setClockNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return <div className="wm-map-clock">{currentUtcClock(clockNow)}</div>;
}

function commandMarketStatus(market: MarketListItem) {
  const status = String(market.status || 'market').trim();
  return status ? status.replace(/[_-]+/g, ' ').toUpperCase() : 'MARKET';
}

function commandMarketStatusClass(market: MarketListItem) {
  const status = String(market.status || '').toLowerCase();
  if (status.includes('active') || status.includes('open')) return 'active';
  if (status.includes('closed')) return 'closed';
  if (status.includes('resolved') || status.includes('final')) return 'resolved';
  return 'neutral';
}

function commandMarketFreshness(market: MarketListItem) {
  return formatRelative(market.lastTradeAt || null);
}

function hasGeoConflictCoordinates(item: RuntimeGeoSanctionsShockItem) {
  const lat = Number(item.latitude);
  const lon = Number(item.longitude);
  return Number.isFinite(lat) && Number.isFinite(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
}

function WeatherInlineMap({
  payload,
  ucdpEvents,
  loading,
  error,
  selectedCityId,
  onSelectCity,
  onRefresh,
}: {
  payload?: RuntimeGlobalWeatherMapPayload | null;
  ucdpEvents: RuntimeGeoSanctionsShockItem[];
  loading: boolean;
  error?: string | null;
  selectedCityId: string | null;
  onSelectCity: (cityId: string) => void;
  onRefresh: () => void;
}) {
  const [detailOpen, setDetailOpen] = useState(false);
  const [clockNow, setClockNow] = useState(() => new Date());
  const items = payload?.items || [];
  const selected = items.find((item) => item.cityId === selectedCityId) || items[0] || null;
  const mappedCount = payload?.summary?.mappedCount ?? items.length;
  const cityCount = payload?.summary?.cityCount ?? items.length;
  const cacheMode = payload?.cacheMode || (loading ? 'loading' : 'seed');
  const selectCity = (cityId: string) => {
    onSelectCity(cityId);
    setDetailOpen(true);
  };
  const selectedTimezone = normalizeTimezone(selected?.timezone);
  const selectedClock: WorldClockLocation | null = selected && selectedTimezone
    ? { id: `map-selected-${selected.cityId || selected.city}`, city: String(selected.city || 'Selected'), venue: 'LOCAL', timezone: selectedTimezone, market: 'generic' }
    : null;
  const mapClocks = buildWorldClockRows(
    clockNow,
    selectedClock && !CORE_WORLD_CLOCKS.some((row) => row.timezone === selectedClock.timezone)
      ? [selectedClock, ...CORE_WORLD_CLOCKS.slice(0, 3)]
      : CORE_WORLD_CLOCKS.slice(0, 3),
  );
  useEffect(() => {
    const timer = window.setInterval(() => setClockNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <div className="wm-inline-weather-map">
      <div className="wm-inline-weather-map-hint">Use the mouse wheel to zoom and drag to pan the map.</div>
      <div className="wm-inline-weather-clock-strip" aria-label="World clock overlay">
        {mapClocks.map((clock) => (
          <span key={clock.id} className={clock.open ? 'open' : ''}>
            <b>{clock.city}</b>
            <strong>{clock.time}</strong>
            <em>{clock.open ? 'OPEN' : 'CLSD'} · {clock.gmtLabel}</em>
          </span>
        ))}
      </div>
      <button type="button" className="wm-inline-weather-map-cache" onClick={onRefresh}>
        {cacheMode}
      </button>
      <div className="wm-inline-weather-map-count" aria-hidden="true">
        {mappedCount}/{cityCount}
      </div>
      {error ? <div className="wm-inline-weather-map-error">{error}</div> : null}
      {!items.length && loading ? (
        <div className="wm-weather-deck-map wm-weather-deck-map-loading"><span>LOADING WEATHER MAP</span></div>
      ) : null}
      {!items.length && !loading ? (
        <div className="wm-weather-deck-map wm-weather-deck-map-loading"><span>WEATHER MAP WARMING</span></div>
      ) : null}
      {items.length ? <WeatherDeckMap items={items} ucdpEvents={ucdpEvents} selectedCityId={selected?.cityId || null} onSelectCity={selectCity} height={620} /> : null}
      {detailOpen && selected ? <WeatherMapCityInspector city={selected} onClose={() => setDetailOpen(false)} /> : null}
    </div>
  );
}

function sanitizePanelIds(panelIds: string[]) {
  const valid = new Set(PANEL_LIBRARY.map((panel) => panel.id));
  const unique: string[] = [];
  for (const panelId of panelIds) {
    if (!valid.has(panelId) || unique.includes(panelId)) continue;
    unique.push(panelId);
  }
  return unique;
}

function readJsonStorage<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function readStringStorage<T extends string>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback;
  const raw = window.localStorage.getItem(key);
  return (raw as T) || fallback;
}

type GeoShockLocalSeed = {
  storedAt: number;
  payload: RuntimeGeoSanctionsShockPayload;
};

function hasRenderableGeoShockPayload(payload?: RuntimeGeoSanctionsShockPayload | null) {
  return Boolean((payload?.items || []).some(hasGeoConflictCoordinates));
}

function readGeoShockRuntimeSeed(): PanelRuntimeData {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(GEO_SHOCK_STORAGE_KEY);
    if (!raw) return {};
    const cached = JSON.parse(raw) as GeoShockLocalSeed;
    if (!cached?.payload || !hasRenderableGeoShockPayload(cached.payload)) return {};
    if (Date.now() - Number(cached.storedAt || 0) > GEO_SHOCK_LOCAL_STALE_MS) return {};
    return {
      'geo-sanctions-shock': {
        ...cached.payload,
        cacheMode: 'local-stale',
      },
    };
  } catch {
    return {};
  }
}

function writeGeoShockRuntimeSeed(payload?: RuntimeGeoSanctionsShockPayload | null) {
  if (typeof window === 'undefined' || !hasRenderableGeoShockPayload(payload)) return;
  try {
    window.localStorage.setItem(GEO_SHOCK_STORAGE_KEY, JSON.stringify({ storedAt: Date.now(), payload }));
  } catch {
    // The remote seed remains authoritative; local storage is only a first-paint fallback.
  }
}

function readSearchParam(key: string): string | null {
  if (typeof window === 'undefined') return null;
  return new URLSearchParams(window.location.search).get(key);
}

function readMarketGroupSortStorage(): MarketGroupSort {
  const saved = readStringStorage<string>(MARKET_GROUP_SORT_STORAGE_KEY, 'active');
  return saved === 'new'
    || saved === 'volume'
    || saved === 'active'
    || saved === 'close'
    || saved === 'move'
    || saved === 'trades'
    ? saved
    : 'active';
}

function readWorkspaceMode(): WorkspaceMode {
  const override = readSearchParam('workspace');
  if (override === 'worldcup') return 'worldcup';
  const saved = readStringStorage<string>(WORKSPACE_MODE_STORAGE_KEY, 'world');
  return saved === 'worldcup' ? 'worldcup' : 'world';
}

function findGroupForMarketId(groups: MarketGroupItem[], marketId: number | null) {
  if (!marketId) return null;
  return groups.find((group) => (group.outcomes || []).some((outcome) => Number(outcome.marketId) === marketId)) || null;
}

function outcomeKeyForGroupMarket(group: MarketGroupItem, marketId?: number | null, fallbackKey?: string | null) {
  const numericMarketId = marketId != null ? Number(marketId) : null;
  if (numericMarketId != null && Number.isFinite(numericMarketId)) {
    const matchedOutcome = [...(group.outcomes || []), ...(group.topOutcomes || [])]
      .find((outcome) => Number(outcome.marketId) === numericMarketId);
    if (matchedOutcome?.outcomeKey) return matchedOutcome.outcomeKey;
  }
  return fallbackKey || group.defaultOutcomeKey || null;
}

type RuntimePanelRefreshOptions = {
  bootstrapPayload?: BootstrapPayload | null;
  activePanelIds?: string[];
};

type IdleSchedulerWindow = Window & typeof globalThis & {
  requestIdleCallback?: (
    callback: (deadline: IdleDeadline) => void,
    options?: { timeout: number },
  ) => number;
  cancelIdleCallback?: (handle: number) => void;
};

function scheduleIdleTask(task: () => void) {
  if (typeof window === 'undefined') return () => undefined;
  const idleWindow = window as IdleSchedulerWindow;
  if (typeof idleWindow.requestIdleCallback === 'function') {
    // Give slow runtime panels a bounded delay so animated views do not starve them forever.
    const handle = idleWindow.requestIdleCallback(() => task(), { timeout: 1200 });
    return () => {
      if (typeof idleWindow.cancelIdleCallback === 'function') {
        idleWindow.cancelIdleCallback(handle);
      }
    };
  }
  const handle = window.setTimeout(task, 0);
  return () => window.clearTimeout(handle);
}

function optimisticBundleFromMarket(market: MarketListItem): WorkspaceBundle {
  const latest = market.latestPrice ?? null;
  const numericLatest = Number(latest);
  const latestNo = Number.isFinite(numericLatest) ? String(1 - numericLatest) : null;
  const timestamp = market.lastTradeAt || market.createdAt || new Date().toISOString();
  return {
    market: {
      id: market.id,
      slug: market.slug,
      title: market.title,
      conditionId: market.conditionId,
      questionId: market.questionId,
      status: market.status,
      latestPrice: latest,
      latestYesPrice: latest,
      latestNoPrice: latestNo,
      endDate: market.endDate,
      createdAt: market.createdAt,
      category: market.category,
      tags: market.tags,
    },
    identity: {
      localMarketId: market.id,
      marketId: market.id,
      gammaMarketId: market.gammaMarketId,
      slug: market.slug,
      conditionId: market.conditionId,
      questionId: market.questionId,
    },
    diagnostics: null,
    health: null,
    group: null,
    selectedOutcome: null,
    trades: [],
    oracle: null,
    price: {
      marketId: market.id,
      latestPrice: latest == null ? null : String(latest),
      latestYesPrice: latest == null ? null : String(latest),
      latestNoPrice: latestNo,
      change24h: market.change24h == null ? null : String(market.change24h),
      volume24h: market.volume24h == null ? null : String(market.volume24h),
      tradeCount24h: Number(market.tradeCount24h || 0),
      updatedAt: timestamp,
    },
    chart: latest == null
      ? null
      : {
          marketId: market.id,
          range: 'snapshot',
          interval: 'snapshot',
          kind: 'probability',
          points: [
            { timestamp, yesPrice: latest, noPrice: latestNo },
            { timestamp: new Date().toISOString(), yesPrice: latest, noPrice: latestNo },
          ],
        },
    content: null,
    lob: null,
  };
}

function emptyWorkspaceBundle(): WorkspaceBundle {
  return {
    market: null,
    identity: null,
    diagnostics: null,
    health: null,
    group: null,
    selectedOutcome: null,
    trades: [],
    oracle: null,
    price: null,
    chart: null,
    content: null,
    lob: null,
  };
}

function isSnapshotChart(chart: WorkspaceBundle['chart']) {
  if (!chart) return false;
  return chart.range === 'snapshot' || chart.interval === 'snapshot' || (chart.points || []).length <= 2;
}

function chooseWorkspaceChart(current: WorkspaceBundle['chart'], patch: WorkspaceBundle['chart']) {
  const patchPoints = patch?.points || [];
  if (!patchPoints.length) return current;
  if (!patch) return current;
  const currentPoints = current?.points || [];
  if (!currentPoints.length) return patch;
  const patchIsSnapshot = isSnapshotChart(patch);
  const currentIsSnapshot = isSnapshotChart(current);
  if (patchIsSnapshot && !currentIsSnapshot) return current;
  if (!patchIsSnapshot && currentIsSnapshot) return patch;
  if (patch.range !== current?.range && !patchIsSnapshot) return patch;
  return patchPoints.length >= currentPoints.length ? patch : current;
}

function lobHasLevels(lob: WorkspaceBundle['lob']) {
  const yesLevels = (lob?.yes?.bids?.length || 0) + (lob?.yes?.asks?.length || 0);
  const noLevels = (lob?.no?.bids?.length || 0) + (lob?.no?.asks?.length || 0);
  return yesLevels + noLevels > 0;
}

function chooseWorkspaceLob(current: WorkspaceBundle['lob'], patch: WorkspaceBundle['lob']) {
  if (!patch) return current;
  if (lobHasLevels(patch)) return patch;
  if (lobHasLevels(current)) return current;
  return patch;
}

function bundleMatchesMarket(bundle: WorkspaceBundle | null, marketId: number) {
  if (!bundle) return false;
  const ids = [
    bundle.market?.id,
    bundle.identity?.localMarketId,
    bundle.identity?.marketId,
    bundle.price?.marketId,
    bundle.oracle?.localMarketId,
    bundle.oracle?.marketId,
    bundle.chart?.localMarketId,
    bundle.chart?.marketId,
    bundle.content?.marketId,
    bundle.lob?.localMarketId,
    bundle.lob?.marketId,
    bundle.selectedOutcome?.marketId,
    bundle.trades?.[0]?.marketId,
  ];
  return ids.some((id) => Number(id) === Number(marketId));
}

function mergeWorkspaceBundle(base: WorkspaceBundle | null, patch: WorkspaceBundle): WorkspaceBundle {
  const current = base || emptyWorkspaceBundle();
  return {
    market: patch.market || current.market,
    identity: patch.identity || current.identity,
    diagnostics: patch.diagnostics || current.diagnostics,
    health: patch.health || current.health,
    group: patch.group || current.group,
    selectedOutcome: patch.selectedOutcome || current.selectedOutcome,
    price: patch.price || current.price,
    chart: chooseWorkspaceChart(current.chart, patch.chart),
    trades: patch.trades?.length ? patch.trades : current.trades,
    oracle: patch.oracle || current.oracle,
    content: patch.content?.items?.length ? patch.content : current.content,
    lob: chooseWorkspaceLob(current.lob, patch.lob),
  };
}

function PanelWorkspaceSlot({
  panelId,
  size,
  layoutPrefs,
  children,
  loading = false,
  className = '',
  layoutManaged = true,
  resizeEnabled = true,
  onMovePanel,
  onResizePanel,
  onResetPanelLayout,
}: {
  panelId: string;
  size: PanelSizeHint;
  layoutPrefs: PanelLayoutPrefs;
  children: ComponentChildren;
  loading?: boolean;
  className?: string;
  layoutManaged?: boolean;
  resizeEnabled?: boolean;
  onMovePanel: (draggedPanelId: string, targetPanelId: string, insertAfter: boolean) => void;
  onResizePanel: (panelId: string, patch: { rowSpan?: number; colSpan?: number }) => void;
  onResetPanelLayout: (panelId: string) => void;
}) {
  const slotRef = useRef<HTMLDivElement | null>(null);
  const layout = getPanelLayout(layoutPrefs, panelId, size);
  const dragRef = useRef<{
    active: boolean;
    started: boolean;
    startX: number;
    startY: number;
    lastX: number;
    lastY: number;
    offsetX: number;
    offsetY: number;
    rafId: number;
    ghost: HTMLElement | null;
    indicator: HTMLElement | null;
    lastTarget: HTMLElement | null;
  }>({
    active: false,
    started: false,
    startX: 0,
    startY: 0,
    lastX: 0,
    lastY: 0,
    offsetX: 0,
    offsetY: 0,
    rafId: 0,
    ghost: null,
    indicator: null,
    lastTarget: null,
  });
  const resizeRef = useRef<{
    active: boolean;
    axis: 'row' | 'col';
    startX: number;
    startY: number;
    startSpan: number;
    move?: (event: MouseEvent) => void;
    up?: () => void;
  }>({
    active: false,
    axis: 'row',
    startX: 0,
    startY: 0,
    startSpan: 1,
  });

  const clearDragVisuals = () => {
    const state = dragRef.current;
    if (state.rafId) {
      window.cancelAnimationFrame(state.rafId);
      state.rafId = 0;
    }
    slotRef.current?.classList.remove('dragging-source');
    if (state.lastTarget) {
      state.lastTarget.classList.remove('panel-drop-target');
      state.lastTarget = null;
    }
    if (state.ghost) {
      const ghost = state.ghost;
      ghost.style.opacity = '0';
      window.setTimeout(() => ghost.remove(), 160);
      state.ghost = null;
    }
    if (state.indicator) {
      const indicator = state.indicator;
      indicator.style.opacity = '0';
      window.setTimeout(() => indicator.remove(), 160);
      state.indicator = null;
    }
  };

  const findDropTarget = (clientX: number, clientY: number) => {
    const hit = document.elementFromPoint(clientX, clientY) as HTMLElement | null;
    const targetSlot = hit?.closest<HTMLElement>('.wm-panel-slot[data-workspace-panel-id]') || null;
    if (!targetSlot) return null;
    const targetPanelId = targetSlot.dataset.workspacePanelId;
    if (!targetPanelId || targetPanelId === panelId) return null;
    const rect = targetSlot.getBoundingClientRect();
    return {
      targetSlot,
      targetPanelId,
      insertAfter: clientY > rect.top + rect.height / 2 || (
        Math.abs(clientY - (rect.top + rect.height / 2)) < Math.min(48, rect.height / 4)
        && clientX > rect.left + rect.width / 2
      ),
      rect,
    };
  };

  const updateDropIndicator = (clientX: number, clientY: number) => {
    const state = dragRef.current;
    if (!state.indicator) return;
    const target = findDropTarget(clientX, clientY);
    if (!target) {
      state.indicator.style.opacity = '0';
      if (state.lastTarget) {
        state.lastTarget.classList.remove('panel-drop-target');
        state.lastTarget = null;
      }
      return;
    }
    if (target.targetSlot !== state.lastTarget) {
      state.lastTarget?.classList.remove('panel-drop-target');
      target.targetSlot.classList.add('panel-drop-target');
      state.lastTarget = target.targetSlot;
    }
    state.indicator.style.left = `${target.rect.left}px`;
    state.indicator.style.top = `${target.insertAfter ? target.rect.bottom : target.rect.top - 4}px`;
    state.indicator.style.width = `${target.rect.width}px`;
    state.indicator.style.opacity = '0.9';
  };

  const startDrag = (event: MouseEvent) => {
    if (event.button !== 0 || !slotRef.current) return;
    const target = event.target as HTMLElement;
    if (target.closest('button, a, input, select, textarea, [role="button"], .wm-panel-resize-handle, .wm-panel-col-resize-handle')) return;
    if (!target.closest('.wm-panel-header')) return;
    const rect = slotRef.current.getBoundingClientRect();
    dragRef.current = {
      active: true,
      started: false,
      startX: event.clientX,
      startY: event.clientY,
      lastX: event.clientX,
      lastY: event.clientY,
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      rafId: 0,
      ghost: null,
      indicator: null,
      lastTarget: null,
    };
    event.preventDefault();

    const onMouseMove = (moveEvent: MouseEvent) => {
      const state = dragRef.current;
      if (!state.active || !slotRef.current) return;
      state.lastX = moveEvent.clientX;
      state.lastY = moveEvent.clientY;
      if (!state.started) {
        const dx = Math.abs(moveEvent.clientX - state.startX);
        const dy = Math.abs(moveEvent.clientY - state.startY);
        if (dx < PANEL_DRAG_THRESHOLD && dy < PANEL_DRAG_THRESHOLD) return;
        const sourceRect = slotRef.current.getBoundingClientRect();
        const sourcePanel = slotRef.current.querySelector<HTMLElement>(':scope > .wm-panel') || slotRef.current;
        state.started = true;
        const ghost = sourcePanel.cloneNode(true) as HTMLElement;
        ghost.querySelectorAll('iframe').forEach((frame) => frame.remove());
        ghost.classList.remove('dragging-source');
        ghost.classList.add('wm-panel-drag-ghost');
        ghost.setAttribute('aria-hidden', 'true');
        ghost.style.position = 'fixed';
        ghost.style.pointerEvents = 'none';
        ghost.style.zIndex = '10000';
        ghost.style.opacity = '0.9';
        ghost.style.boxShadow = '0 28px 80px rgba(0, 0, 0, 0.68), 0 0 0 1px rgba(146, 192, 246, 0.42), 0 0 40px rgba(78, 132, 198, 0.32)';
        ghost.style.transform = 'scale(1.02)';
        ghost.style.width = `${sourceRect.width}px`;
        ghost.style.height = `${sourceRect.height}px`;
        ghost.style.left = `${moveEvent.clientX - state.offsetX}px`;
        ghost.style.top = `${moveEvent.clientY - state.offsetY}px`;
        document.body.appendChild(ghost);
        state.ghost = ghost;
        slotRef.current.classList.add('dragging-source');
        const indicator = document.createElement('div');
        indicator.className = 'wm-panel-drop-indicator';
        document.body.appendChild(indicator);
        state.indicator = indicator;
      }
      if (state.rafId) window.cancelAnimationFrame(state.rafId);
      state.rafId = window.requestAnimationFrame(() => {
        const latest = dragRef.current;
        if (latest.ghost) {
          latest.ghost.style.left = `${latest.lastX - latest.offsetX}px`;
          latest.ghost.style.top = `${latest.lastY - latest.offsetY}px`;
        }
        updateDropIndicator(latest.lastX, latest.lastY);
        latest.rafId = 0;
      });
    };

    const finishDrag = () => {
      const state = dragRef.current;
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', finishDrag);
      document.removeEventListener('keydown', onKeyDown);
      if (state.active && state.started) {
        const target = findDropTarget(state.lastX, state.lastY);
        if (target) onMovePanel(panelId, target.targetPanelId, target.insertAfter);
      }
      state.active = false;
      state.started = false;
      clearDragVisuals();
    };

    const onKeyDown = (keyEvent: KeyboardEvent) => {
      if (keyEvent.key !== 'Escape') return;
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', finishDrag);
      document.removeEventListener('keydown', onKeyDown);
      dragRef.current.active = false;
      dragRef.current.started = false;
      clearDragVisuals();
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', finishDrag);
    document.addEventListener('keydown', onKeyDown);
  };

  const startResize = (axis: 'row' | 'col', event: MouseEvent) => {
    if (!resizeEnabled) return;
    event.preventDefault();
    event.stopPropagation();
    resizeRef.current.active = true;
    resizeRef.current.axis = axis;
    resizeRef.current.startX = event.clientX;
    resizeRef.current.startY = event.clientY;
    resizeRef.current.startSpan = axis === 'row' ? layout.rowSpan : layout.colSpan;
    slotRef.current?.classList.add(axis === 'row' ? 'resizing' : 'col-resizing');
    document.body.classList.add('panel-resize-active');

    const onMouseMove = (moveEvent: MouseEvent) => {
      const state = resizeRef.current;
      if (!state.active) return;
      if (state.axis === 'row') {
        const nextSpan = clampSpan(state.startSpan + Math.round((moveEvent.clientY - state.startY) / PANEL_ROW_RESIZE_STEP), PANEL_MIN_ROW_SPAN, PANEL_MAX_ROW_SPAN);
        onResizePanel(panelId, { rowSpan: nextSpan });
      } else {
        const nextSpan = clampSpan(state.startSpan + Math.round((moveEvent.clientX - state.startX) / PANEL_COL_RESIZE_STEP), PANEL_MIN_COL_SPAN, PANEL_MAX_COL_SPAN);
        onResizePanel(panelId, { colSpan: nextSpan });
      }
    };

    const onMouseUp = () => {
      resizeRef.current.active = false;
      slotRef.current?.classList.remove('resizing', 'col-resizing');
      document.body.classList.remove('panel-resize-active');
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };

    resizeRef.current.move = onMouseMove;
    resizeRef.current.up = onMouseUp;
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  };

  useEffect(() => {
    return () => {
      const resizeState = resizeRef.current;
      if (resizeState.move) document.removeEventListener('mousemove', resizeState.move);
      if (resizeState.up) document.removeEventListener('mouseup', resizeState.up);
      clearDragVisuals();
    };
  }, []);

  return (
    <div
      className={`wm-panel-slot ${layoutManaged ? 'is-layout-managed' : ''} ${className}`.trim()}
      data-workspace-panel-id={panelId}
      ref={slotRef}
      onMouseDown={startDrag}
      style={{
        '--wm-panel-row-span': String(layout.rowSpan),
        '--wm-panel-col-span': String(layout.colSpan),
      } as Record<string, string>}
  >
      {children}
      {loading ? (
        <div className="wm-panel-slot-loading">
          <PanelLoading detail="正在同步这个 panel 的实时数据" />
        </div>
      ) : null}
      {resizeEnabled ? (
        <>
          <button
            aria-label="Resize panel height"
            className="wm-panel-resize-handle"
            type="button"
            onDblClick={() => onResetPanelLayout(panelId)}
            onMouseDown={(event) => startResize('row', event)}
          />
          <button
            aria-label="Resize panel width"
            className="wm-panel-col-resize-handle"
            type="button"
            onDblClick={() => onResetPanelLayout(panelId)}
            onMouseDown={(event) => startResize('col', event)}
          />
        </>
      ) : null}
    </div>
  );
}

function WorldMonitorApp() {
  const [bootstrap, setBootstrap] = useState<BootstrapPayload | null>(null);
  const [markets, setMarkets] = useState<MarketListItem[]>([]);
  const [marketGroups, setMarketGroups] = useState<MarketGroupItem[]>([]);
  const [marketGroupSort, setMarketGroupSort] = useState<MarketGroupSort>(() => readMarketGroupSortStorage());
  const [selectedMarketGroupId, setSelectedMarketGroupId] = useState<string | null>(null);
  const [selectedMarketGroupOutcomeKey, setSelectedMarketGroupOutcomeKey] = useState<string | null>(null);
  const [selectedMarketGroupDetail, setSelectedMarketGroupDetail] = useState<MarketGroupDetail | null>(null);
  const [selectedMarketGroupChart, setSelectedMarketGroupChart] = useState<MarketGroupChartPayload | null>(null);
  const [selectedMarketGroupChartRange, setSelectedMarketGroupChartRange] = useState<MarketGroupChartRange>('1d');
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [bundle, setBundle] = useState<WorkspaceBundle | null>(null);
  const [selectedMarketId, setSelectedMarketId] = useState<number | null>(null);
  const [globalTrades, setGlobalTrades] = useState<TradeRow[]>([]);
  const [globalOracle, setGlobalOracle] = useState<OracleEvent[]>([]);
  const [latestContent, setLatestContent] = useState<ContentItem[]>([]);
  const [runtimeData, setRuntimeData] = useState<PanelRuntimeData>(() => readGeoShockRuntimeSeed());
  const [panelLoadingIds, setPanelLoadingIds] = useState<Set<string>>(() => new Set());
  const [marketQuery] = useState('');
  const [layerQuery, setLayerQuery] = useState('');
  const [commandQuery, setCommandQuery] = useState('');
  const [commandTab, setCommandTab] = useState<CommandPaletteTab>('markets');
  const [commandActiveMarketId, setCommandActiveMarketId] = useState<number | null>(null);
  const [commandMarketHits, setCommandMarketHits] = useState<MarketListItem[]>([]);
  const [commandMarketSearchLoading, setCommandMarketSearchLoading] = useState(false);
  const [commandMarketSearchError, setCommandMarketSearchError] = useState('');
  const [layers, setLayers] = useState<LayerToggle[]>(INITIAL_LAYERS);
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>(() => readWorkspaceMode());
  const [activePanelIds, setActivePanelIds] = useState<string[]>([]);
  const [panelLayoutPrefs, setPanelLayoutPrefs] = useState<PanelLayoutPrefs>(() => readJsonStorage<PanelLayoutPrefs>(PANEL_LAYOUT_STORAGE_KEY, {}));
  const [panelPrefsLoaded, setPanelPrefsLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [bundleLoading, setBundleLoading] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const [viewMode, setViewMode] = useState<MapViewMode>(() => {
    const override = readSearchParam('view');
    if (isMapViewMode(override)) return override;
    const stored = readStringStorage(VIEW_STORAGE_KEY, '3d');
    return isMapViewMode(stored) ? stored : '3d';
  });
  const [globeStatus, setGlobeStatus] = useState<WorldGlobeStatusMetrics>({
    fps: 0,
    markerTotal: 0,
    markerVisible: 0,
    qualitySetting: 'auto',
    qualityLevel: 'high',
    dpr: 1,
  });
  const [region, setRegion] = useState<RegionKey>(() => {
    const override = readSearchParam('region');
    return REGION_OPTIONS.some((option) => option.value === override) ? (override as RegionKey) : readStringStorage(REGION_STORAGE_KEY, 'global');
  });
  const [mapZoom, setMapZoom] = useState<number>(() => clampMapZoom(readJsonStorage(ZOOM_STORAGE_KEY, 1)));
  const [showPanelLibrary, setShowPanelLibrary] = useState<boolean>(() => Boolean(readJsonStorage(LIBRARY_STORAGE_KEY, true)));
  const [showCommandPalette, setShowCommandPalette] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [weatherMapPayload, setWeatherMapPayload] = useState<RuntimeGlobalWeatherMapPayload | null>(null);
  const [weatherMapLoading, setWeatherMapLoading] = useState(false);
  const [weatherMapError, setWeatherMapError] = useState<string | null>(null);
  const [selectedWeatherCityId, setSelectedWeatherCityId] = useState<string | null>(null);
  const bootstrapRef = useRef<BootstrapPayload | null>(null);
  const selectedMarketIdRef = useRef<number | null>(null);
  const selectedMarketGroupIdRef = useRef<string | null>(null);
  const marketGroupSortRef = useRef<MarketGroupSort>(marketGroupSort);
  const slowRefreshCancelRef = useRef<(() => void) | null>(null);
  const slowRefreshInFlightRef = useRef<Set<string>>(new Set());
  const bundleRequestSeqRef = useRef(0);
  const bundleCacheRef = useRef<Map<number, WorkspaceBundle>>(new Map());

  const setPanelsLoading = (panelIds: string[], nextLoading: boolean) => {
    if (!panelIds.length) return;
    setPanelLoadingIds((current) => {
      const next = new Set(current);
      panelIds.forEach((panelId) => {
        if (nextLoading) next.add(panelId);
        else next.delete(panelId);
      });
      return next;
    });
  };

  const focusMarketGroup = (group: MarketGroupItem, outcomeKey?: string | null, marketId?: number | null) => {
    const eventId = group.eventId != null ? String(group.eventId) : null;
    const nextMarketId = marketId != null ? Number(marketId) : null;
    const nextOutcomeKey = outcomeKeyForGroupMarket(group, nextMarketId, outcomeKey);
    selectedMarketGroupIdRef.current = eventId;
    selectedMarketIdRef.current = nextMarketId;
    setSelectedMarketGroupId(eventId);
    setSelectedMarketGroupOutcomeKey(nextOutcomeKey);
    setSelectedMarketId(nextMarketId);
  };

  useEffect(() => {
    selectedMarketIdRef.current = selectedMarketId;
  }, [selectedMarketId]);

  useEffect(() => {
    selectedMarketGroupIdRef.current = selectedMarketGroupId;
  }, [selectedMarketGroupId]);

  async function refreshFastRuntimePanels(options: RuntimePanelRefreshOptions = {}): Promise<{ marketsPayload: MarketsPayload | null; marketGroupsPayload: MarketGroupsPayload | null }> {
    const bootstrapPayload = options.bootstrapPayload || bootstrapRef.current;
    const fastRuntimePanelIds = FAST_RUNTIME_PANELS.map((panel) => panel.id);
    setPanelsLoading(fastRuntimePanelIds, true);
    const settled = await Promise.allSettled([
      fetchSystemHealth(),
      fetchRecentTrades(24),
      fetchRecentOracle(16),
      fetchLatestContent(12),
      fetchMarketGroups('', FAST_MARKETS_PAGE_SIZE, marketGroupSortRef.current),
      fetchAllActiveMarkets('', FAST_MARKETS_PAGE_SIZE),
      fetchPanelRuntimeData(
        FAST_RUNTIME_PANELS,
        (panelId, value) => {
          setRuntimeData((current) => mergeRuntimeData(current, { [panelId]: value }));
        },
        (panelId) => setPanelsLoading([panelId], false),
      ),
    ]);

    const fallbackMarkets = bootstrapPayload?.activeMarketsPreview || [];
    if (settled[0].status === 'fulfilled') setHealth(settled[0].value);
    else if (bootstrapPayload?.systemHealth) setHealth(bootstrapPayload.systemHealth);

    if (settled[1].status === 'fulfilled') setGlobalTrades(settled[1].value);
    else if (bootstrapPayload?.globalTradesPreview) setGlobalTrades(bootstrapPayload.globalTradesPreview);

    if (settled[2].status === 'fulfilled') setGlobalOracle(settled[2].value);
    else if (bootstrapPayload?.globalOraclePreview) setGlobalOracle(bootstrapPayload.globalOraclePreview);

    if (settled[3].status === 'fulfilled') setLatestContent(settled[3].value.items || []);
    else if (bootstrapPayload?.latestContentPreview) setLatestContent(bootstrapPayload.latestContentPreview);

    if (settled[4].status === 'fulfilled') setMarketGroups(settled[4].value.items || []);

    if (settled[5].status === 'fulfilled') setMarkets(settled[5].value.items || []);
    else if (fallbackMarkets.length) setMarkets(fallbackMarkets);

    const fastRuntimeResult = settled[6];
    if (fastRuntimeResult.status === 'fulfilled') {
      setRuntimeData((current) => mergeRuntimeData(current, fastRuntimeResult.value));
    } else if (bootstrapPayload?.commoditiesPreview) {
      setRuntimeData((current) => mergeRuntimeData(current, { 'commodities-watch': bootstrapPayload.commoditiesPreview }));
    }
    setPanelsLoading(fastRuntimePanelIds, false);

    return {
      marketsPayload: settled[5].status === 'fulfilled' ? settled[5].value : null,
      marketGroupsPayload: settled[4].status === 'fulfilled' ? settled[4].value : null,
    };
  }

  async function refreshSlowRuntimePanels(panels: typeof SLOW_RUNTIME_PANELS = SLOW_RUNTIME_PANELS) {
    const eligible = panels.filter((panel) => !slowRefreshInFlightRef.current.has(panel.id));
    if (!eligible.length) return;
    eligible.forEach((panel) => slowRefreshInFlightRef.current.add(panel.id));
    setPanelsLoading(eligible.map((panel) => panel.id), true);
    try {
      const patch = await fetchPanelRuntimeData(eligible, (panelId, value) => {
        setRuntimeData((current) => mergeRuntimeData(current, { [panelId]: value }));
      }, (panelId) => setPanelsLoading([panelId], false));
      setRuntimeData((current) => mergeRuntimeData(current, patch));
    } finally {
      eligible.forEach((panel) => slowRefreshInFlightRef.current.delete(panel.id));
      setPanelsLoading(eligible.map((panel) => panel.id), false);
    }
  }

  function scheduleSlowRuntimePanels(activePanelSet = new Set(activePanelIds), excludedPanelIds = new Set<string>()) {
    const panels = SLOW_RUNTIME_PANELS.filter((panel) => activePanelSet.has(panel.id) && !excludedPanelIds.has(panel.id));
    if (!panels.length || slowRefreshCancelRef.current) return;
    slowRefreshCancelRef.current = scheduleIdleTask(() => {
      slowRefreshCancelRef.current = null;
      void refreshSlowRuntimePanels(panels)
        .catch((loadError) => {
          setError((previous) => previous || (loadError instanceof Error ? loadError.message : 'Failed to refresh slow runtime panels.'));
        });
    });
  }

  async function refreshRuntimePanels(options: RuntimePanelRefreshOptions = {}) {
    const fastResult = await refreshFastRuntimePanels(options);
    const activePanelSet = new Set(options.activePanelIds || activePanelIds);
    const visibleSlowPanels = SLOW_RUNTIME_PANELS.filter((panel) => activePanelSet.has(panel.id));
    if (visibleSlowPanels.length) {
      void refreshSlowRuntimePanels(visibleSlowPanels).catch((loadError) => {
        setError((previous) => previous || (loadError instanceof Error ? loadError.message : 'Failed to refresh visible runtime panels.'));
      });
    }
    scheduleSlowRuntimePanels(activePanelSet, new Set(visibleSlowPanels.map((panel) => panel.id)));
    return fastResult;
  }

  useEffect(() => {
    if (workspaceMode !== 'worldcup') return undefined;
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, [workspaceMode]);

  useEffect(() => {
    const savedPanelIds = sanitizePanelIds(readJsonStorage<string[]>(PANEL_STORAGE_KEY, []));
    setActivePanelIds(savedPanelIds.length ? sanitizePanelIds([...savedPanelIds, ...DEFAULT_PANEL_IDS]) : DEFAULT_PANEL_IDS);
    setPanelPrefsLoaded(true);
  }, []);

  useEffect(() => {
    if (!panelPrefsLoaded || typeof window === 'undefined') return;
    window.localStorage.setItem(PANEL_STORAGE_KEY, JSON.stringify(activePanelIds));
  }, [activePanelIds, panelPrefsLoaded]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(PANEL_LAYOUT_STORAGE_KEY, JSON.stringify(panelLayoutPrefs));
  }, [panelLayoutPrefs]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(VIEW_STORAGE_KEY, viewMode);
  }, [viewMode]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(REGION_STORAGE_KEY, region);
  }, [region]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(LIBRARY_STORAGE_KEY, JSON.stringify(showPanelLibrary));
  }, [showPanelLibrary]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(ZOOM_STORAGE_KEY, JSON.stringify(mapZoom));
  }, [mapZoom]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(MARKET_GROUP_SORT_STORAGE_KEY, marketGroupSort);
  }, [marketGroupSort]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, workspaceMode);
    const url = new URL(window.location.href);
    if (workspaceMode === 'worldcup') {
      url.searchParams.set('workspace', 'worldcup');
    } else {
      url.searchParams.delete('workspace');
    }
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  }, [workspaceMode]);

  useEffect(() => {
    writeGeoShockRuntimeSeed(runtimeData['geo-sanctions-shock'] as RuntimeGeoSanctionsShockPayload | undefined);
  }, [runtimeData]);

  useEffect(() => {
    bootstrapRef.current = bootstrap;
  }, [bootstrap]);

  useEffect(() => {
    marketGroupSortRef.current = marketGroupSort;
  }, [marketGroupSort]);

  useEffect(() => {
    if (selectedMarketId == null) {
      if (!selectedMarketGroupId) {
        setSelectedMarketGroupId(null);
        setSelectedMarketGroupOutcomeKey(null);
        setSelectedMarketGroupDetail(null);
        setSelectedMarketGroupChart(null);
      }
      return;
    }
    const matchedGroup = findGroupForMarketId(marketGroups, selectedMarketId);
    if (!matchedGroup) {
      if (selectedMarketGroupId || selectedMarketGroupDetail || selectedMarketGroupChart || selectedMarketGroupOutcomeKey) {
        setSelectedMarketGroupId(null);
        setSelectedMarketGroupOutcomeKey(null);
        setSelectedMarketGroupDetail(null);
        setSelectedMarketGroupChart(null);
      }
      return;
    }
    const nextEventId = matchedGroup.eventId != null ? String(matchedGroup.eventId) : null;
    const matchedOutcome = (matchedGroup.outcomes || []).find((outcome) => Number(outcome.marketId) === selectedMarketId) || null;
    if (nextEventId && nextEventId !== selectedMarketGroupId) {
      setSelectedMarketGroupId(nextEventId);
      setSelectedMarketGroupDetail(null);
      setSelectedMarketGroupChart(null);
    }
    const nextOutcomeKey = matchedOutcome?.outcomeKey || matchedGroup.defaultOutcomeKey || null;
    if (nextOutcomeKey && nextOutcomeKey !== selectedMarketGroupOutcomeKey) {
      setSelectedMarketGroupOutcomeKey(nextOutcomeKey);
    }
  }, [
    marketGroups,
    selectedMarketGroupChart,
    selectedMarketGroupDetail,
    selectedMarketGroupId,
    selectedMarketGroupOutcomeKey,
    selectedMarketId,
  ]);

  useEffect(() => () => {
    slowRefreshCancelRef.current?.();
    slowRefreshCancelRef.current = null;
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const bootstrapPayload = await fetchBootstrap();
        if (cancelled) return;

        const defaultPanelIds = sanitizePanelIds(bootstrapPayload.defaultWorkspace?.panels || []);
        const immediatePanelIds = activePanelIds.length ? sanitizePanelIds([...activePanelIds, ...defaultPanelIds]) : defaultPanelIds;
        const bootstrapMarketGroups = bootstrapPayload.activeMarketGroupsPreview || [];
        const initialDefaultGroup = pickDefaultMarketGroup(bootstrapMarketGroups);
        const initialDefaultMarketId = initialDefaultGroup ? null : pickDefaultMarketId(
          bootstrapPayload.activeMarketsPreview || [],
          bootstrapPayload.featuredMarket,
        );

        setBootstrap(bootstrapPayload);
        setMarkets(bootstrapPayload.activeMarketsPreview || []);
        setMarketGroups(bootstrapMarketGroups);
        setHealth(bootstrapPayload.systemHealth || null);
        setGlobalTrades(bootstrapPayload.globalTradesPreview || []);
        setGlobalOracle(bootstrapPayload.globalOraclePreview || []);
        setLatestContent(bootstrapPayload.latestContentPreview || []);
        setRuntimeData((current) => mergeRuntimeData(current, bootstrapPayload.commoditiesPreview ? { 'commodities-watch': bootstrapPayload.commoditiesPreview } : {}));
        selectedMarketIdRef.current = initialDefaultMarketId;
        if (initialDefaultGroup) {
          focusMarketGroup(initialDefaultGroup, initialDefaultGroup.defaultOutcomeKey || null, initialDefaultGroup.defaultMarketId ?? null);
        } else {
          selectedMarketGroupIdRef.current = null;
          setSelectedMarketGroupId(null);
          setSelectedMarketGroupOutcomeKey(null);
          setSelectedMarketId(initialDefaultMarketId);
        }
        setActivePanelIds((current) => (
          current.length
            ? sanitizePanelIds([...current, ...defaultPanelIds])
            : defaultPanelIds
        ));
        setLoading(false);

        const focusFirstGroupIfInitial = (groups: MarketGroupItem[]) => {
          const selectionStillInitial = !selectedMarketGroupIdRef.current && selectedMarketIdRef.current === initialDefaultMarketId;
          if (!selectionStillInitial) return false;
          const firstGroup = pickDefaultMarketGroup(groups);
          if (!firstGroup) return false;
          focusMarketGroup(firstGroup, firstGroup.defaultOutcomeKey || null, firstGroup.defaultMarketId ?? null);
          return true;
        };

        void refreshRuntimePanels({ bootstrapPayload, activePanelIds: immediatePanelIds })
          .then(({ marketsPayload, marketGroupsPayload }) => {
            if (cancelled) return;
            if (focusFirstGroupIfInitial(marketGroupsPayload?.items || [])) {
              return;
            }
            const selectionStillInitial = !selectedMarketGroupIdRef.current && selectedMarketIdRef.current === initialDefaultMarketId;
            if (!selectionStillInitial) return;
            const marketItems = marketsPayload?.items || bootstrapPayload.activeMarketsPreview || [];
            const nextMarketId = pickDefaultMarketId(marketItems, bootstrapPayload.featuredMarket);
            selectedMarketIdRef.current = nextMarketId;
            setSelectedMarketId(nextMarketId);
          })
          .catch((loadError) => {
            if (!cancelled) {
              setError((previous) => previous || (loadError instanceof Error ? loadError.message : 'Failed to refresh global workspace data.'));
            }
          });
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load dashboard.');
          setLoading(false);
          void refreshRuntimePanels().catch(() => {
            // Runtime panels can still hydrate from seed snapshots when bootstrap is temporarily unavailable.
          });
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [panelPrefsLoaded]);

  useEffect(() => {
    let cancelled = false;

    async function refreshGlobalPanels() {
      try {
        await refreshRuntimePanels();
        if (cancelled) return;
      } catch (loadError) {
        if (!cancelled) {
          setError((previous) => previous || (loadError instanceof Error ? loadError.message : 'Failed to refresh snapshots.'));
        }
      }
    }

    const timer = window.setInterval(() => {
      void refreshGlobalPanels();
    }, 20000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const timers: number[] = [];

    async function refreshRuntimePanel(panelId: string) {
      try {
        const panel = PANEL_REGISTRY[panelId];
        setPanelsLoading([panelId], true);
        const payload = await panel?.fetchData?.();
        if (!cancelled && payload !== undefined) {
          setRuntimeData((current) => mergeRuntimeData(current, { [panelId]: payload }));
        }
      } catch {
        // Keep the latest visible runtime snapshot rather than flashing empty on transient upstream misses.
      } finally {
        if (!cancelled) setPanelsLoading([panelId], false);
      }
    }

    for (const panel of INTERVAL_RUNTIME_PANELS) {
      void refreshRuntimePanel(panel.id);
      const intervalMs = Number(panel.refresh?.intervalMs || 0);
      if (intervalMs > 0) {
        timers.push(window.setInterval(() => {
          void refreshRuntimePanel(panel.id);
        }, intervalMs));
      }
    }

    return () => {
      cancelled = true;
      timers.forEach((timer) => window.clearInterval(timer));
    };
  }, []);

  useEffect(() => {
    if (!marketQuery.trim()) {
      let cancelled = false;
      void fetchMarketGroups('', FAST_MARKETS_PAGE_SIZE, marketGroupSort)
        .then((payload) => {
          if (!cancelled) setMarketGroups(payload.items || []);
        })
        .catch(() => {
          // Keep the last group list visible when the event feed has a transient miss.
        });
      return () => {
        cancelled = true;
      };
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const [groupsResult, marketsResult] = await Promise.allSettled([
          fetchMarketGroups(marketQuery.trim(), SEARCH_MARKETS_PAGE_SIZE, marketGroupSort),
          fetchAllActiveMarkets(marketQuery.trim(), SEARCH_MARKETS_PAGE_SIZE),
        ]);
        if (!cancelled && groupsResult.status === 'fulfilled') setMarketGroups(groupsResult.value.items || []);
        if (!cancelled && marketsResult.status === 'fulfilled') setMarkets(marketsResult.value.items || []);
      } catch (loadError) {
        if (!cancelled) {
          setError((previous) => previous || (loadError instanceof Error ? loadError.message : 'Failed to refresh market search.'));
        }
      }
    }, 220);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [marketGroupSort, marketQuery]);

  useEffect(() => {
    if (!selectedMarketGroupId) {
      setSelectedMarketGroupDetail(null);
      return;
    }
    let cancelled = false;
    const eventId = selectedMarketGroupId;

    fetchMarketGroupDetail(eventId, 3000)
      .then((detailPayload) => {
        if (cancelled) return;
        setSelectedMarketGroupDetail(detailPayload);
        setSelectedMarketGroupOutcomeKey((current) => current || detailPayload.defaultOutcomeKey || null);
      })
      .catch(() => {
        if (!cancelled) setSelectedMarketGroupDetail(null);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedMarketGroupId]);

  useEffect(() => {
    if (!selectedMarketGroupId) {
      setSelectedMarketGroupChart(null);
      return;
    }
    let cancelled = false;
    const eventId = selectedMarketGroupId;
    const chartRange = selectedMarketGroupChartRange;
    setSelectedMarketGroupChart(null);

    fetchMarketGroupChart(eventId, chartRange, 3500)
      .then((chartPayload) => {
        if (!cancelled) setSelectedMarketGroupChart(chartPayload);
      })
      .catch(() => {
        if (!cancelled) setSelectedMarketGroupChart(null);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedMarketGroupChartRange, selectedMarketGroupId]);

  useEffect(() => {
    if (!selectedMarketId) return;
    let cancelled = false;
    const currentMarketId = selectedMarketId;
    const chartRange = selectedMarketGroupChartRange;

    fetchMarketChart(currentMarketId, chartRange, undefined, 3500)
      .then((chartPayload) => {
        if (cancelled) return;
        setBundle((previous) => {
          const base = previous || bundleCacheRef.current.get(currentMarketId) || emptyWorkspaceBundle();
          const next = mergeWorkspaceBundle(base, { ...emptyWorkspaceBundle(), chart: chartPayload });
          bundleCacheRef.current.set(currentMarketId, next);
          return next;
        });
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, [selectedMarketGroupChartRange, selectedMarketId]);

  useEffect(() => {
    if (!selectedMarketId) return;
    const currentMarketId = selectedMarketId;
    const requestSeq = ++bundleRequestSeqRef.current;
    let cancelled = false;
    const cachedBundle = bundleCacheRef.current.get(currentMarketId);
    const listMarket = markets.find((market) => market.id === currentMarketId)
      || bootstrapRef.current?.activeMarketsPreview?.find((market) => market.id === currentMarketId)
      || null;
    const initialBundle = cachedBundle || (listMarket ? optimisticBundleFromMarket(listMarket) : emptyWorkspaceBundle());
    setBundle(initialBundle);
    setBundleLoading(!cachedBundle && !listMarket);
    if (!cachedBundle) {
      bundleCacheRef.current.set(currentMarketId, initialBundle);
    }

    function applyLoadedBundle(loadedBundle: WorkspaceBundle) {
      if (cancelled || bundleRequestSeqRef.current !== requestSeq) return;
      if (!bundleMatchesMarket(loadedBundle, currentMarketId)) return;
      const loadedGroup = loadedBundle.group || null;
      const loadedEventId = loadedGroup?.eventId ?? loadedBundle.identity?.eventId ?? null;
      if (loadedGroup && loadedEventId != null) {
        const eventId = String(loadedEventId);
        selectedMarketGroupIdRef.current = eventId;
        setSelectedMarketGroupId(eventId);
        setSelectedMarketGroupDetail(loadedGroup);
        const nextOutcomeKey = loadedBundle.selectedOutcome?.outcomeKey
          || loadedBundle.identity?.selectedOutcomeKey
          || outcomeKeyForGroupMarket(loadedGroup, currentMarketId, loadedGroup.defaultOutcomeKey || null);
        if (nextOutcomeKey) {
          setSelectedMarketGroupOutcomeKey(nextOutcomeKey);
        }
      }
      setBundle((previous) => {
        const base = previous || bundleCacheRef.current.get(currentMarketId) || initialBundle;
        const next = mergeWorkspaceBundle(base, loadedBundle);
        bundleCacheRef.current.set(currentMarketId, next);
        return next;
      });
    }

    function refreshLobSnapshot() {
      fetchMarketLob(currentMarketId, 1800)
        .then((lob) => applyLoadedBundle({ ...emptyWorkspaceBundle(), lob }))
        .catch(() => undefined);
    }

    function refreshPriceSnapshot() {
      fetchMarketPrice(currentMarketId, 1800)
        .then((price) => applyLoadedBundle({ ...emptyWorkspaceBundle(), price }))
        .catch(() => undefined);
    }

    function refreshTradeSnapshot() {
      fetchMarketTrades(currentMarketId, 24, 2200)
        .then((trades) => applyLoadedBundle({ ...emptyWorkspaceBundle(), trades }))
        .catch(() => undefined);
    }

    function refreshContentSnapshot() {
      fetchMarketContent(currentMarketId, 20, 5000)
        .then((content) => applyLoadedBundle({ ...emptyWorkspaceBundle(), content }))
        .catch(() => undefined);
    }

    refreshPriceSnapshot();
    refreshTradeSnapshot();
    refreshLobSnapshot();
    refreshContentSnapshot();

    fetchWorkspaceBundle(currentMarketId)
      .then((loadedBundle) => applyLoadedBundle(loadedBundle))
      .catch((loadError) => {
        if (!cancelled && bundleRequestSeqRef.current === requestSeq && !listMarket && !cachedBundle) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load market.');
        }
      })
      .finally(() => {
        if (!cancelled && bundleRequestSeqRef.current === requestSeq) {
          setBundleLoading(false);
        }
      });
    const timer = window.setInterval(() => {
      if (cancelled || bundleRequestSeqRef.current !== requestSeq) return;
      fetchWorkspaceBundle(currentMarketId)
        .then((loadedBundle) => applyLoadedBundle(loadedBundle))
        .catch(() => undefined);
      refreshPriceSnapshot();
      refreshTradeSnapshot();
      refreshLobSnapshot();
      refreshContentSnapshot();
    }, 45000);

    const loadingTimer = window.setTimeout(() => {
      if (!cancelled && bundleRequestSeqRef.current === requestSeq) {
        setBundleLoading(false);
      }
    }, 4500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.clearTimeout(loadingTimer);
    };
  }, [selectedMarketId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setShowCommandPalette(true);
      }
      if (event.key === 'Escape') {
        setShowCommandPalette(false);
        setShowSettings(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 2200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const toggleLayer = (layerId: string) => {
    const target = layers.find((layer) => layer.id === layerId);
    if (target) setNotice(`${target.label} ${target.enabled ? 'hidden' : 'enabled'}`);
    setLayers((current) => current.map((layer) => (layer.id === layerId ? { ...layer, enabled: !layer.enabled } : layer)));
  };

  const togglePanel = (panelId: string) => {
    setActivePanelIds((current) => {
      if (current.includes(panelId)) return current.filter((candidate) => candidate !== panelId);
      return [...current, panelId];
    });
  };

  const moveWorkspacePanel = (draggedPanelId: string, targetPanelId: string, insertAfter: boolean) => {
    setActivePanelIds((current) => {
      const movablePanelIds = current.filter((panelId) => !MAP_BOTTOM_PANEL_IDS.includes(panelId));
      if (!movablePanelIds.includes(draggedPanelId) || !movablePanelIds.includes(targetPanelId)) return current;
      const nextMovablePanelIds = reorderPanelIds(movablePanelIds, draggedPanelId, targetPanelId, insertAfter);
      if (nextMovablePanelIds === movablePanelIds) return current;
      const movablePanelSet = new Set(movablePanelIds);
      let nextIndex = 0;
      return current.map((panelId) => (movablePanelSet.has(panelId) ? (nextMovablePanelIds[nextIndex++] || panelId) : panelId));
    });
  };

  const resizeWorkspacePanel = (panelId: string, patch: { rowSpan?: number; colSpan?: number }) => {
    setPanelLayoutPrefs((current) => {
      const entry = current[panelId] || {};
      return {
        ...current,
        [panelId]: {
          ...entry,
          ...patch,
        },
      };
    });
  };

  const resetWorkspacePanelLayout = (panelId: string) => {
    setPanelLayoutPrefs((current) => {
      if (!current[panelId]) return current;
      const next = { ...current };
      delete next[panelId];
      return next;
    });
  };

  const availableMarkets = useMemo(
    () => (markets.length ? markets : (bootstrap?.activeMarketsPreview || [])),
    [bootstrap?.activeMarketsPreview, markets],
  );

  const filteredMarkets = useMemo(() => {
    const query = commandQuery.trim().toLowerCase();
    if (!query) return availableMarkets;
    return availableMarkets.filter((market) => {
      const text = `${market.title} ${market.slug} ${market.category || ''} ${(market.tags || []).join(' ')}`.toLowerCase();
      return text.includes(query);
    });
  }, [availableMarkets, commandQuery]);

  const selectedMarket = useMemo<MarketSummary | null>(() => {
    if (selectedMarketGroupId && selectedMarketId == null) return null;
    if (bundle?.market && bundle.market.id === selectedMarketId) return bundle.market;
    const selectedListMarket = availableMarkets.find((market) => market.id === selectedMarketId);
    if (selectedListMarket) return selectedListMarket;
    if (bootstrap?.featuredMarket?.id === selectedMarketId) return bootstrap.featuredMarket;
    if (!selectedMarketGroupId && bootstrap?.featuredMarket && !isSuppressedDefaultMarket(bootstrap.featuredMarket)) {
      return bootstrap.featuredMarket;
    }
    return null;
  }, [availableMarkets, bootstrap?.featuredMarket, bundle?.market, selectedMarketGroupId, selectedMarketId]);

  const selectedMarketGroup = useMemo<MarketGroupItem | null>(() => {
    if (!selectedMarketGroupId) return null;
    return marketGroups.find((group) => String(group.eventId ?? '') === selectedMarketGroupId) || null;
  }, [marketGroups, selectedMarketGroupId]);

  const currentGlobalTrades = globalTrades.length ? globalTrades : (bootstrap?.globalTradesPreview || []);
  const currentGlobalOracle = globalOracle.length ? globalOracle : (bootstrap?.globalOraclePreview || []);
  const currentLatestContent = latestContent.length ? latestContent : (bootstrap?.latestContentPreview || []);
  const displayMarkets = filteredMarkets.length ? filteredMarkets : availableMarkets;
  const displayPanelIds = activePanelIds.length
    ? activePanelIds
    : sanitizePanelIds(bootstrap?.defaultWorkspace?.panels || []);
  const mapBottomPanelIds = displayPanelIds.filter((panelId) => MAP_BOTTOM_PANEL_IDS.includes(panelId));
  const sidePanelIds = displayPanelIds.filter((panelId) => !MAP_BOTTOM_PANEL_IDS.includes(panelId));
  const activeMarketsEntry = PANEL_REGISTRY['active-markets'];
  const oracleFeedEntry = PANEL_REGISTRY['oracle-feed'];
  const remainingSidePanelIds = sidePanelIds.filter((panelId) => !FOCUSED_STRIP_PANEL_IDS.has(panelId));

  const liveMetrics = [
    { label: 'ACTIVE MARKETS', value: displayMarkets.length || availableMarkets.length || 0 },
    { label: 'ORDERFILLED', value: currentGlobalTrades.length || 0 },
    { label: 'ORACLE', value: currentGlobalOracle.length || 0 },
    { label: 'INTEL', value: currentLatestContent.length || 0 },
  ];
  const visibleLayers = useMemo(() => {
    const query = layerQuery.trim().toLowerCase();
    if (!query) return layers;
    return layers.filter((layer) => `${layer.label} ${layer.hint || ''} ${layer.id}`.toLowerCase().includes(query));
  }, [layerQuery, layers]);
  const enabledLayerIds = useMemo(() => layers.filter((layer) => layer.enabled).map((layer) => layer.id), [layers]);
  const activeLayerCount = enabledLayerIds.length;
  const geoShockPayload = runtimeData['geo-sanctions-shock'] as RuntimeGeoSanctionsShockPayload | undefined;
  const ucdpLayerEnabled = enabledLayerIds.includes('ucdp');
  const ucdpMapEvents = useMemo(
    () => (ucdpLayerEnabled ? (geoShockPayload?.items || []).filter(hasGeoConflictCoordinates) : []),
    [geoShockPayload, ucdpLayerEnabled],
  );
  const mapVisibleEventCount = viewMode === '3d' ? globeStatus.markerVisible : ucdpMapEvents.length;
  const mapQualityLabel = viewMode === '3d'
    ? `${globeStatus.qualitySetting.toUpperCase()} · ${globeStatus.fps ? Math.round(globeStatus.fps) : '--'} FPS`
    : MAP_VIEW_OPTIONS.find((option) => option.value === viewMode)?.label || '2D Map';

  const runtimeValue = <T,>(panelId: string): T | null => (runtimeData[panelId] as T | undefined) || null;
  const runtimePayloadLoaded = (panelId: string) => runtimeData[panelId] !== undefined && runtimeData[panelId] !== null;
  const panelShouldShowLoading = (panelId: string) => {
    if (loading && !bootstrap) return true;
    if (panelLoadingIds.has(panelId) && !runtimePayloadLoaded(panelId)) return true;
    if (bundleLoading && selectedMarketId != null && MARKET_WORKSPACE_PANEL_IDS.has(panelId) && !bundle?.market && !selectedMarket) return true;
    return false;
  };

  const panelContext: PanelRenderContext = {
    bootstrap,
    markets: displayMarkets,
    marketGroups,
    marketGroupSort,
    setMarketGroupSort,
    selectedMarketId,
    setSelectedMarketId,
    focusMarketGroup,
    selectedMarketGroupId,
    selectedMarketGroup,
    selectedMarketGroupOutcomeKey,
    setSelectedMarketGroupOutcomeKey,
    selectedMarketGroupDetail,
    selectedMarketGroupChart,
    selectedMarketGroupChartRange,
    setSelectedMarketGroupChartRange,
    selectedMarket,
    selectedWeatherCityId,
    setSelectedWeatherCityId,
    bundle,
    health,
    globalTrades: currentGlobalTrades,
    globalOracle: currentGlobalOracle,
    latestContent: currentLatestContent,
    runtimeData,
    commodities: runtimeValue<RuntimeMarketGroup>('commodities-watch'),
    crypto: runtimeValue<RuntimeMarketGroup>('crypto-watch'),
    f1: runtimeValue<RuntimeF1Payload>('f1-trackside'),
    jin10: runtimeValue<RuntimeJin10Payload>('jin10-flash'),
    nba: runtimeValue<RuntimeNbaPayload>('nba-scoreboard'),
    nbaIntel: runtimeValue<RuntimeNbaIntelPayload>('nba-intel'),
    nbaMatchupPredictor: runtimeValue<RuntimeNbaMatchupPredictorPayload>('espn-matchup-predictor'),
    inflationNowcast: runtimeValue<RuntimeInflationNowcastPayload>('inflation-nowcast'),
    alphaSignals: runtimeValue<RuntimeSignalPayload>('alpha-signal'),
    whaleTrades: runtimeValue<RuntimeSignalPayload>('whale-tracker'),
    suspiciousTrades: runtimeValue<RuntimeSignalPayload>('suspicious-flow'),
  };

  useEffect(() => {
    const query = commandQuery.trim();
    if (!showCommandPalette || !query) {
      setCommandMarketHits([]);
      setCommandMarketSearchLoading(false);
      setCommandMarketSearchError('');
      return;
    }

    let cancelled = false;
    const timer = window.setTimeout(() => {
      setCommandMarketSearchLoading(true);
      setCommandMarketSearchError('');
      fetchMarketSearch(query, 50)
        .then((payload) => {
          if (!cancelled) {
            setCommandMarketHits(payload.items || []);
            setCommandMarketSearchError('');
          }
        })
        .catch(() => {
          if (!cancelled) {
            setCommandMarketHits([]);
            setCommandMarketSearchError('PostgreSQL market search is unavailable.');
          }
        })
        .finally(() => {
          if (!cancelled) setCommandMarketSearchLoading(false);
        });
    }, 180);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [commandQuery, showCommandPalette]);

  const commandResults = useMemo(() => {
    const query = commandQuery.trim().toLowerCase();
    const panelHits = PANEL_LIBRARY.filter((panel) => {
      const text = `${panel.title} ${panel.description} ${panel.eyebrow} ${panel.id} ${panel.size || 'default'}`.toLowerCase();
      return !query || text.includes(query);
    });
    const localMarketHits = availableMarkets.filter((market) => {
      const text = `${market.title} ${market.category || ''} ${market.slug}`.toLowerCase();
      return !query || text.includes(query);
    }).slice(0, 30);
    const marketHits = query && commandMarketHits.length ? commandMarketHits : localMarketHits;
    return { panelHits, marketHits };
  }, [availableMarkets, commandMarketHits, commandQuery]);

  const commandPanelStats = useMemo(() => ({
    enabled: PANEL_LIBRARY.filter((panel) => displayPanelIds.includes(panel.id)).length,
    matching: commandResults.panelHits.length,
    total: PANEL_LIBRARY.length,
  }), [commandResults.panelHits.length, displayPanelIds]);

  useEffect(() => {
    if (!showCommandPalette || commandTab !== 'markets') return;
    setCommandActiveMarketId((current) => {
      if (current != null && commandResults.marketHits.some((market) => market.id === current)) return current;
      return commandResults.marketHits[0]?.id ?? null;
    });
  }, [commandResults.marketHits, commandTab, showCommandPalette]);

  const commandActiveMarket = useMemo(() => (
    commandResults.marketHits.find((market) => market.id === commandActiveMarketId)
    || commandResults.marketHits[0]
    || null
  ), [commandActiveMarketId, commandResults.marketHits]);

  const handleCommandKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      setShowCommandPalette(false);
      return;
    }
    if (commandTab !== 'markets' || !commandResults.marketHits.length) return;
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' && event.key !== 'Enter') return;
    event.preventDefault();
    if (event.key === 'Enter') {
      if (commandActiveMarket) focusCommandMarket(commandActiveMarket);
      return;
    }
    const currentIndex = Math.max(0, commandResults.marketHits.findIndex((market) => market.id === commandActiveMarketId));
    const direction = event.key === 'ArrowDown' ? 1 : -1;
    const nextIndex = (currentIndex + direction + commandResults.marketHits.length) % commandResults.marketHits.length;
    setCommandActiveMarketId(commandResults.marketHits[nextIndex]?.id ?? null);
  };

  const resetWorkspace = () => {
    setRegion('global');
    setMapZoom(1);
    setViewMode('3d');
    const firstGroup = pickDefaultMarketGroup(marketGroups);
    if (firstGroup) {
      focusMarketGroup(firstGroup, firstGroup.defaultOutcomeKey || null, firstGroup.defaultMarketId ?? null);
    } else {
      const nextMarketId = pickDefaultMarketId(availableMarkets, bootstrap?.featuredMarket);
      selectedMarketGroupIdRef.current = null;
      selectedMarketIdRef.current = nextMarketId;
      setSelectedMarketGroupId(null);
      setSelectedMarketGroupOutcomeKey(null);
      setSelectedMarketId(nextMarketId);
    }
    setNotice('Workspace reset');
  };

  const cycleRegion = () => {
    const currentIndex = REGION_OPTIONS.findIndex((item) => item.value === region);
    const next = REGION_OPTIONS[(currentIndex + 1) % REGION_OPTIONS.length];
    if (next) setRegion(next.value);
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setNotice('Link copied');
    } catch {
      setNotice('Copy failed');
    }
  };

  const focusCommandMarket = (market: MarketListItem) => {
    selectedMarketGroupIdRef.current = null;
    selectedMarketIdRef.current = market.id;
    setWorkspaceMode('world');
    setSelectedMarketGroupId(null);
    setSelectedMarketGroupOutcomeKey(null);
    setSelectedMarketId(market.id);
    setShowCommandPalette(false);
    setNotice(`Focused market: ${market.title.slice(0, 72)}${market.title.length > 72 ? '...' : ''}`);
    window.setTimeout(() => {
      document.querySelector('.wm-focused-market-row')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }, 0);
  };

  const changeViewMode = (nextMode: MapViewMode) => {
    setViewMode(nextMode);
    setMapZoom((current) => clampMapZoom(nextMode === '3d' ? current : Math.min(2, current)));
    const label = MAP_VIEW_OPTIONS.find((option) => option.value === nextMode)?.label || nextMode;
    setNotice(`${label} enabled`);
  };

  const loadWeatherMap = async (force = false) => {
    const panelPayload = runtimeData['global-temperature-monitor'] as RuntimeGlobalWeatherMapPayload | undefined;
    if (!force && panelPayload?.items?.length) {
      setWeatherMapPayload(panelPayload);
      setSelectedWeatherCityId((current) => current || String(panelPayload.items?.[0]?.cityId || ''));
      return;
    }
    setWeatherMapLoading(true);
    setWeatherMapError(null);
    try {
      const payload = await fetchRuntimeGlobalWeatherMap(60);
      setWeatherMapPayload(payload);
      setRuntimeData((current) => mergeRuntimeData(current, { 'global-temperature-monitor': payload }));
      setSelectedWeatherCityId((current) => current || String(payload.items?.[0]?.cityId || ''));
    } catch (loadError) {
      setWeatherMapError(loadError instanceof Error ? loadError.message : 'Failed to load weather map.');
    } finally {
      setWeatherMapLoading(false);
    }
  };

  useEffect(() => {
    if (viewMode !== '3d') {
      void loadWeatherMap(false);
    }
  }, [viewMode]);

  const zoomIn = () => setMapZoom((current) => clampMapZoom(current + 1));
  const zoomOut = () => setMapZoom((current) => clampMapZoom(current - 1));

  return (
    <div className="wm-shell">
      <div className="wm-promo">
        <span className="wm-pro-badge">PRO</span>
        <span className="wm-promo-copy">PolyMonitor Pro is coming - sharper Polymarket signal, less noise, AI briefs for flow, oracle risk, and macro context.</span>
        <button className="wm-promo-cta" type="button">Reserve your spot</button>
      </div>

      <header className="wm-toolbar">
        <div className="wm-toolbar-left">
          <div className="wm-nav-cluster">
            <button
              className={`wm-workspace-option ${workspaceMode === 'world' ? 'active' : ''}`}
              type="button"
              onClick={() => {
                setWorkspaceMode('world');
                resetWorkspace();
              }}
              title="World workspace"
            >
              <span className="wm-workspace-icon">◎</span>
              <span className="wm-workspace-label">World</span>
            </button>
            <button
              className={`wm-workspace-option wm-workspace-worldcup ${workspaceMode === 'worldcup' ? 'active' : ''}`}
              type="button"
              onClick={() => setWorkspaceMode('worldcup')}
              title="World Cup"
            >
              <span className="wm-workspace-icon">⚽</span>
              <span className="wm-workspace-label">World Cup</span>
            </button>
            <button className="wm-nav-icon" type="button" onClick={() => setShowCommandPalette(true)} title="Command palette">⌨</button>
            <button className="wm-nav-icon" type="button" onClick={() => setShowPanelLibrary((current) => !current)} title="Toggle panel library">◫</button>
            <button className="wm-nav-icon" type="button" onClick={() => setShowSettings(true)} title="Open settings">⚒</button>
            <button className="wm-nav-icon" type="button" onClick={cycleRegion} title="Cycle region">◌</button>
          </div>
          <div className="wm-brand">POLYDATA MONITOR <span>{APP_VERSION}</span></div>
          <div className="wm-live-dot">Live</div>
          <button className="wm-select-pill" type="button" onClick={cycleRegion}>
            {REGION_OPTIONS.find((item) => item.value === region)?.label || 'Global'} ▾
          </button>
          <div className="wm-defcon-pill">POLYMARKET <span>LIVE</span></div>
        </div>
        <nav className="wm-site-nav" aria-label="polyData resources">
          {SITE_NAV_LINKS.map((link) => (
            <a
              key={link.label}
              className={link.label === 'Quant' ? 'wm-site-nav-quant' : undefined}
              href={link.href}
              target={link.external ? '_blank' : undefined}
              rel={link.external ? 'noopener noreferrer' : undefined}
            >
              {link.label}
            </a>
          ))}
        </nav>
        <div className="wm-toolbar-right">
          <button className="wm-counter-pill" type="button">{liveMetrics[1]?.value || 0}</button>
          <button className="wm-tool-button" type="button" onClick={() => setShowCommandPalette(true)}>⌘K Search</button>
          <button className="wm-tool-button" type="button" onClick={() => void copyLink()}>Copy Link</button>
          <button className="wm-tool-icon" type="button" onClick={resetWorkspace}>⌂</button>
          <button className="wm-tool-icon" type="button" onClick={() => setShowSettings(true)}>⚙</button>
        </div>
      </header>

      {workspaceMode === 'worldcup' ? (
        <WorldCupWorkspace
          now={now}
          marketGroups={marketGroups}
          latestContent={currentLatestContent}
          weatherPayload={(runtimeData['global-temperature-monitor'] as RuntimeGlobalWeatherMapPayload | undefined) || null}
          geoShockPayload={(runtimeData['geo-sanctions-shock'] as RuntimeGeoSanctionsShockPayload | undefined) || null}
        />
      ) : (
      <main className="wm-dashboard">
        <div className="wm-main-content">
        <section className="wm-map-section">
          <div className="wm-map-header">
            <div className="wm-map-heading">
              <span className="wm-map-kicker">Live Odds & Oracle Monitor</span>
              <div className="wm-map-title">Polymarket Signal Atlas</div>
            </div>
            <div className="wm-map-status-strip" aria-label="Global map status">
              <span className="wm-status-chip">POLYDATA MONITOR · LIVE</span>
              <LiveUtcClock />
              <span className="wm-map-status-metric">Events <b>{ucdpMapEvents.length}</b></span>
              <span className="wm-map-status-metric">Visible <b>{mapVisibleEventCount}</b></span>
              <span className="wm-map-status-metric">Quality <b>{mapQualityLabel}</b></span>
            </div>
            <div className="wm-map-view-toggle" role="tablist" aria-label="Map view mode">
              {MAP_VIEW_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="tab"
                  aria-selected={viewMode === option.value}
                  className={viewMode === option.value ? 'active' : ''}
                  onClick={() => changeViewMode(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div className="wm-map-stage">
            <div className={`wm-globe-area ${viewMode !== '3d' ? 'wm-globe-area-flat' : ''}`}>
              <aside className={`wm-layer-sidebar ${showPanelLibrary ? '' : 'collapsed'}`}>
                <div className="wm-toggle-header">
                  <span>Layers</span>
                  <button type="button" className="wm-toggle-collapse" onClick={() => setShowPanelLibrary(false)}>▼</button>
                </div>
                <input
                  className="wm-layer-search"
                  value={layerQuery}
                  onInput={(event) => setLayerQuery((event.currentTarget as HTMLInputElement).value)}
                  placeholder="Search layers..."
                />

                <div className="wm-layer-list">
                  {visibleLayers.length ? visibleLayers.map((layer) => (
                    <label
                      key={layer.id}
                      className={`wm-layer-row ${layer.enabled ? 'enabled' : ''}`}
                      title={`${layer.enabled ? 'Hide' : 'Show'} ${layer.label}`}
                    >
                      <input
                        type="checkbox"
                        checked={layer.enabled}
                        onChange={() => toggleLayer(layer.id)}
                        aria-label={`${layer.enabled ? 'Hide' : 'Show'} ${layer.label}`}
                      />
                      <span className="wm-layer-icon">{layer.icon}</span>
                      <span>{layer.label}</span>
                      {layer.hint ? <em className="wm-layer-hint">{layer.hint}</em> : null}
                    </label>
                  )) : (
                    <div className="wm-layer-empty">No matching layers</div>
                  )}
                </div>

                <div className="wm-sidebar-footer">{activeLayerCount}/{layers.length} layers active</div>
              </aside>

              <div className="wm-globe-hero">
                {viewMode === '3d' ? (
                  <WorldGlobe
                    markets={displayMarkets}
                    selectedMarket={selectedMarket}
                    recentTrades={currentGlobalTrades}
                    recentOracle={currentGlobalOracle}
                    contentItems={currentLatestContent}
                    ucdpEvents={ucdpMapEvents}
                    region={region}
                    zoomLevel={mapZoom}
                    enabledLayerIds={enabledLayerIds}
                    onMetricsChange={setGlobeStatus}
                  />
                ) : (
                  <WeatherInlineMap
                    payload={weatherMapPayload || (runtimeData['global-temperature-monitor'] as RuntimeGlobalWeatherMapPayload | undefined) || null}
                    ucdpEvents={ucdpMapEvents}
                    loading={weatherMapLoading}
                    error={weatherMapError}
                    selectedCityId={selectedWeatherCityId}
                    onSelectCity={setSelectedWeatherCityId}
                    onRefresh={() => void loadWeatherMap(true)}
                  />
                )}

              </div>

              <div className="wm-map-controls">
                <button type="button" className="wm-side-beta" onClick={() => setShowSettings(true)}>BETA</button>
                <button type="button" onClick={zoomIn}>＋</button>
                <button type="button" onClick={zoomOut}>－</button>
                <button type="button" onClick={resetWorkspace}>⌂</button>
              </div>

              {loading ? <div className="wm-banner">Bootstrapping monitor...</div> : null}
              {bundleLoading ? <div className="wm-banner secondary">Switching market workspace...</div> : null}
              {error ? <div className="wm-banner error">{error}</div> : null}
              {notice ? <div className="wm-banner notice">{notice}</div> : null}
            </div>
          </div>

          <div className="wm-map-bottom-grid">
            {mapBottomPanelIds.map((panelId) => {
              const entry = PANEL_REGISTRY[panelId];
              if (!entry) return null;
              const sizeClass = entry.size ? `size-${entry.size}` : '';
              return (
                <div className={`wm-panel-slot ${sizeClass}`.trim()} key={`bottom-${panelId}`}>
                  {entry.render(panelContext)}
                  {panelShouldShowLoading(panelId) ? (
                    <div className="wm-panel-slot-loading">
                      <PanelLoading detail="正在同步这个 panel 的实时数据" />
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>

        <section className="wm-focused-market-row">
          {activeMarketsEntry ? (
            <PanelWorkspaceSlot
              panelId="active-markets"
              size={activeMarketsEntry.size}
              layoutPrefs={panelLayoutPrefs}
              className="wm-focused-market-list"
              layoutManaged={false}
              resizeEnabled={false}
              loading={panelShouldShowLoading('active-markets')}
              onMovePanel={moveWorkspacePanel}
              onResizePanel={resizeWorkspacePanel}
              onResetPanelLayout={resetWorkspacePanelLayout}
            >
              {activeMarketsEntry.render(panelContext)}
            </PanelWorkspaceSlot>
          ) : null}
          <div className="wm-focused-market-right">
            <FocusedMarketStrip
              {...panelContext}
              renderPanelSlot={(panelId, className, panel) => {
                const entry = PANEL_REGISTRY[panelId];
                return (
                  <PanelWorkspaceSlot
                    key={panelId}
                    panelId={panelId}
                    size={entry?.size}
                    layoutPrefs={panelLayoutPrefs}
                    className={className}
                    layoutManaged={false}
                    resizeEnabled={false}
                    loading={panelShouldShowLoading(panelId)}
                    onMovePanel={moveWorkspacePanel}
                    onResizePanel={resizeWorkspacePanel}
                    onResetPanelLayout={resetWorkspacePanelLayout}
                  >
                    {panel}
                  </PanelWorkspaceSlot>
                );
              }}
            />
          </div>
          {oracleFeedEntry ? (
            <PanelWorkspaceSlot
              panelId="oracle-feed"
              size={oracleFeedEntry.size}
              layoutPrefs={panelLayoutPrefs}
              className="wm-focused-oracle-feed"
              layoutManaged={false}
              resizeEnabled={false}
              loading={panelShouldShowLoading('oracle-feed')}
              onMovePanel={moveWorkspacePanel}
              onResizePanel={resizeWorkspacePanel}
              onResetPanelLayout={resetWorkspacePanelLayout}
            >
              {oracleFeedEntry.render(panelContext)}
            </PanelWorkspaceSlot>
          ) : null}
        </section>

        <section className="wm-panels-grid">
          {remainingSidePanelIds.map((panelId) => {
            const entry = PANEL_REGISTRY[panelId];
            if (!entry) return null;
            return (
              <PanelWorkspaceSlot
                key={panelId}
                panelId={panelId}
                size={entry.size}
                layoutPrefs={panelLayoutPrefs}
                loading={panelShouldShowLoading(panelId)}
                onMovePanel={moveWorkspacePanel}
                onResizePanel={resizeWorkspacePanel}
                onResetPanelLayout={resetWorkspacePanelLayout}
              >
                {entry.render(panelContext)}
              </PanelWorkspaceSlot>
            );
          })}
        </section>
        </div>
      </main>
      )}

      {showCommandPalette ? (
        <div className="wm-modal-backdrop" onClick={() => setShowCommandPalette(false)}>
          <div className="wm-modal wm-command-modal" onClick={(event) => event.stopPropagation()} onKeyDown={handleCommandKeyDown}>
            <div className="wm-command-header">
              <div>
                <span>Market Command Center</span>
                <strong>Search Markets</strong>
              </div>
              <div className="wm-command-source">
                <span>PostgreSQL</span>
                <span>ClickHouse TX</span>
                <span>Live Index</span>
              </div>
            </div>
            <div className="wm-command-searchbar">
              <span aria-hidden="true">⌕</span>
              <input
                autoFocus
                className="wm-command-input"
                value={commandQuery}
                onInput={(event) => setCommandQuery((event.currentTarget as HTMLInputElement).value)}
                placeholder="Search markets, tickers, categories, or panels..."
              />
              <kbd>⌘K</kbd>
            </div>
            <div className="wm-command-tabs" role="tablist" aria-label="Command palette sections">
              <button type="button" className={commandTab === 'markets' ? 'active' : ''} onClick={() => setCommandTab('markets')}>Markets <span>{commandResults.marketHits.length}</span></button>
              <button type="button" className={commandTab === 'panels' ? 'active' : ''} onClick={() => setCommandTab('panels')}>Panels <span>{commandPanelStats.matching}/{commandPanelStats.total}</span></button>
              <button type="button" className={commandTab === 'commands' ? 'active' : ''} onClick={() => setCommandTab('commands')}>Commands <span>3</span></button>
            </div>
            <div className="wm-command-body">
              {commandTab === 'markets' ? (
                <div className="wm-command-market-layout">
                  <div className="wm-command-group wm-command-market-list">
                    <div className="wm-command-list-head">
                      <span>Market</span>
                      <span>YES</span>
                      <span>VOL</span>
                      <span>TX</span>
                      <span>AGE</span>
                    </div>
                    {commandMarketSearchLoading ? <div className="wm-command-empty">Searching PostgreSQL market index...</div> : null}
                    {!commandMarketSearchLoading && commandMarketSearchError ? (
                      <div className="wm-command-empty error">{commandMarketSearchError}</div>
                    ) : null}
                    {commandResults.marketHits.map((market) => {
                      const active = commandActiveMarket?.id === market.id;
                      return (
                        <button
                          key={market.id}
                          type="button"
                          className={`wm-command-result wm-command-market-result ${active ? 'active' : ''}`}
                          onMouseEnter={() => setCommandActiveMarketId(market.id)}
                          onFocus={() => setCommandActiveMarketId(market.id)}
                          onClick={() => focusCommandMarket(market)}
                        >
                          <div className="wm-command-result-main">
                            <strong>{market.title}</strong>
                            <span>
                              <i className={`wm-command-status ${commandMarketStatusClass(market)}`}>{commandMarketStatus(market)}</i>
                              <em>{market.category || 'Uncategorized'}</em>
                            </span>
                          </div>
                          <b>{formatPercent(market.latestPrice)}</b>
                          <b>{formatCurrencyCompact(market.volume24h)}</b>
                          <b>{formatCompact(market.tradeCount24h)}</b>
                          <b>{commandMarketFreshness(market)}</b>
                        </button>
                      );
                    })}
                    {!commandMarketSearchLoading && !commandMarketSearchError && commandQuery.trim() && !commandResults.marketHits.length ? (
                      <div className="wm-command-empty">No matching markets in PostgreSQL.</div>
                    ) : null}
                  </div>
                  <aside className="wm-command-preview" aria-label="Selected market preview">
                    {commandActiveMarket ? (
                      <>
                        <div className="wm-command-preview-top">
                          <span className={`wm-command-status ${commandMarketStatusClass(commandActiveMarket)}`}>{commandMarketStatus(commandActiveMarket)}</span>
                          <em>{commandActiveMarket.category || 'Market'}</em>
                        </div>
                        <strong>{commandActiveMarket.title}</strong>
                        <div className="wm-command-preview-price">
                          <span><em>YES</em><b>{formatPercent(commandActiveMarket.latestPrice)}</b></span>
                          <span><em>24H VOL</em><b>{formatCurrencyCompact(commandActiveMarket.volume24h)}</b></span>
                          <span><em>24H TX</em><b>{formatCompact(commandActiveMarket.tradeCount24h)}</b></span>
                          <span><em>LAST TRADE</em><b>{commandMarketFreshness(commandActiveMarket)}</b></span>
                        </div>
                        <div className="wm-command-preview-meta">
                          <span><em>Market ID</em><b>{commandActiveMarket.id}</b></span>
                          <span><em>Outcomes</em><b>{commandActiveMarket.outcomeCount || 2}</b></span>
                          <span><em>Closes</em><b>{formatDate(commandActiveMarket.endDate)}</b></span>
                        </div>
                        <div className="wm-command-preview-tags">
                          {(commandActiveMarket.tags || []).slice(0, 5).map((tag) => <span key={tag}>{tag}</span>)}
                        </div>
                        <button type="button" className="wm-command-primary" onClick={() => focusCommandMarket(commandActiveMarket)}>Open Market Workspace</button>
                      </>
                    ) : (
                      <div className="wm-command-empty">Search a market to preview live pricing, status, and flow.</div>
                    )}
                  </aside>
                </div>
              ) : null}
              {commandTab === 'panels' ? (
                <div className="wm-command-panel-section">
                  <div className="wm-command-panel-summary">
                    <span>Showing <b>{commandPanelStats.matching}</b> of <b>{commandPanelStats.total}</b> panels</span>
                    <span>Enabled <b>{commandPanelStats.enabled}</b></span>
                    {commandQuery.trim() ? <em>Filtered by "{commandQuery.trim()}"</em> : <em>Full panel library</em>}
                  </div>
                  <div className="wm-command-panel-grid">
                    {commandResults.panelHits.map((panel) => (
                      <button
                        key={panel.id}
                        type="button"
                        className={`wm-command-result wm-command-panel-result ${displayPanelIds.includes(panel.id) ? 'enabled' : ''}`}
                        onClick={() => {
                          if (!displayPanelIds.includes(panel.id)) togglePanel(panel.id);
                          setShowCommandPalette(false);
                        }}
                      >
                        <div className="wm-command-panel-main">
                          <strong>{panel.title}</strong>
                          <small>{panel.id}</small>
                        </div>
                        <span>{panel.description}</span>
                        <div className="wm-command-panel-meta">
                          <i>{panel.eyebrow || 'panel'}</i>
                          <i>{panel.size || 'default'}</i>
                          <em>{displayPanelIds.includes(panel.id) ? 'Enabled' : 'Add panel'}</em>
                        </div>
                      </button>
                    ))}
                    {!commandResults.panelHits.length ? (
                      <div className="wm-command-empty">No panels match the current query.</div>
                    ) : null}
                  </div>
                </div>
              ) : null}
              {commandTab === 'commands' ? (
                <div className="wm-command-panel-grid wm-command-actions-grid">
                  <button type="button" className="wm-command-result wm-command-panel-result" onClick={() => {
                    resetWorkspace();
                    setShowCommandPalette(false);
                  }}>
                    <strong>Reset Workspace</strong>
                    <span>Return to the default market workspace and global region.</span>
                    <em>Run</em>
                  </button>
                  <button type="button" className="wm-command-result wm-command-panel-result" onClick={() => {
                    setShowCommandPalette(false);
                    setShowSettings(true);
                  }}>
                    <strong>Workspace Settings</strong>
                    <span>Open panel, region, and monitor preferences.</span>
                    <em>Open</em>
                  </button>
                  <button type="button" className="wm-command-result wm-command-panel-result" onClick={() => {
                    void copyLink();
                    setShowCommandPalette(false);
                  }}>
                    <strong>Copy Link</strong>
                    <span>Copy the current monitor URL.</span>
                    <em>Copy</em>
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {showSettings ? (
        <div className="wm-modal-backdrop" onClick={() => setShowSettings(false)}>
          <div className="wm-modal wm-settings-modal" onClick={(event) => event.stopPropagation()}>
            <div className="wm-modal-title">Workspace Settings</div>
            <label className="wm-settings-row">
              <span>Region</span>
              <select value={region} onChange={(event) => setRegion((event.currentTarget as HTMLSelectElement).value as RegionKey)}>
                {REGION_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="wm-settings-row">
              <span>Map Mode</span>
              <select value={viewMode} onChange={(event) => setViewMode((event.currentTarget as HTMLSelectElement).value as MapViewMode)}>
                {MAP_VIEW_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="wm-settings-row">
              <span>Map Zoom</span>
              <input type="range" min="1" max="4" step="1" value={String(mapZoom)} onInput={(event) => setMapZoom(clampMapZoom((event.currentTarget as HTMLInputElement).value))} />
            </label>
            <div className="wm-settings-actions">
              <button type="button" className="wm-settings-btn" onClick={() => setActivePanelIds(sanitizePanelIds(PANEL_LIBRARY.map((panel) => panel.id)))}>Enable All Panels</button>
              <button type="button" className="wm-settings-btn" onClick={() => setActivePanelIds(sanitizePanelIds(bootstrap?.defaultWorkspace?.panels || []))}>Restore Default Panels</button>
              <button type="button" className="wm-settings-btn primary" onClick={() => { resetWorkspace(); setShowSettings(false); }}>Reset Workspace</button>
            </div>
          </div>
        </div>
      ) : null}

    </div>
  );
}

export function App() {
  const pathname = typeof window === 'undefined' ? '/' : window.location.pathname;
  return pathname === '/quant' || pathname.startsWith('/quant/') ? <QuantWorkspace /> : <WorldMonitorApp />;
}
