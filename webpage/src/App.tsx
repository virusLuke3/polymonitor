import { useDashboardData } from '@/features/workspace/useDashboardData';
import { useMarketCatalog, useMarketSearch } from '@/features/market-focus/useMarketCatalog';
import {
  useWorkspacePreferences,
  useWorkspaceSync,
  DEFAULT_MAP_VIEW_MODE,
  type MapViewMode,
} from '@/features/workspace/useWorkspacePreferences';
import { useMarketFocus } from '@/features/market-focus/useMarketFocus';
import { isSuppressedDefaultMarket, findGroupForMarketId, outcomeKeyForGroupMarket } from '@/features/market-focus/marketBundle';
import { lazy, Suspense } from 'preact/compat';
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { AppShell } from '@/components/AppShell';
import { FocusedMarketStrip } from '@/components/FocusedMarketStrip';
import { PanelLoading } from '@/components/Panel';
import {
  PanelWorkspaceSlot,
} from '@/components/PanelWorkspaceSlot';
import { WorldGlobe, type WorldGlobeStatusMetrics } from '@/components/WorldGlobe';
import { PANEL_LIBRARY, PANEL_REGISTRY, RUNTIME_PANEL_MODULES } from '@/panels/registry';
import { usePanelRuntime } from '@/panels/usePanelRuntime';
import { useI18n, type MessageKey } from '@/services/i18n';
import { specialistPanelMeta } from '@/services/specialist-i18n';
import {
  MapStatus, useWorldEventMapController, readWorldEventMapSeed, WorldEventMapView, clampMapZoom, type LayerToggle,
  MapToolbar,
  LayerPanel,
  worldEventLayerById,
  type WorldEventRegion,
} from '@/features/world-event-map';
import type {
  MarketListItem,
  MarketGroupItem,
  MarketSummary,
  PanelRenderContext,
} from '@/types';

type RegionKey = WorldEventRegion;
type CommandPaletteTab = 'markets' | 'panels' | 'commands';
const MarketWorkspace = lazy(() => import('@/workspaces/market/MarketWorkspace').then((module) => ({ default: module.MarketWorkspace })));
const DataQualityWorkspace = lazy(() => import('@/workspaces/data-quality/DataQualityWorkspace').then((module) => ({ default: module.DataQualityWorkspace })));
const LoginWorkspace = lazy(() => import('@/workspaces/auth/AuthWorkspace').then((module) => ({ default: module.LoginWorkspace })));
const AccountWorkspace = lazy(() => import('@/workspaces/auth/AuthWorkspace').then((module) => ({ default: module.AccountWorkspace })));
const WatchlistWorkspace = lazy(() => import('@/workspaces/watchlist/WatchlistWorkspace').then((module) => ({ default: module.WatchlistWorkspace })));
const BriefingManagerWorkspace = lazy(() => import('@/workspaces/briefing/BriefingWorkspace').then((module) => ({ default: module.BriefingManagerWorkspace })));
const PublicBriefingWorkspace = lazy(() => import('@/workspaces/briefing/BriefingWorkspace').then((module) => ({ default: module.PublicBriefingWorkspace })));
const DeveloperWorkspace = lazy(() => import('@/workspaces/developers/DeveloperWorkspace').then((module) => ({ default: module.DeveloperWorkspace })));
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
  { value: '2d', label: '2D Map' },
  { value: '3d', label: '3D Globe' },
];
const REGION_MESSAGE_KEYS: Record<RegionKey, MessageKey> = {
  global: 'region.global',
  america: 'region.america',
  mena: 'region.mena',
  eu: 'region.eu',
  asia: 'region.asia',
  latam: 'region.latam',
  africa: 'region.africa',
  oceania: 'region.oceania',
};
const MAP_VIEW_MESSAGE_KEYS: Record<MapViewMode, MessageKey> = {
  '2d': 'map.2d',
  '3d': 'map.3d',
};
const CORE_PANEL_META_KEYS: Record<string, { title: MessageKey; description: MessageKey }> = {
  'active-markets': { title: 'panelMeta.activeMarkets.title', description: 'panelMeta.activeMarkets.description' },
  'market-summary': { title: 'panelMeta.marketSummary.title', description: 'panelMeta.marketSummary.description' },
  'featured-market': { title: 'panelMeta.marketContext.title', description: 'panelMeta.marketContext.description' },
  'price-chart': { title: 'panelMeta.priceSurface.title', description: 'panelMeta.priceSurface.description' },
  'oracle-feed': { title: 'panelMeta.oracleFeed.title', description: 'panelMeta.oracleFeed.description' },
  'related-news': { title: 'panelMeta.relatedIntel.title', description: 'panelMeta.relatedIntel.description' },
};

