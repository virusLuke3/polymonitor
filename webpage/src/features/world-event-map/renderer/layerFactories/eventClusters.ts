import type { Feature, Point } from 'geojson';
import Supercluster from 'supercluster';
import { worldEventLayerById, worldEventLayerIdForEvent } from '../../config/layerRegistry';
import { mapSymbolForEvent, type MapSymbolKey } from '../../config/mapSymbols';
import type { GeoEvent, GeoEventSeverity } from '../../domain/types';
import { disclosureTierForZoom, eventDisclosureTier, eventVisibleAtZoom } from '../eventDisclosure';
import { coordinateBounds, eventGeometryBounds, eventRepresentativePoint, isHazardEvent, eventColor, SEVERITY_COLORS } from './shared';
export { eventDisclosureTier, eventVisibleAtZoom } from '../eventDisclosure';

export type EventCluster = {
  kind: 'event-cluster';
  id: string;
  coordinates: [number, number];
  eventIds: string[];
  count: number;
  severityCounts?: Record<GeoEventSeverity, number>;
  severity: GeoEventSeverity;
  bounds: [number, number, number, number];
  expansionZoom: number;
  color: [number, number, number, number];
  symbol: MapSymbolKey;
  label?: string;
  badge?: string;
};

type ClusterPointProperties = {
  eventId: string;
  severityRank: number;
  west: number;
  south: number;
  east: number;
  north: number;
  representativeEventId: string;
  visibilityTier: number;
  majorCount: number;
  contextCount: number;
  majorSeverityRank: number;
  contextSeverityRank: number;
  representativeMajorEventId: string;
  representativeContextEventId: string;
};

type ClusterAggregateProperties = ClusterPointProperties;

type ClusterBucket = {
  id: string;
  layerId: string;
  index: Supercluster<ClusterPointProperties, ClusterAggregateProperties>;
  eventById: Map<string, GeoEvent>;
};

type UnclusteredBucket = { layerId: string; events: GeoEvent[] };
export type ScreenBox = [number, number, number, number];
export type LabelProjection = (position: [number, number]) => { x: number; y: number } | null;

const WORLD_VIEWPORT: [number, number, number, number] = [-180, -85, 180, 85];

const SEVERITIES: readonly GeoEventSeverity[] = ['info', 'watch', 'warning', 'critical'];
export const SEVERITY_RANK: Record<GeoEventSeverity, number> = {
  info: 0,
  watch: 1,
  warning: 2,
  critical: 3,
};

function severityFromRank(rank: number): GeoEventSeverity {
  return SEVERITIES[Math.max(0, Math.min(SEVERITIES.length - 1, Math.round(rank)))] || 'info';
}

function pointFeature(event: GeoEvent, coordinates: [number, number]): Feature<Point, ClusterPointProperties> {
  const [lon, lat] = coordinates;
  const bounds = eventGeometryBounds(event) || [lon, lat, lon, lat];
  const visibilityTier = eventDisclosureTier(event);
  const severityRank = SEVERITY_RANK[event.severity];
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates },
    properties: {
      eventId: event.id,
      severityRank,
      west: bounds[0],
      south: bounds[1],
      east: bounds[2],
      north: bounds[3],
      representativeEventId: event.id,
      visibilityTier,
      majorCount: visibilityTier === 0 ? 1 : 0,
      contextCount: visibilityTier <= 1 ? 1 : 0,
      majorSeverityRank: visibilityTier === 0 ? severityRank : -1,
      contextSeverityRank: visibilityTier <= 1 ? severityRank : -1,
      representativeMajorEventId: visibilityTier === 0 ? event.id : '',
      representativeContextEventId: visibilityTier <= 1 ? event.id : '',
    },
  };
}

function eventSemanticKey(event: GeoEvent) {
  if (isHazardEvent(event)) return event.hazardKind;
  if (event.category === 'conflict' || event.category === 'unrest') {
    return `conflict-${String(event.properties.violenceType || 'unknown')}`;
  }
  return event.category;
}

function semanticLabel(event: GeoEvent) {
  if (isHazardEvent(event)) return event.hazardKind.replace(/-/g, ' ');
  if (event.category === 'conflict' || event.category === 'unrest') {
    const violenceType = String(event.properties.violenceType || '');
    if (violenceType === '1') return 'state-based conflict';
    if (violenceType === '2') return 'non-state conflict';
    if (violenceType === '3') return 'one-sided violence';
  }
  return event.category.replace(/-/g, ' ');
}

