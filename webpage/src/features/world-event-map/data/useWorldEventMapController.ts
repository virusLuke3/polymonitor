import { useMapInfrastructure } from './useMapInfrastructure';
import { useMapSignals } from './useMapSignals';
import type { RendererViewport } from '../renderer/MapRenderer';
import { clampWorldEventZoom } from '../state/mapState';
import { useEffect, useMemo, useState } from 'preact/hooks';
import type { RuntimeBreakingEventRadarPayload, RuntimeGeoSanctionsShockPayload, RuntimeGlobalTransportShippingPayload } from '@/types';
import type { usePanelRuntime } from '@/panels/usePanelRuntime';
import type { MapSymbolKey } from '../config/mapSymbols';
import { selectableWorldEventLayers, worldEventLayerById } from '../config/layerRegistry';
import type { WorldEventRegion } from '../config/regions';
import { adaptGeoShockPayload, adaptGeoShockCountryRiskPayload } from '../adapters/geoShockAdapter';
import { adaptBreakingEventMapPayload } from '../adapters/breakingEventAdapter';
import { adaptTransportReference } from '../adapters/transportReferenceAdapter';
import { filterWorldEventMapEvents, filterWorldEventMapEventsForLayers } from '../state/selectors';
import { useWorldEventMapState } from '../state/useWorldEventMapState';
import { sourceStatusFromAdapter } from './sourceStatus';
import { useCountryGeometry } from './useCountryGeometry';
import { useNaturalHazards } from './useNaturalHazards';
import { useAviationViewport } from './useAviationViewport';
import { hasGeoConflictCoordinates, writeWorldEventMapSeed } from './worldEventMapSeed';

export type LayerToggle = {
  id: string;
  label: string;
  panelEmoji: string;
  icon: MapSymbolKey;
  enabled: boolean;
  hint?: string;
  aliases: string[];
  availability: 'ready' | 'degraded' | 'unavailable';
  availabilityReason?: string;
  isExecutable: boolean;
  sourceKeys: string[];
  requiredSources: string[];
};


const INITIAL_LAYERS: LayerToggle[] = selectableWorldEventLayers().map((layer) => ({
  id: layer.id,
  label: layer.label,
  panelEmoji: layer.panelEmoji,
  icon: layer.icon,
  enabled: layer.defaultEnabled,
  hint: layer.hint,
  aliases: [...layer.aliases],
  availability: layer.availability,
  availabilityReason: layer.availabilityReason,
  isExecutable: layer.isExecutable(),
  sourceKeys: [...layer.sourceKeys],
  requiredSources: [...layer.requiredSources],
}));


export function clampMapZoom(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 1.25;
  return clampWorldEventZoom(Math.round(numeric * 4) / 4);
}



type SharedRuntime = Pick<ReturnType<typeof usePanelRuntime>, 'runtimeData' | 'getStatus' | 'refreshIds' | 'setConsumerPanels' | 'suspended'>;