function localizedLayerLabel(layer: LayerToggle, t: (key: MessageKey, params?: Record<string, string | number>) => string) {
  const messageKey = worldEventLayerById(layer.id)?.messageKey as MessageKey | undefined;
  return messageKey ? t(messageKey) : layer.label;
}

function localizedPanelMeta(
  panel: (typeof PANEL_LIBRARY)[number],
  t: (key: MessageKey, params?: Record<string, string | number>) => string,
) {
  const keys = CORE_PANEL_META_KEYS[panel.id];
  return keys
    ? { title: t(keys.title), description: t(keys.description) }
    : specialistPanelMeta(panel.id, panel.title, panel.description, t);
}

const FOCUSED_STRIP_PANEL_IDS = new Set(['active-markets', 'price-chart', 'lob-depth', 'global-orderfilled', 'oracle-feed']);
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

function WorldMonitorApp() {
  const { locale, setLocale, t, formatDateTime, formatNumber, formatPercent, formatRelativeTime } = useI18n();
  const workspace = useWorkspacePreferences();
  const {
    layoutWidth, enableAllPanels, restorePanels, activePanelIds, panelLayoutPrefs,
    viewMode, setViewMode, showPanelLibrary, setShowPanelLibrary,
    marketGroupSort, setMarketGroupSort, togglePanel, moveWorkspacePanel,
    resizeWorkspacePanel, resetWorkspacePanelLayout,
  } = workspace;
  const runtime = usePanelRuntime({
    panels: RUNTIME_PANEL_MODULES, activePanelIds, initialData: readWorldEventMapSeed, waitForVisibility: true,
  });
  const { runtimeData, getStatus: getPanelRuntimeStatus, refreshPanels } = runtime;
  const { bootstrap, health, globalTrades, globalOracle, latestContent, loading, error } = useDashboardData(workspace, runtime);
  const { markets, marketGroups, marketCatalogRefreshing, marketCatalogError, refreshMarketCatalog, catalogLoaded } = useMarketCatalog(bootstrap, !loading);
  const { selectedMarketId, setSelectedMarketId, resetMarketSelection, selectedMarketGroupId, selectedMarketGroupOutcomeKey, setSelectedMarketGroupOutcomeKey,
    selectedMarketGroupDetail, selectedMarketGroupChart, selectedMarketGroupChartRange, setSelectedMarketGroupChartRange,
    bundle, bundleLoading, focusMarketGroup, prefetchMarketFocus, error: focusError } = useMarketFocus({ bootstrap, markets, marketGroups, catalogLoaded });
  const { worldEventMap, setMapRendererKind, layers, region, mapZoom, setRegion, setMapZoom, enabledLayerIds,
    ucdpRawMapEvents, worldEventMapEvents, mapSourceStatuses } = useWorldEventMapController(runtime, viewMode === '2d');
  const { workspaceSyncStatus, workspaceSyncUpdatedAt, retryWorkspaceSync } = useWorkspaceSync(workspace, { region, mapZoom, setRegion, setMapZoom });
  const [commandQuery, setCommandQuery] = useState('');
  const [commandTab, setCommandTab] = useState<CommandPaletteTab>('markets');
  const [commandActiveMarketId, setCommandActiveMarketId] = useState<number | null>(null);
  const [globeStatus, setGlobeStatus] = useState<WorldGlobeStatusMetrics>({
    fps: 0,
    markerTotal: 0,
    markerVisible: 0,
    qualitySetting: 'auto',
    qualityLevel: 'high',
    dpr: 1,
  });
  const [showCommandPalette, setShowCommandPalette] = useState(false);
  const { hits: commandMarketHits, loading: commandMarketSearchLoading, unavailable: commandSearchUnavailable } = useMarketSearch(commandQuery, showCommandPalette);
  const commandMarketSearchError = commandSearchUnavailable ? t('atlas.commandSearchUnavailable') : '';
  const [showSettings, setShowSettings] = useState(false);
  const [manualCopyLink, setManualCopyLink] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedWeatherCityId, setSelectedWeatherCityId] = useState<string | null>(null);
  const manualCopyInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setShowCommandPalette(true);
      }
      if (event.key === 'Escape') {
        setShowCommandPalette(false);
        setShowSettings(false);
        setManualCopyLink(null);
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
    if (!target?.isExecutable || target.availability === 'unavailable') {
      setNotice(target?.availabilityReason || 'This layer is not available in the current runtime.');
      return;
    }
    if (target) {
      const label = localizedLayerLabel(target, t);
      setNotice(t(target.enabled ? 'atlas.hideLayer' : 'atlas.showLayer', { layer: label }));
    }
    worldEventMap.toggleLayer(layerId);
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
  const activeMarketsEntry = PANEL_REGISTRY['active-markets'];
  const oracleFeedEntry = PANEL_REGISTRY['oracle-feed'];
  const remainingSidePanelIds = activePanelIds.filter((panelId) => !FOCUSED_STRIP_PANEL_IDS.has(panelId));

  const liveMetrics = [
    { label: 'ACTIVE MARKETS', value: displayMarkets.length || availableMarkets.length || 0 },
    { label: 'ORDERFILLED', value: currentGlobalTrades.length || 0 },
    { label: 'ORACLE', value: currentGlobalOracle.length || 0 },
    { label: 'INTEL', value: currentLatestContent.length || 0 },
  ];
  const mapVisibleEventCount = viewMode === '3d' ? globeStatus.markerVisible : worldEventMapEvents.length;
  const mapQualityLabel = viewMode === '3d'
    ? `${globeStatus.qualitySetting.toUpperCase()} · ${globeStatus.fps ? Math.round(globeStatus.fps) : '--'} FPS`
    : `${t(MAP_VIEW_MESSAGE_KEYS[viewMode])} · Z${mapZoom.toFixed(2)}`;

  const runtimePayloadLoaded = (panelId: string) => runtime.getData(panelId) !== undefined && runtime.getData(panelId) !== null;
  const panelShouldShowLoading = (panelId: string) => {
    if (loading && !bootstrap) return true;
    if (getPanelRuntimeStatus(panelId).phase === 'loading' && !runtimePayloadLoaded(panelId)) return true;
    return false;
  };
  const retryRuntimePanel = (panelId: string) => {
    const panel = PANEL_REGISTRY[panelId];
    if (panel?.fetchData || panel?.dataSourceId) {
      void refreshPanels([panel], { panelIds: [panelId], reason: 'manual', force: true });
    }
  };

  const panelContext: PanelRenderContext = {
    bootstrap,
    markets: displayMarkets,
    marketGroups,
    marketGroupSort,
    setMarketGroupSort,
    marketCatalogRefreshing,
    marketCatalogError,
    refreshMarketCatalog,
    selectedMarketId,
    setSelectedMarketId,
    prefetchMarketFocus,
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
  };

  const commandResults = useMemo(() => {
    const query = commandQuery.trim().toLowerCase();
    const panelHits = PANEL_LIBRARY.filter((panel) => {
      const meta = localizedPanelMeta(panel, t);
      const text = `${meta.title} ${meta.description} ${panel.title} ${panel.description} ${panel.eyebrow} ${panel.id} ${panel.size || 'default'}`.toLowerCase();
      return !query || text.includes(query);
    });
    const localMarketHits = availableMarkets.filter((market) => {
      const text = `${market.title} ${market.category || ''} ${market.slug}`.toLowerCase();
      return !query || text.includes(query);
    }).slice(0, 30);
    const marketHits = query && commandMarketHits.length ? commandMarketHits : localMarketHits;
    return { panelHits, marketHits };
  }, [availableMarkets, commandMarketHits, commandQuery, t]);

  const commandPanelStats = useMemo(() => ({
    enabled: PANEL_LIBRARY.filter((panel) => activePanelIds.includes(panel.id)).length,
    matching: commandResults.panelHits.length,
    total: PANEL_LIBRARY.length,
  }), [commandResults.panelHits.length, activePanelIds]);

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
    worldEventMap.reset();
    setViewMode(DEFAULT_MAP_VIEW_MODE);
    resetMarketSelection();
    setNotice(t('atlas.workspaceReset'));
  };

  const resetMap = () => worldEventMap.setRegion('global');

  const copyLink = async () => {
    const writeClipboard = async (value: string) => {
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(value);
          return;
        }
      } catch {
        // Fall through to the selection-based copy path for restricted browsers.
      }
      const textarea = document.createElement('textarea');
      textarea.value = value;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      textarea.style.pointerEvents = 'none';
      document.body.appendChild(textarea);
      textarea.select();
      const copied = document.execCommand('copy');
      textarea.remove();
      if (!copied) throw new Error('Clipboard copy was rejected');
    };
    const shareUrl = new URL(worldEventMap.shareUrl(window.location.href));
    shareUrl.searchParams.set('view', viewMode);
    const value = shareUrl.toString();
    try {
      await writeClipboard(value);
      setNotice(t('atlas.linkCopied'));
    } catch {
      setManualCopyLink(value);
      window.setTimeout(() => {
        manualCopyInputRef.current?.focus();
        manualCopyInputRef.current?.select();
      }, 0);
    }
  };

  const focusCommandMarket = (market: MarketListItem) => {
    setSelectedMarketId(market.id);
    setShowCommandPalette(false);
    setNotice(t('atlas.focusedMarket', { title: `${market.title.slice(0, 72)}${market.title.length > 72 ? '...' : ''}` }));
    window.setTimeout(() => {
      document.querySelector('.wm-focused-market-row')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }, 0);
  };

  const focusRelatedMarket = (marketId: number) => {
    const group = findGroupForMarketId(marketGroups, marketId);
    if (group) {
      focusMarketGroup(group, outcomeKeyForGroupMarket(group, marketId), marketId);
    } else {
      setSelectedMarketId(marketId);
    }
    setNotice(`Focused evidence-linked market ${marketId}.`);
  };

  const changeViewMode = (nextMode: MapViewMode) => {
    setViewMode(nextMode);
    setNotice(t('atlas.viewEnabled', { view: t(MAP_VIEW_MESSAGE_KEYS[nextMode]) }));
  };

  const zoomIn = () => setMapZoom((current) => clampMapZoom(current + 1));
  const zoomOut = () => setMapZoom((current) => clampMapZoom(current - 1));
  const formatMarketPercent = (value?: string | number | null) => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? formatPercent(numeric) : '--';
  };
  const formatMarketCompact = (value?: string | number | null) => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? formatNumber(numeric, { notation: 'compact', maximumFractionDigits: 1 }) : '--';
  };
  const formatMarketCurrency = (value?: string | number | null) => {
    const numeric = Number(value);
    return Number.isFinite(numeric)
      ? formatNumber(numeric, { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 })
      : '--';
  };

  return (
    <AppShell
      regionValue={region}
      regionOptions={REGION_OPTIONS.map((option) => ({
        value: option.value,
        label: t(REGION_MESSAGE_KEYS[option.value]),
      }))}
      orderFilledCount={liveMetrics[1]?.value || 0}
      onRegionChange={(nextRegion) => {
        if (REGION_OPTIONS.some((option) => option.value === nextRegion)) setRegion(nextRegion as RegionKey);
      }}
      onResetWorkspace={resetWorkspace}
      onOpenCommandPalette={() => setShowCommandPalette(true)}
      onTogglePanelLibrary={() => setShowPanelLibrary((current) => !current)}
      onOpenSettings={() => setShowSettings(true)}
      onCopyLink={() => void copyLink()}
    >

      <main className="wm-dashboard">
        <div className="wm-main-content">
        <section className="wm-map-section">
          <div className="wm-map-header">
            <div className="wm-map-heading">
              <span className="wm-map-kicker">{t('atlas.kicker')}</span>
              <div className="wm-map-title">{t('atlas.title')} <small className="wm-map-beta">BETA</small></div>
            </div>
            <div className="wm-map-status-strip" aria-label={t('atlas.mapStatus')}>
              <span className="wm-status-chip">{t('atlas.liveStatus')}</span>
              <LiveUtcClock />
              <MapStatus sources={mapSourceStatuses} />
              <span className="wm-map-status-metric">{t('atlas.events')} <b>{formatNumber(worldEventMapEvents.length)}</b></span>
              <span className="wm-map-status-metric">{t('atlas.visible')} <b>{formatNumber(mapVisibleEventCount)}</b></span>
              <span className="wm-map-status-metric">{t('atlas.quality')} <b>{mapQualityLabel}</b></span>
            </div>
            <div className="wm-map-view-toggle" role="tablist" aria-label={t('atlas.viewMode')}>
              {MAP_VIEW_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="tab"
                  aria-selected={viewMode === option.value}
                  className={viewMode === option.value ? 'active' : ''}
                  onClick={() => changeViewMode(option.value)}
                >
                  {t(MAP_VIEW_MESSAGE_KEYS[option.value])}
                </button>
              ))}
            </div>
          </div>

          <MapToolbar
            state={worldEventMap.state}
            onTimeRangeChange={worldEventMap.setTimeRange}
            onSeveritiesChange={worldEventMap.setSeverities}
            onBasemapProviderChange={worldEventMap.setBasemapProvider}
            onBasemapThemeChange={worldEventMap.setBasemapTheme}
            onClearCountry={() => worldEventMap.setCountry(null)}
          />

          <div className="wm-map-stage">
            <div className={`wm-globe-area ${viewMode !== '3d' ? 'wm-globe-area-flat' : ''}`}>
              <LayerPanel
                items={layers}
                events={worldEventMapEvents}
                collapsed={!showPanelLibrary}
                onToggle={toggleLayer}
                onCollapse={() => setShowPanelLibrary(false)}
                onExpand={() => setShowPanelLibrary(true)}
              />

              <div className="wm-globe-hero">
                {viewMode === '3d' ? (
                  <WorldGlobe
                    markets={displayMarkets}
                    selectedMarket={selectedMarket}
                    recentTrades={currentGlobalTrades}
                    recentOracle={currentGlobalOracle}
                    contentItems={currentLatestContent}
                    ucdpEvents={ucdpRawMapEvents}
                    region={region}
                    zoomLevel={Math.min(4, mapZoom)}
                    enabledLayerIds={enabledLayerIds}
                    onMetricsChange={setGlobeStatus}
                  />
                ) : (
                  <WorldEventMapView
                    onRendererKindChange={setMapRendererKind}
                    events={worldEventMapEvents}
                    state={worldEventMap.state}
                    onCameraChange={(nextCamera) => worldEventMap.setCamera(nextCamera.center, nextCamera.zoom)}
                    onEventSelect={worldEventMap.selectEvent}
                    onOpenMarket={focusRelatedMarket}
                    onAviationLensChange={worldEventMap.setAviationLens}
                    onAviationRiskSourceChange={worldEventMap.setAviationRiskSource}
                    onAviationClose={() => worldEventMap.toggleLayer('air-routes')}
                    onCountryChange={worldEventMap.setCountry}
                    onWeatherPreset={() => { for (const id of ['weather-alerts', 'weather-radar']) if (!worldEventMap.state.activeLayerIds.includes(id)) worldEventMap.toggleLayer(id); }}
                  />
                )}

              </div>

              <div className="wm-map-controls">
                <button type="button" aria-label={t("map.zoomin")} onClick={zoomIn}>＋</button>
                <button type="button" aria-label={t("map.zoomout")} onClick={zoomOut}>－</button>
                <button type="button" aria-label={t("map.globaloverview")} onClick={resetMap}>⌂</button>
              </div>

              {loading ? <div className="wm-banner">{t('atlas.bootstrapping')}</div> : null}
              {bundleLoading ? <div className="wm-banner secondary">{t('atlas.switchingMarket')}</div> : null}
              {error || focusError ? <div className="wm-banner error">{error || focusError}</div> : null}
              {notice ? <div className="wm-banner notice">{notice}</div> : null}
            </div>
          </div>

        </section>

        <section className="wm-focused-market-row">
          {activeMarketsEntry?.render ? (
            <PanelWorkspaceSlot
              panelId="active-markets"
              size={activeMarketsEntry.size}
              layoutPrefs={panelLayoutPrefs}
              layoutWidth={layoutWidth}
              onVisibilityChange={runtime.setPanelVisible}
              className="wm-focused-market-list"
              layoutManaged={false}
              resizeEnabled={false}
              loading={panelShouldShowLoading('active-markets')}
              runtimeStatus={getPanelRuntimeStatus('active-markets')}
              onRetry={() => retryRuntimePanel('active-markets')}
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
                    layoutWidth={layoutWidth}
                    onVisibilityChange={runtime.setPanelVisible}
                    className={className}
                    layoutManaged={false}
                    resizeEnabled={false}
                    loading={panelShouldShowLoading(panelId)}
                    runtimeStatus={getPanelRuntimeStatus(panelId)}
                    onRetry={() => retryRuntimePanel(panelId)}
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
          {oracleFeedEntry?.render ? (
            <PanelWorkspaceSlot
              panelId="oracle-feed"
              size={oracleFeedEntry.size}
              layoutPrefs={panelLayoutPrefs}
              layoutWidth={layoutWidth}
              onVisibilityChange={runtime.setPanelVisible}
              className="wm-focused-oracle-feed"
              layoutManaged={false}
              resizeEnabled={false}
              loading={panelShouldShowLoading('oracle-feed')}
              runtimeStatus={getPanelRuntimeStatus('oracle-feed')}
              onRetry={() => retryRuntimePanel('oracle-feed')}
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
            if (!entry?.render) return null;
            return (
              <PanelWorkspaceSlot
                key={panelId}
                panelId={panelId}
                size={entry.size}
                layoutPrefs={panelLayoutPrefs}
                layoutWidth={layoutWidth}
                onVisibilityChange={runtime.setPanelVisible}
                loading={panelShouldShowLoading(panelId)}
                runtimeStatus={getPanelRuntimeStatus(panelId)}
                onRetry={() => retryRuntimePanel(panelId)}
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

      {showCommandPalette ? (
        <div className="wm-modal-backdrop" onClick={() => setShowCommandPalette(false)}>
          <div className="wm-modal wm-command-modal" onClick={(event) => event.stopPropagation()} onKeyDown={handleCommandKeyDown}>
            <div className="wm-command-header">
              <div>
                <span>{t('atlas.commandTitle')}</span>
                <strong>{t('atlas.commandSearchTitle')}</strong>
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
                placeholder={t('atlas.commandPlaceholder')}
              />
              <kbd>⌘K</kbd>
            </div>
            <div className="wm-command-tabs" role="tablist" aria-label={t('atlas.commandSections')}>
              <button type="button" className={commandTab === 'markets' ? 'active' : ''} onClick={() => setCommandTab('markets')}>{t('atlas.commandMarkets')} <span>{formatNumber(commandResults.marketHits.length)}</span></button>
              <button type="button" className={commandTab === 'panels' ? 'active' : ''} onClick={() => setCommandTab('panels')}>{t('atlas.commandPanels')} <span>{formatNumber(commandPanelStats.matching)}/{formatNumber(commandPanelStats.total)}</span></button>
              <button type="button" className={commandTab === 'commands' ? 'active' : ''} onClick={() => setCommandTab('commands')}>{t('atlas.commandCommands')} <span>{formatNumber(3)}</span></button>
            </div>
            <div className="wm-command-body">
              {commandTab === 'markets' ? (
                <div className="wm-command-market-layout">
                  <div className="wm-command-group wm-command-market-list">
                    <div className="wm-command-list-head">
                      <span>{t('atlas.commandMarket')}</span>
                      <span>YES</span>
                      <span>{t('atlas.commandVolume')}</span>
                      <span>{t('atlas.commandTransactions')}</span>
                      <span>{t('atlas.commandAge')}</span>
                    </div>
                    {commandMarketSearchLoading ? <div className="wm-command-empty">{t('atlas.commandSearching')}</div> : null}
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
                              <em>{market.category || t('atlas.commandUncategorized')}</em>
                            </span>
                          </div>
                          <b>{formatMarketPercent(market.latestPrice)}</b>
                          <b>{formatMarketCurrency(market.volume24h)}</b>
                          <b>{formatMarketCompact(market.tradeCount24h)}</b>
                          <b>{formatRelativeTime(market.lastTradeAt || null)}</b>
                        </button>
                      );
                    })}
                    {!commandMarketSearchLoading && !commandMarketSearchError && commandQuery.trim() && !commandResults.marketHits.length ? (
                      <div className="wm-command-empty">{t('atlas.commandNoMarkets')}</div>
                    ) : null}
                  </div>
                  <aside className="wm-command-preview" aria-label={t('atlas.commandPreview')}>
                    {commandActiveMarket ? (
                      <>
                        <div className="wm-command-preview-top">
                          <span className={`wm-command-status ${commandMarketStatusClass(commandActiveMarket)}`}>{commandMarketStatus(commandActiveMarket)}</span>
                          <em>{commandActiveMarket.category || t('atlas.commandMarket')}</em>
                        </div>
                        <strong>{commandActiveMarket.title}</strong>
                        <div className="wm-command-preview-price">
                          <span><em>YES</em><b>{formatMarketPercent(commandActiveMarket.latestPrice)}</b></span>
                          <span><em>{t('atlasMarket.volume24h')}</em><b>{formatMarketCurrency(commandActiveMarket.volume24h)}</b></span>
                          <span><em>{t('atlasMarket.trades24h')}</em><b>{formatMarketCompact(commandActiveMarket.tradeCount24h)}</b></span>
                          <span><em>{t('atlas.commandLastTrade')}</em><b>{formatRelativeTime(commandActiveMarket.lastTradeAt || null)}</b></span>
                        </div>
                        <div className="wm-command-preview-meta">
                          <span><em>{t('atlas.commandMarketId')}</em><b>{formatNumber(commandActiveMarket.id)}</b></span>
                          <span><em>{t('atlas.commandOutcomes')}</em><b>{formatNumber(commandActiveMarket.outcomeCount || 2)}</b></span>
                          <span><em>{t('atlas.commandCloses')}</em><b>{commandActiveMarket.endDate ? formatDateTime(commandActiveMarket.endDate) : '--'}</b></span>
                        </div>
                        <div className="wm-command-preview-tags">
                          {(commandActiveMarket.tags || []).slice(0, 5).map((tag) => <span key={tag}>{tag}</span>)}
                        </div>
                        <a className="wm-command-primary" href={`/markets/${commandActiveMarket.id}`}>{t('atlas.commandOpenMarket')}</a>
                      </>
                    ) : (
                      <div className="wm-command-empty">{t('atlas.commandPreviewHelp')}</div>
                    )}
                  </aside>
                </div>
              ) : null}
              {commandTab === 'panels' ? (
                <div className="wm-command-panel-section">
                  <div className="wm-command-panel-summary">
                    <span>{t('atlas.commandShowingPanels', { matching: formatNumber(commandPanelStats.matching), total: formatNumber(commandPanelStats.total) })}</span>
                    <span>{t('atlas.commandEnabledCount', { count: formatNumber(commandPanelStats.enabled) })}</span>
                    {commandQuery.trim() ? <em>{t('atlas.commandFilteredBy', { query: commandQuery.trim() })}</em> : <em>{t('atlas.commandFullLibrary')}</em>}
                  </div>
                  <div className="wm-command-panel-grid">
                    {commandResults.panelHits.map((panel) => {
                      const meta = localizedPanelMeta(panel, t);
                      return (
                        <button
                          key={panel.id}
                          type="button"
                          className={`wm-command-result wm-command-panel-result ${activePanelIds.includes(panel.id) ? 'enabled' : ''}`}
                          onClick={() => {
                            if (!activePanelIds.includes(panel.id)) togglePanel(panel.id);
                            setShowCommandPalette(false);
                          }}
                        >
                          <div className="wm-command-panel-main">
                            <strong>{meta.title}</strong>
                            <small>{panel.id}</small>
                          </div>
                          <span>{meta.description}</span>
                          <div className="wm-command-panel-meta">
                            <i>{panel.eyebrow || t('atlas.commandPanel')}</i>
                            <i>{panel.size || t('atlas.commandDefaultSize')}</i>
                            <em>{activePanelIds.includes(panel.id) ? t('atlas.commandEnabled') : t('atlas.commandAddPanel')}</em>
                          </div>
                        </button>
                      );
                    })}
                    {!commandResults.panelHits.length ? (
                      <div className="wm-command-empty">{t('atlas.commandNoPanels')}</div>
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
                    <strong>{t('atlas.commandReset')}</strong>
                    <span>{t('atlas.commandResetDetail')}</span>
                    <em>{t('atlas.commandRun')}</em>
                  </button>
                  <button type="button" className="wm-command-result wm-command-panel-result" onClick={() => {
                    setShowCommandPalette(false);
                    setShowSettings(true);
                  }}>
                    <strong>{t('atlas.commandSettings')}</strong>
                    <span>{t('atlas.commandSettingsDetail')}</span>
                    <em>{t('atlas.commandOpen')}</em>
                  </button>
                  <button type="button" className="wm-command-result wm-command-panel-result" onClick={() => {
                    void copyLink();
                    setShowCommandPalette(false);
                  }}>
                    <strong>{t('atlas.commandCopyLink')}</strong>
                    <span>{t('atlas.commandCopyLinkDetail')}</span>
                    <em>{t('atlas.commandCopy')}</em>
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
            <div className="wm-modal-title">{t('settings.title')}</div>
            <label className="wm-settings-row">
              <span>{t('settings.language')}</span>
              <select value={locale} onChange={(event) => setLocale(event.currentTarget.value === 'zh' ? 'zh' : 'en')}>
                <option value="en">{t('language.english')}</option>
                <option value="zh">{t('language.chinese')}</option>
              </select>
            </label>
            <label className="wm-settings-row">
              <span>{t('settings.region')}</span>
              <select value={region} onChange={(event) => setRegion((event.currentTarget as HTMLSelectElement).value as RegionKey)}>
                {REGION_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{t(REGION_MESSAGE_KEYS[option.value])}</option>
                ))}
              </select>
            </label>
            <label className="wm-settings-row">
              <span>{t('settings.mapMode')}</span>
              <select value={viewMode} onChange={(event) => setViewMode((event.currentTarget as HTMLSelectElement).value as MapViewMode)}>
                {MAP_VIEW_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{t(MAP_VIEW_MESSAGE_KEYS[option.value])}</option>
                ))}
              </select>
            </label>
            <label className="wm-settings-row">
              <span>{t('settings.mapZoom')}</span>
              <input type="range" min="-1" max="8" step="0.25" value={String(mapZoom)} onInput={(event) => setMapZoom(clampMapZoom((event.currentTarget as HTMLInputElement).value))} />
            </label>
            <section className={`wm-settings-sync is-${workspaceSyncStatus}`} aria-live="polite">
              <div>
                <span>{t('settings.cloud')}</span>
                <strong>
                  {workspaceSyncStatus === 'synced' ? t('settings.synced')
                    : workspaceSyncStatus === 'saving' ? t('settings.saving')
                    : workspaceSyncStatus === 'local' ? t('settings.local')
                    : workspaceSyncStatus === 'checking' ? t('settings.checking')
                    : workspaceSyncStatus === 'conflict' ? t('settings.conflict')
                    : t('settings.unavailable')}
                </strong>
                <small>
                  {workspaceSyncUpdatedAt
                    ? t('settings.serverObserved', { date: formatDateTime(workspaceSyncUpdatedAt) })
                    : t('settings.syncDescription')}
                </small>
              </div>
              <div>
                {workspaceSyncStatus === 'local' ? <a href="/login?next=/">{t('settings.signIn')}</a> : null}
                {workspaceSyncStatus === 'error' || workspaceSyncStatus === 'conflict'
                  ? <button type="button" onClick={retryWorkspaceSync}>{workspaceSyncStatus === 'conflict' ? t('settings.latestCloud') : t('settings.retry')}</button>
                  : null}
                <a href="/briefings">{t('settings.briefings')}</a>
              </div>
            </section>
            <div className="wm-settings-actions">
              <button type="button" className="wm-settings-btn" onClick={() => enableAllPanels()}>{t('settings.enableAll')}</button>
              <button type="button" className="wm-settings-btn" onClick={() => restorePanels(bootstrap)}>{t('settings.restore')}</button>
              <button type="button" className="wm-settings-btn primary" onClick={() => { resetWorkspace(); setShowSettings(false); }}>{t('settings.reset')}</button>
            </div>
          </div>
        </div>
      ) : null}

      {manualCopyLink ? (
        <div className="wm-modal-backdrop" onClick={() => setManualCopyLink(null)}>
          <div
            className="wm-modal wm-copy-link-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="wm-copy-link-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="wm-modal-title" id="wm-copy-link-title">{t('atlas.copyManualTitle')}</div>
            <p>{t('atlas.copyManualDetail')}</p>
            <input
              ref={manualCopyInputRef}
              type="text"
              readOnly
              value={manualCopyLink}
              onFocus={(event) => event.currentTarget.select()}
            />
            <div className="wm-settings-actions">
              <button type="button" className="wm-settings-btn" onClick={() => {
                manualCopyInputRef.current?.focus();
                manualCopyInputRef.current?.select();
              }}>{t('atlas.selectLink')}</button>
              <button type="button" className="wm-settings-btn primary" onClick={() => setManualCopyLink(null)}>{t('atlas.closeCopy')}</button>
            </div>
          </div>
        </div>
      ) : null}

    </AppShell>
  );
}