function semanticBadge(event: GeoEvent) {
  if (isHazardEvent(event)) {
    switch (event.hazardKind) {
      case 'earthquake': return 'EQ';
      case 'volcano': return 'VO';
      case 'severe-storm':
      case 'tornado': return 'ST';
      case 'tropical-cyclone': return 'CY';
      case 'flood':
      case 'tsunami': return 'FL';
      case 'wildfire':
      case 'fire-detection': return 'FI';
      case 'extreme-heat': return 'HT';
      case 'extreme-cold': return 'CL';
      case 'temperature-anomaly':
      case 'precipitation-anomaly':
      case 'other-weather-anomaly': return 'AN';
    }
  }
  if (event.category === 'conflict' || event.category === 'unrest') {
    const violenceType = String(event.properties.violenceType || '');
    if (violenceType === '1') return 'SB';
    if (violenceType === '2') return 'NS';
    if (violenceType === '3') return 'OS';
    return 'CF';
  }
  if (event.category === 'intel') return 'IN';
  return '';
}

function inViewport(event: GeoEvent, viewport: [number, number, number, number]) {
  const position = eventRepresentativePoint(event);
  if (!position) return false;
  const [lon, lat] = position;
  return lon >= viewport[0] && lon <= viewport[2] && lat >= viewport[1] && lat <= viewport[3];
}

function isClusterableMarker(event: GeoEvent) {
  if (event.geometry?.type === 'Point') return true;
  return isHazardEvent(event)
    && (event.geometry?.type === 'Polygon' || event.geometry?.type === 'MultiPolygon');
}

/** Persistent source index. Viewport/zoom queries never rebuild Supercluster. */
export class EventClusterIndex {
  private source: GeoEvent[] | null = null;
  private eventById = new Map<string, GeoEvent>();
  private unclustered: UnclusteredBucket[] = [];
  private buckets: ClusterBucket[] = [];
  private queryKey = '';
  private queryResult: { singles: GeoEvent[]; clusters: EventCluster[] } | null = null;
  buildCount = 0;

  update(events: GeoEvent[]) {
    if (events === this.source) return;
    this.source = events;
    this.eventById = new Map();
    this.unclustered = [];
    this.buckets = [];
    this.queryKey = '';
    this.queryResult = null;
    const grouped = new Map<string, GeoEvent[]>();
    for (const event of events) {
      if (!isClusterableMarker(event)) continue;
      if (event.properties.mapEntity === 'air-hub' || event.properties.mapEntity === 'live-aircraft') continue;
      if (!eventRepresentativePoint(event)) continue;
      const layerId = worldEventLayerIdForEvent(event);
      if (!layerId) continue;
      this.eventById.set(event.id, event);
      const bucketId = `${layerId}:${eventSemanticKey(event)}`;
      const bucket = grouped.get(bucketId) || [];
      bucket.push(event);
      grouped.set(bucketId, bucket);
    }

    for (const [id, bucketEvents] of grouped) {
      const layerId = id.split(':', 1)[0]!;
      const layer = worldEventLayerById(layerId);
      if (!layer?.cluster || layer.clusterRadius <= 0) {
        this.unclustered.push({ layerId, events: bucketEvents });
        continue;
      }
      const index = new Supercluster<ClusterPointProperties, ClusterAggregateProperties>({
        radius: layer.clusterRadius,
        minPoints: layer.clusterMinPoints,
        maxZoom: 7,
        map: (properties) => ({ ...properties }),
        reduce: (accumulated, properties) => {
          if (properties.severityRank > accumulated.severityRank) {
            accumulated.severityRank = properties.severityRank;
            accumulated.representativeEventId = properties.representativeEventId;
          }
          accumulated.majorCount += properties.majorCount;
          accumulated.contextCount += properties.contextCount;
          if (properties.majorSeverityRank > accumulated.majorSeverityRank) {
            accumulated.majorSeverityRank = properties.majorSeverityRank;
            accumulated.representativeMajorEventId = properties.representativeMajorEventId;
          }
          if (properties.contextSeverityRank > accumulated.contextSeverityRank) {
            accumulated.contextSeverityRank = properties.contextSeverityRank;
            accumulated.representativeContextEventId = properties.representativeContextEventId;
          }
          accumulated.visibilityTier = Math.min(accumulated.visibilityTier, properties.visibilityTier);
          accumulated.west = Math.min(accumulated.west, properties.west);
          accumulated.south = Math.min(accumulated.south, properties.south);
          accumulated.east = Math.max(accumulated.east, properties.east);
          accumulated.north = Math.max(accumulated.north, properties.north);
        },
      });
      const eventById = new Map(bucketEvents.map((event) => [event.id, event]));
      index.load(bucketEvents.map((event) => pointFeature(event, eventRepresentativePoint(event)!)));
      this.buckets.push({ id, layerId, index, eventById });
    }
    this.buildCount += 1;
  }