/** Owns map state and source composition. Shared snapshots stay in Panel Runtime. */
export function useWorldEventMapController({ runtimeData, getStatus: getPanelRuntimeStatus, refreshIds, setConsumerPanels, suspended }: SharedRuntime, mapActive = true) {
  const worldEventMap = useWorldEventMapState();
  const [rendererViewport, setRendererViewport] = useState<RendererViewport | null>(null);
  const [mapRendererKind, setMapRendererKind] = useState<'webgl' | 'svg'>('webgl');
  const infrastructure = useMapInfrastructure(!suspended && mapActive && worldEventMap.state.activeLayerIds.some(id => ['waterways','pipelines','submarine-cables'].includes(id)), rendererViewport);
  const mapSignals = useMapSignals(worldEventMap.state.activeLayerIds, suspended || !mapActive);
  const naturalHazards = useNaturalHazards({
    sourceKeys: worldEventMap.state.activeLayerIds.flatMap((id) => worldEventLayerById(id)?.sourceKeys || []),
    zoom: worldEventMap.state.zoom,
    center: [worldEventMap.state.center.lon, worldEventMap.state.center.lat],
    suspended: suspended || !mapActive,
  });
  const airRoutesRequested = worldEventMap.state.activeLayerIds.includes('air-routes');
  const aviationViewport = useAviationViewport(
    airRoutesRequested && mapActive && !suspended,
    rendererViewport,
  );
  const layers = useMemo<LayerToggle[]>(() => {
    const statuses = new Map(naturalHazards.sources.map((source) => [source.key, source]));
    return INITIAL_LAYERS.map((layer) => {
      if (layer.id === 'weather-radar' && mapRendererKind === 'svg') return {
        ...layer, enabled: false, isExecutable: false, availability: 'unavailable' as const,
        availabilityReason: 'Radar requires the WebGL renderer; SVG keeps the event map available.',
      };
      const relevant = layer.sourceKeys.map((key) => statuses.get(key)).filter(Boolean);
      const required = layer.requiredSources.map((key) => statuses.get(key)).filter(Boolean);
      const requiredUnavailable = required.length > 0 && required.some((source) => (
        source?.status === 'error' && source.eventCount === 0
      ));
      const aviationDegraded = layer.id === 'air-routes'
        && Boolean(aviationViewport.error || aviationViewport.payload?.status === 'unavailable');
      const degraded = aviationDegraded
        || relevant.some((source) => source?.status === 'error' || source?.status === 'degraded');
      const reasons = relevant
        .filter((source) => source?.status === 'error' || source?.status === 'degraded')
        .map((source) => `${source?.label || source?.key}: ${source?.message || source?.status}`);
      if (requiredUnavailable) {
        reasons.unshift('A required authoritative source is unavailable; this layer cannot make its declared claim.');
      }
      if (aviationDegraded) {
        reasons.push(
          aviationViewport.error
            || aviationViewport.payload?.limitations?.join(' · ')
            || aviationViewport.payload?.errorCode
            || 'Live viewport aircraft are unavailable; reference routes remain usable.',
        );
      }
      return {
        ...layer,
        enabled: worldEventMap.state.activeLayerIds.includes(layer.id),
        availability: layer.availability === 'unavailable' || requiredUnavailable
          ? 'unavailable'
          : degraded ? 'degraded' : 'ready',
        availabilityReason: reasons.join(' · ') || layer.availabilityReason,
      };
    });
  }, [
    mapRendererKind,
    aviationViewport.error,
    aviationViewport.phase,
    aviationViewport.payload,
    naturalHazards.sources,
    worldEventMap.state.activeLayerIds,
  ]);
  const region = worldEventMap.state.region;
  const mapZoom = worldEventMap.state.zoom;
  const setRegion = (nextRegion: WorldEventRegion) => worldEventMap.setRegion(nextRegion);
  const setMapZoom = (nextZoom: number | ((current: number) => number)) => {
    const value = typeof nextZoom === 'function' ? nextZoom(worldEventMap.state.zoom) : nextZoom;
    worldEventMap.setZoom(clampMapZoom(value));
  };

  const enabledLayerIds = useMemo(() => layers.filter((layer) => layer.enabled).map((layer) => layer.id), [layers]);
  const geoShockPayload = runtimeData['geo-sanctions-shock'] as RuntimeGeoSanctionsShockPayload | undefined;
  const ucdpLayerEnabled = enabledLayerIds.includes('ucdp');
  const intelLayerEnabled = enabledLayerIds.includes('intel-hotspots');
  const countryRiskLayerEnabled = enabledLayerIds.includes('sanctions-country-risk');
  const countryGeometry = useCountryGeometry(
    mapActive && !suspended,
  );
  const breakingEventPayload = runtimeData['breaking-event-radar'] as RuntimeBreakingEventRadarPayload | undefined;
  const ucdpRawMapEvents = useMemo(
    () => (ucdpLayerEnabled ? (geoShockPayload?.items || []).filter(hasGeoConflictCoordinates) : []),
    [geoShockPayload, ucdpLayerEnabled],
  );
  const geoShockAdapterResult = useMemo(() => adaptGeoShockPayload(geoShockPayload), [geoShockPayload]);
  const intelAdapterResult = useMemo(
    () => adaptBreakingEventMapPayload(breakingEventPayload, countryGeometry.index),
    [breakingEventPayload, countryGeometry.index],
  );
  const countryRiskAdapterResult = useMemo(
    () => adaptGeoShockCountryRiskPayload(geoShockPayload, countryGeometry.index),
    [countryGeometry.index, geoShockPayload],
  );
  const worldEventFilterState = useMemo(() => ({
    activeLayerIds: worldEventMap.state.activeLayerIds,
    timeRange: worldEventMap.state.timeRange,
    severities: worldEventMap.state.severities,
    countryCode: worldEventMap.state.countryCode,
  }), [
    worldEventMap.state.activeLayerIds,
    worldEventMap.state.severities,
    worldEventMap.state.timeRange,
    worldEventMap.state.countryCode,
  ]);
  const hazardMapEvents = useMemo(
    () => filterWorldEventMapEventsForLayers(
      naturalHazards.events,
      worldEventFilterState,
      Date.now(),
      countryGeometry.index,
    ),
    [countryGeometry.index, naturalHazards.events, worldEventFilterState],
  );
  const ucdpMapEvents = useMemo(
    () => ucdpLayerEnabled
      ? filterWorldEventMapEvents(
        geoShockAdapterResult.events.filter((event) => event.geometry?.type === 'Point'),
        worldEventFilterState,
        Date.now(),
        countryGeometry.index,
      )
      : [],
    [countryGeometry.index, geoShockAdapterResult, ucdpLayerEnabled, worldEventFilterState],
  );
  const intelMapEvents = useMemo(
    () => intelLayerEnabled
      ? filterWorldEventMapEvents(
        intelAdapterResult.events,
        worldEventFilterState,
        Date.now(),
        countryGeometry.index,
      )
      : [],
    [countryGeometry.index, intelAdapterResult.events, intelLayerEnabled, worldEventFilterState],
  );
  const countryRiskMapEvents = useMemo(
    () => countryRiskLayerEnabled
      ? filterWorldEventMapEvents(
        countryRiskAdapterResult.events,
        worldEventFilterState,
        Date.now(),
        countryGeometry.index,
      )
      : [],
    [countryGeometry.index, countryRiskAdapterResult.events, countryRiskLayerEnabled, worldEventFilterState],
  );
  const showAirRoutes = airRoutesRequested;
  const transportPayload = runtimeData['global-transport-shipping'] as RuntimeGlobalTransportShippingPayload | undefined;
  const mapTransportPayload = useMemo<RuntimeGlobalTransportShippingPayload | undefined>(() => {
    if (!showAirRoutes) return transportPayload;
    if (!transportPayload && !aviationViewport.payload) return undefined;
    return {
      ...(transportPayload || { items: [] }),
      status: transportPayload?.status || aviationViewport.payload?.status || 'loading',
      aviation: {
        ...transportPayload?.aviation,
        generatedAt: aviationViewport.payload?.generatedAt || transportPayload?.aviation?.generatedAt,
        liveFlights: aviationViewport.payload?.aircraft ?? transportPayload?.aviation?.liveFlights ?? [],
      },
    };
  }, [aviationViewport.payload, showAirRoutes, transportPayload]);
  const airReferenceAdapterResult = useMemo(
    () => showAirRoutes
      ? adaptTransportReference(mapTransportPayload)
      : { events: [], rejected: [] },
    [showAirRoutes, mapTransportPayload],
  );
  const airReferenceEvents = airReferenceAdapterResult.events;
  const supplementalEvents = useMemo(() => mapSignals.events.map(event => {
    if (event.properties.mapLayer !== 'internet-outages' || !event.countryCode) return event;
    const country = countryGeometry.index?.resolve(event.countryCode);
    return country ? {...event, geometry: country.geometry, locationPrecision: 'country' as const} : event;
  }), [mapSignals.events, countryGeometry.index]);
  const worldEventMapEvents = useMemo(
    () => [
      ...hazardMapEvents,
      ...intelMapEvents,
      ...ucdpMapEvents,
      ...countryRiskMapEvents,
      ...airReferenceEvents,
      ...filterWorldEventMapEventsForLayers([...supplementalEvents, ...infrastructure.events], worldEventFilterState, Date.now(), countryGeometry.index),
    ],
    [infrastructure.events, supplementalEvents, worldEventFilterState, countryGeometry.index, airReferenceEvents, countryRiskMapEvents, hazardMapEvents, intelMapEvents, ucdpMapEvents],
  );
  const mapSourceStatuses = useMemo(() => {
    const activeSourceKeys = new Set(
      enabledLayerIds.flatMap((layerId) => worldEventLayerById(layerId)?.sourceKeys || []),
    );
    const statuses = naturalHazards.sources.filter((source) => activeSourceKeys.has(source.key));
    if (ucdpLayerEnabled) {
      statuses.push(sourceStatusFromAdapter({
        key: 'geo-sanctions-shock',
        label: 'UCDP',
        payloadStatus: geoShockPayload?.conflictState || geoShockPayload?.status,
        generatedAt: geoShockPayload?.generatedAt,
        result: geoShockAdapterResult,
        loaded: Boolean(geoShockPayload),
      }));
    }
    if (intelLayerEnabled) {
      const runtimeStatus = getPanelRuntimeStatus('breaking-event-radar');
      const status = sourceStatusFromAdapter({
        key: 'breaking-event-radar',
        label: 'INTEL',
        payloadStatus: countryGeometry.error
          ? 'error'
          : breakingEventPayload?.status || runtimeStatus.phase,
        generatedAt: breakingEventPayload?.generatedAt,
        result: intelAdapterResult,
        loaded: Boolean(countryGeometry.error)
          || (Boolean(breakingEventPayload) && Boolean(countryGeometry.index)),
      });
      if (countryGeometry.error) status.message = countryGeometry.error;
      statuses.push(status);
    }
    if (countryRiskLayerEnabled) {
      const runtimeStatus = getPanelRuntimeStatus('geo-sanctions-shock');
      const status = sourceStatusFromAdapter({
        key: 'geo-sanctions-shock-risk',
        label: 'COUNTRY RISK',
        payloadStatus: countryGeometry.error
          ? 'error'
          : geoShockPayload?.status || runtimeStatus.phase,
        generatedAt: geoShockPayload?.generatedAt,
        result: countryRiskAdapterResult,
        loaded: Boolean(countryGeometry.error)
          || (Boolean(geoShockPayload) && Boolean(countryGeometry.index)),
      });
      if (countryGeometry.error) status.message = countryGeometry.error;
      statuses.push(status);
    }
    if (showAirRoutes) {
      const runtimeStatus = getPanelRuntimeStatus('global-transport-shipping');
      const status = sourceStatusFromAdapter({
        key: 'global-transport-shipping',
        label: 'AVIATION',
        payloadStatus: aviationViewport.error
          ? (aviationViewport.payload || transportPayload ? 'degraded' : 'error')
          : aviationViewport.payload?.status === 'unavailable'
            ? 'degraded'
            : transportPayload?.status || aviationViewport.payload?.status || runtimeStatus.phase,
        generatedAt: aviationViewport.payload?.generatedAt
          || transportPayload?.aviation?.generatedAt
          || transportPayload?.generatedAt,
        result: airReferenceAdapterResult,
        loaded: Boolean(transportPayload || aviationViewport.payload || aviationViewport.error),
      });
      if (aviationViewport.error) {
        status.message = aviationViewport.payload || transportPayload
          ? `Viewport refresh failed; retaining the last successful aviation snapshot: ${aviationViewport.error}`
          : aviationViewport.error;
      }
      else if (aviationViewport.payload?.limitations?.length) {
        status.message = aviationViewport.payload.limitations.join(' · ');
      }
      status.phase = aviationViewport.phase === 'OFF' ? 'disabled' : aviationViewport.phase === 'ZOOM_REQUIRED' ? 'zoom-required' : aviationViewport.phase === 'LOADING' ? 'loading' : aviationViewport.phase === 'EMPTY' ? 'empty' : aviationViewport.phase === 'PARTIAL' ? 'partial' : aviationViewport.phase === 'STALE' ? 'stale' : aviationViewport.phase === 'UNAVAILABLE' ? 'unavailable' : 'fresh';
      statuses.push(status);
    }
    return statuses;
  }, [
    breakingEventPayload,
    countryGeometry.error,
    countryGeometry.index,
    countryRiskAdapterResult,
    countryRiskLayerEnabled,
    enabledLayerIds,
    getPanelRuntimeStatus,
    geoShockAdapterResult,
    geoShockPayload,
    intelAdapterResult,
    intelLayerEnabled,
    naturalHazards.sources,
    showAirRoutes,
    aviationViewport.error,
    aviationViewport.phase,
    aviationViewport.payload,
    transportPayload,
    airReferenceAdapterResult,
    ucdpLayerEnabled,
  ]);

  const requiredPanelIds = useMemo(() => [
    ...(ucdpLayerEnabled || (mapActive && countryRiskLayerEnabled) ? ['geo-sanctions-shock'] : []),
    ...(mapActive && intelLayerEnabled ? ['breaking-event-radar'] : []),
    ...(mapActive && showAirRoutes ? ['global-transport-shipping'] : []),
  ], [ucdpLayerEnabled, countryRiskLayerEnabled, intelLayerEnabled, showAirRoutes, mapActive]);
  useEffect(() => {
    setConsumerPanels('world-event-map', requiredPanelIds);
    return () => setConsumerPanels('world-event-map', []);
  }, [requiredPanelIds, setConsumerPanels]);
  const missingSources = requiredPanelIds.filter((id) => runtimeData[id] === undefined).join(',');
  useEffect(() => {
    if (missingSources) void refreshIds(missingSources.split(','), { reason: 'refresh' });
  }, [missingSources, refreshIds]);
  useEffect(() => { writeWorldEventMapSeed(geoShockPayload); }, [geoShockPayload]);
  return { countryIndex: countryGeometry.index, worldEventMap, setRendererViewport, aviationStatus: aviationViewport, setMapRendererKind, layers, region, mapZoom, setRegion, setMapZoom, enabledLayerIds,
    ucdpRawMapEvents, worldEventMapEvents, mapSourceStatuses: [...mapSourceStatuses, ...mapSignals.sources, ...infrastructure.sources] };
}