export function App() {
  const pathname = typeof window === 'undefined' ? '/' : window.location.pathname;
  if (pathname === '/login' || pathname.startsWith('/login/')) {
    return (
      <Suspense fallback={<PanelLoading label="Loading secure access" detail="Preparing administrator sign in" />}>
        <LoginWorkspace />
      </Suspense>
    );
  }
  if (pathname === '/account' || pathname.startsWith('/account/')) {
    return (
      <Suspense fallback={<PanelLoading label="Loading access control" detail="Reading session and credential registry" />}>
        <AccountWorkspace />
      </Suspense>
    );
  }
  if (/^\/briefings\/[A-Za-z0-9_-]{32}(?:\/|$)/.test(pathname)) {
    return (
      <Suspense fallback={<PanelLoading label="Loading briefing" detail="Opening canonical prediction-market snapshot" />}>
        <PublicBriefingWorkspace />
      </Suspense>
    );
  }
  if (pathname === '/briefings' || pathname === '/briefings/') {
    return (
      <Suspense fallback={<PanelLoading label="Loading briefings" detail="Reading revocable share registry" />}>
        <BriefingManagerWorkspace />
      </Suspense>
    );
  }
  if (pathname === '/developers' || pathname.startsWith('/developers/')) {
    return (
      <Suspense fallback={<PanelLoading label="Loading developer surface" detail="Reading MCP discovery and security contracts" />}>
        <DeveloperWorkspace />
      </Suspense>
    );
  }
  if (pathname === '/watchlist' || pathname.startsWith('/watchlist/')) {
    return (
      <Suspense fallback={<PanelLoading label="Loading Watchlist" detail="Reading tracked markets, Oracle rules and alert events" />}>
        <WatchlistWorkspace />
      </Suspense>
    );
  }
  if (pathname === '/data-quality' || pathname.startsWith('/data-quality/')) {
    return (
      <Suspense fallback={<PanelLoading label="Loading Data Quality workspace" detail="Auditing market identity, Oracle lifecycle and synchronization watermarks" />}>
        <DataQualityWorkspace />
      </Suspense>
    );
  }
  if (/^\/markets\/\d+(?:\/|$)/.test(pathname)) {
    return (
      <Suspense fallback={<PanelLoading label="Loading Market workspace" detail="Resolving market identity, probability and evidence sources" />}>
        <MarketWorkspace />
      </Suspense>
    );
  }
  return <WorldMonitorApp />;
}