  query(
    zoom: number,
    selectedEventId: string | null,
    viewport: [number, number, number, number] = WORLD_VIEWPORT,
  ) {
    const normalizedZoom = Math.max(0, Math.floor(zoom));
    const disclosureTier = disclosureTierForZoom(zoom);
    // Supercluster only needs integer zooms, but disclosure changes at 2.5 and
    // 4.0. Include that tier so crossing 2.5 cannot reuse a world-view result
    // until the next integer zoom.
    const key = `${normalizedZoom}|${disclosureTier}|${selectedEventId || ''}|${viewport.map((value) => value.toFixed(3)).join(':')}`;
    if (key === this.queryKey && this.queryResult) return this.queryResult;
    const selected = selectedEventId ? this.eventById.get(selectedEventId) : undefined;
    const singles: GeoEvent[] = selected ? [selected] : [];
    const addVisible = (event: GeoEvent) => {
      if (event.id === selectedEventId || !inViewport(event, viewport)) return;
      if (eventVisibleAtZoom(event, zoom, selectedEventId)) singles.push(event);
    };
    for (const bucket of this.unclustered) {
      const layer = worldEventLayerById(bucket.layerId);
      if (!layer || Math.max(0, zoom) < layer.minZoom) continue;
      for (const event of bucket.events) addVisible(event);
    }

    const clusters: EventCluster[] = [];
    for (const bucket of this.buckets) {
      const layer = worldEventLayerById(bucket.layerId);
      if (!layer || Math.max(0, zoom) < layer.minZoom) continue;
      for (const feature of bucket.index.getClusters(viewport, normalizedZoom)) {
        if (!('cluster' in feature.properties)) {
          const event = bucket.eventById.get(feature.properties.eventId);
          if (event) addVisible(event);
          continue;
        }
        const clusterId = Number(feature.properties.cluster_id);
        const properties = feature.properties as typeof feature.properties & ClusterAggregateProperties;
        // Progressive disclosure controls standalone points, labels and heavy
        // footprints. A cluster is the bounded world-view representation of
        // every active event it contains; removing watch/info leaves from the
        // aggregate made a healthy 500-event feed look empty.
        let visibleCount = Number(feature.properties.point_count);
        const representativeId = properties.representativeEventId;
        const representative = bucket.eventById.get(representativeId)
          || bucket.eventById.get(properties.representativeEventId)
          || bucket.eventById.values().next().value as GeoEvent | undefined;
        if (!representative) continue;
        const leaves = bucket.index.getLeaves(clusterId, Infinity);
        const visibleLeaves = leaves
          .map((leaf) => bucket.eventById.get(leaf.properties.eventId))
          .filter((event): event is GeoEvent => event != null && event.id !== selectedEventId);
        visibleCount = visibleLeaves.length;
        if (!visibleCount) continue;
        if (visibleCount === 1) {
          addVisible(visibleLeaves[0]!);
          continue;
        }
        const severityCounts = { info: 0, watch: 0, warning: 0, critical: 0 };
        visibleLeaves.forEach(event => severityCounts[event.severity]++);
        const severityRank = Math.max(...visibleLeaves.map(event => SEVERITY_RANK[event.severity]));
        const severity = severityFromRank(Number(severityRank || 0));
        const [red, green, blue] = SEVERITY_COLORS[severity];
        clusters.push({
          kind: 'event-cluster',
          id: `cluster:${bucket.id}:${clusterId}`,
          coordinates: feature.geometry.coordinates as [number, number],
          eventIds: visibleLeaves.map((event) => event.id),
          count: visibleCount,
          severityCounts,
          severity,
          bounds: coordinateBounds(visibleLeaves.flatMap(event => {
            const b = eventGeometryBounds(event);
            return b ? [[b[0], b[1]], [b[2], b[3]]] as [number, number][] : [];
          })) || [properties.west, properties.south, properties.east, properties.north],
          expansionZoom: bucket.index.getClusterExpansionZoom(clusterId),
          color: isHazardEvent(representative) ? eventColor({ ...representative, severity }) : [red, green, blue, SEVERITY_COLORS[severity][3]],
          symbol: mapSymbolForEvent(representative),
          label: semanticLabel(representative),
          badge: semanticBadge(representative),
        });
      }
    }
    this.queryKey = key;
    this.queryResult = { singles, clusters };
    return this.queryResult;
  }
}

export function clusterEventPoints(
  events: GeoEvent[],
  zoom: number,
  selectedEventId: string | null,
  viewport: [number, number, number, number] = WORLD_VIEWPORT,
) {
  const index = new EventClusterIndex();
  index.update(events);
  return index.query(zoom, selectedEventId, viewport);
}
