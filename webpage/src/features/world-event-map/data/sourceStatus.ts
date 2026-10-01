import type {
  GeoEventAdapterResult,
  GeoEventSourceStatus,
  HazardMapResponse,
} from '../domain/types';

export type WorldEventSourceStatus = {
  key: string;
  label: string;
  status: 'loading' | GeoEventSourceStatus;
  phase?: 'disabled' | 'zoom-required' | 'renderer-limited' | 'loading' | 'fresh' | 'empty' | 'partial' | 'stale' | 'unavailable' | 'recovering';
  eventCount: number;
  rejectedCount: number;
  generatedAt?: string;
  message?: string;
};

export function sourceStatusFromAdapter({
  key,
  label,
  payloadStatus,
  generatedAt,
  result,
  loaded,
}: {
  key: string;
  label: string;
  payloadStatus?: unknown;
  generatedAt?: string;
  result: GeoEventAdapterResult;
  loaded: boolean;
}): WorldEventSourceStatus {
  if (!loaded) {
    return {
      key,
      label,
      status: 'loading',
      eventCount: 0,
      rejectedCount: 0,
    };
  }
  const rawStatus = String(payloadStatus || '').trim().toLowerCase();
  let status: GeoEventSourceStatus = rawStatus === 'error' || rawStatus === 'failed'
    ? 'error'
    : rawStatus === 'degraded' || rawStatus.includes('stale')
      ? 'degraded'
      : rawStatus === 'partial' || result.rejected.length > 0
        ? 'partial'
        : 'ok';
  if (!result.events.length && status === 'ok' && result.rejected.length) status = 'partial';
  return {
    key,
    label,
    status,
    eventCount: result.events.length,
    rejectedCount: result.rejected.length,
    generatedAt,
    message: result.rejected.length
      ? `${result.rejected.length} record${result.rejected.length === 1 ? '' : 's'} rejected by the map contract`
      : undefined,
  };
}

const HAZARD_SOURCE_LABELS: Record<string, string> = {
  usgs: 'USGS',
  'usgs-volcano-cap': 'USGS VOLCANO',
  nhc: 'NHC',
  eonet: 'EONET',
  gdacs: 'GDACS',
  nws: 'NWS',
  firms: 'FIRMS',
  'climate-anomaly': 'ANOMALY',
};

const HAZARD_PROVIDERS: Record<string, readonly string[]> = {
  usgs: ['USGS'], 'usgs-volcano-cap': ['USGS Volcano Hazards Program HANS CAP'],
  nhc: ['NOAA National Hurricane Center', 'NHC'], eonet: ['NASA EONET'],
  gdacs: ['GDACS'], nws: ['NWS', 'NOAA National Weather Service'], firms: ['NASA FIRMS'],
  'climate-anomaly': ['NOAA NCEI Climate at a Glance'],
};

export function sourceStatusesFromHazardResponse(
  response: HazardMapResponse | null,
  rejectedCount = 0,
  loading = false,
): WorldEventSourceStatus[] {
  if (!response) {
    return loading
      ? ['usgs', 'usgs-volcano-cap', 'nhc', 'eonet', 'gdacs', 'nws', 'firms', 'climate-anomaly'].map((key) => ({
          key,
          label: HAZARD_SOURCE_LABELS[key] || key.toUpperCase(),
          status: 'loading' as const,
          eventCount: 0,
          rejectedCount: 0,
        }))
      : [];
  }
  return response.sources.map((source) => {
    const names = HAZARD_PROVIDERS[source.key] || [source.key];
    const eventCount = response.events.filter((event) => event.sources.some(
      (item) => names.some(name => name.toLowerCase() === item.provider.toLowerCase()),
    )).length;
    const details = [
      source.coverage.label,
      ...source.coverage.gaps,
      source.errorCode ? `Source condition: ${source.errorCode}` : '',
    ].filter(Boolean);
    if (rejectedCount > 0) details.push(`${rejectedCount} record${rejectedCount === 1 ? '' : 's'} rejected by the map contract; see data quality for details.`);
    const geometryIncomplete = source.key === 'nws' && response.events.some(event => event.sources.some(item => names.includes(item.provider)) && (!event.geometry || Number(event.properties.unresolvedZoneCount || 0) > 0));
    const transportExpired = ['ok', 'partial'].includes(source.status)
      && Number.isFinite(Date.parse(source.staleAfter || '')) && Date.parse(source.staleAfter!) <= Date.now();
    if (geometryIncomplete) details.push(`${transportExpired ? 'Retained catalog' : 'Fresh catalog'}; optional official boundaries are incomplete or still resolving.`);
    if (transportExpired) details.push('Source freshness deadline has passed; retaining the original last-success time while refreshing.');
    const status = transportExpired ? 'degraded' : source.status === 'ok' && (rejectedCount > 0 || geometryIncomplete) ? 'partial' : source.status;
    return {
      phase: geometryIncomplete && status === 'ok' ? 'partial' : status === 'error' ? 'unavailable' : status === 'degraded' ? 'stale' : status === 'partial' ? 'partial' : eventCount === 0 ? 'empty' : 'fresh',
      key: source.key,
      label: HAZARD_SOURCE_LABELS[source.key] || source.key.toUpperCase(),
      status,
      eventCount,
      rejectedCount: source.status === 'ok' ? rejectedCount : 0,
      generatedAt: source.dataUpdatedAt || source.fetchedAt || response.generatedAt,
      message: details.join(' · '),
    };
  });
}

export function sourceStatusesAfterHazardRefreshFailure(
  current: WorldEventSourceStatus[],
  message: string,
  hasSnapshot: boolean,
): WorldEventSourceStatus[] {
  if (!hasSnapshot) {
    if (current.length) {
      return current.map((source) => ({
        ...source,
        status: 'error',
        eventCount: 0,
        message: `Initial source load failed: ${message}`,
      }));
    }
    return [{
      key: 'natural-hazards',
      label: 'HAZARDS',
      status: 'error',
      eventCount: 0,
      rejectedCount: 0,
      message,
    }];
  }
  return current.map((source) => ({
    ...source,
    status: source.status === 'error' ? 'error' : 'degraded',
    message: `${source.message ? `${source.message} · ` : ''}Refresh failed; retaining the last successful snapshot: ${message}`,
  }));
}
