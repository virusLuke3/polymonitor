import { IconLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import type { Layer, LayersList } from '@deck.gl/core';
import type { Feature, Point } from 'geojson';
import Supercluster from 'supercluster';
import type { GeoEvent, GeoEventSeverity } from '../../domain/types';
import {
  worldEventLayerById,
  worldEventLayerIdForEvent,
} from '../../config/layerRegistry';
import {
  MAP_SEVERITY_STYLES,
  MAP_SYMBOL_ATLAS,
  MAP_SYMBOL_ICON_MAPPING,
  mapSymbolForEvent,
  type MapSymbolKey,
} from '../../config/mapSymbols';
import {
  continuousMetricRadiusMeters,
  eventLabel,
  eventGeometryBounds,
  eventRepresentativePoint,
  MAP_MONO_FONT_FAMILY,
  SEVERITY_COLORS,
  isHazardEvent,
} from './shared';

export type EventCluster = {
  kind: 'event-cluster';
  id: string;
  coordinates: [number, number];
  eventIds: string[];
  count: number;
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

const MAX_CLUSTER_LEAVES = 200;
const WORLD_VIEWPORT: [number, number, number, number] = [-180, -85, 180, 85];

const SEVERITIES: readonly GeoEventSeverity[] = ['info', 'watch', 'warning', 'critical'];
const SEVERITY_RANK: Record<GeoEventSeverity, number> = {
  info: 0,
  watch: 1,
  warning: 2,
  critical: 3,
};

function severityFromRank(rank: number): GeoEventSeverity {
  return SEVERITIES[Math.max(0, Math.min(SEVERITIES.length - 1, Math.round(rank)))] || 'info';
}

function isMajorWorldEvent(event: GeoEvent) {
  if (event.severity === 'critical') return true;
  if (event.severity !== 'warning') return false;
  if (!isHazardEvent(event)) return true;
  if (event.metrics.kind === 'earthquake') {
    const pager = String(event.metrics.pagerAlert || '').toLowerCase();
    return event.metrics.magnitude >= 5.2
      || Number(event.metrics.significance || 0) >= 500
      || event.metrics.tsunami === true
      || pager === 'orange'
      || pager === 'red';
  }
  if ((event.hazardKind === 'wildfire' || event.hazardKind === 'fire-detection')
    && event.metrics.kind === 'wildfire') {
    return event.hazardKind === 'wildfire'
      || Number(event.metrics.detectionCount || 0) >= 20
      || Number(event.metrics.fireRadiativePowerMw || 0) >= 100;
  }
  return true;
}

export function eventDisclosureTier(event: GeoEvent) {
  if (isMajorWorldEvent(event)) return 0;
  if (event.severity === 'watch' || event.severity === 'warning') return 1;
  return 2;
}

function disclosureTierForZoom(zoom: number) {
  return zoom < 2.5 ? 0 : zoom < 4 ? 1 : 2;
}

export function eventVisibleAtZoom(event: GeoEvent, zoom: number, selectedEventId: string | null) {
  return event.id === selectedEventId || eventDisclosureTier(event) <= disclosureTierForZoom(zoom);
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
        minPoints: 3,
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
      if (!layer || zoom < layer.minZoom) continue;
      for (const event of bucket.events) addVisible(event);
    }

    const clusters: EventCluster[] = [];
    for (const bucket of this.buckets) {
      const layer = worldEventLayerById(bucket.layerId);
      if (!layer || zoom < layer.minZoom) continue;
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
        const visibleCount = Number(feature.properties.point_count);
        const representativeId = properties.representativeEventId;
        const representative = bucket.eventById.get(representativeId)
          || bucket.eventById.get(properties.representativeEventId)
          || bucket.eventById.values().next().value as GeoEvent | undefined;
        if (!representative) continue;
        const leaves = bucket.index.getLeaves(clusterId, MAX_CLUSTER_LEAVES);
        const visibleLeaves = leaves
          .map((leaf) => bucket.eventById.get(leaf.properties.eventId))
          .filter((event): event is GeoEvent => event != null);
        if (visibleCount === 1) {
          addVisible(representative);
          continue;
        }
        const severityRank = properties.severityRank;
        const severity = severityFromRank(Number(severityRank || 0));
        const [red, green, blue] = SEVERITY_COLORS[severity];
        clusters.push({
          kind: 'event-cluster',
          id: `cluster:${bucket.id}:${clusterId}`,
          coordinates: feature.geometry.coordinates as [number, number],
          eventIds: visibleLeaves.map((event) => event.id),
          count: visibleCount,
          severity,
          bounds: [properties.west, properties.south, properties.east, properties.north],
          expansionZoom: bucket.index.getClusterExpansionZoom(clusterId),
          color: [red, green, blue, SEVERITY_COLORS[severity][3]],
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

function pointAlpha(event: GeoEvent, zoom: number, selectedEventId: string | null) {
  if (event.id === selectedEventId) return 255;
  const base = event.severity === 'critical'
    ? 235
    : event.severity === 'warning'
      ? 210
      : event.severity === 'watch'
        ? 145
        : 105;
  const zoomScale = zoom < 2.5 ? 0.62 : zoom < 4 ? 0.8 : 1;
  const scaled = Math.round(base * zoomScale);
  if (event.severity === 'critical') return Math.max(205, scaled);
  if (event.severity === 'warning') return Math.max(150, scaled);
  return scaled;
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

export function createEventPointLayers({
  events,
  zoom,
  selectedEventId,
  showLabels,
  viewport,
  clusterIndex,
}: {
  events: GeoEvent[];
  zoom: number;
  selectedEventId: string | null;
  showLabels: boolean;
  viewport?: [number, number, number, number];
  clusterIndex?: EventClusterIndex;
}): LayersList {
  const index = clusterIndex || new EventClusterIndex();
  index.update(events);
  const { singles, clusters } = index.query(zoom, selectedEventId, viewport);
  const layers: Layer[] = [];

  if (clusters.length) {
    layers.push(new ScatterplotLayer<EventCluster>({
      id: 'world-event-cluster-halos',
      data: clusters,
      getPosition: (cluster) => cluster.coordinates,
      getRadius: 28_000,
      getFillColor: [3, 9, 13, zoom < 2.5 ? 215 : 228],
      getLineColor: (cluster) => cluster.color,
      getLineWidth: (cluster) => MAP_SEVERITY_STYLES[cluster.severity].lineWidth,
      radiusMinPixels: zoom < 2.5 ? 11 : 12,
      radiusMaxPixels: zoom < 2.5 ? 11 : 12,
      lineWidthMinPixels: 1,
      pickable: false,
      stroked: true,
    }));
    layers.push(new IconLayer<EventCluster>({
      id: 'world-event-clusters',
      data: clusters,
      iconAtlas: MAP_SYMBOL_ATLAS,
      iconMapping: MAP_SYMBOL_ICON_MAPPING,
      getIcon: (cluster) => cluster.symbol,
      getPosition: (cluster) => cluster.coordinates,
      getSize: (cluster) => Math.min(22, 14 + Math.log2(cluster.count + 1) * 1.25),
      getColor: (cluster) => cluster.color,
      sizeUnits: 'pixels',
      sizeMinPixels: 14,
      sizeMaxPixels: 22,
      alphaCutoff: 0.05,
      pickable: true,
      autoHighlight: false,
    }));
    layers.push(new TextLayer<EventCluster>({
      id: 'world-event-cluster-counts',
      data: clusters,
      getPosition: (cluster) => cluster.coordinates,
      getText: (cluster) => String(cluster.count),
      getSize: (cluster) => String(cluster.count).length > 3 ? 7 : 8,
      getColor: [236, 244, 242, 255],
      getPixelOffset: [10, 8],
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'center',
      fontFamily: MAP_MONO_FONT_FAMILY,
      fontWeight: 800,
      background: true,
      getBackgroundColor: [4, 10, 14, 242],
      getBorderColor: (cluster) => cluster.color,
      getBorderWidth: 1,
      backgroundPadding: [3, 2],
      backgroundBorderRadius: 4,
      pickable: false,
    }));
  }

  if (singles.length) {
    const intensityEvents = singles.filter((event) => continuousMetricRadiusMeters(event) != null);
    if (intensityEvents.length) {
      layers.push(new ScatterplotLayer<GeoEvent>({
        id: 'world-event-point-intensity',
        data: intensityEvents,
        getPosition: (event) => eventRepresentativePoint(event)!,
        getRadius: (event) => continuousMetricRadiusMeters(event) || 0,
        getFillColor: (event) => {
          const [red, green, blue] = SEVERITY_COLORS[event.severity];
          return [red, green, blue, zoom < 2.5 ? 22 : 32];
        },
        getLineColor: (event) => {
          const [red, green, blue] = SEVERITY_COLORS[event.severity];
          return [red, green, blue, zoom < 2.5 ? 78 : 100];
        },
        getLineWidth: 1,
        radiusMinPixels: 7,
        radiusMaxPixels: zoom < 2.5 ? 14 : zoom < 4 ? 18 : 23,
        lineWidthMinPixels: 0.8,
        pickable: false,
        filled: true,
        stroked: true,
      }));
    }
    layers.push(new ScatterplotLayer<GeoEvent>({
      id: 'world-event-point-frames',
      data: singles,
      getPosition: (event) => eventRepresentativePoint(event)!,
      getRadius: 18_000,
      getFillColor: [3, 9, 13, 210],
      getLineColor: (event) => {
        const [red, green, blue] = SEVERITY_COLORS[event.severity];
        return [red, green, blue, Math.min(255, pointAlpha(event, zoom, selectedEventId) + 20)];
      },
      getLineWidth: (event) => event.id === selectedEventId
        ? 2.4
        : MAP_SEVERITY_STYLES[event.severity].lineWidth,
      radiusMinPixels: zoom < 2.5 ? 7.5 : 8.5,
      radiusMaxPixels: zoom < 2.5 ? 9 : 10,
      lineWidthMinPixels: 1,
      pickable: false,
      stroked: true,
    }));
    layers.push(new IconLayer<GeoEvent>({
      id: 'world-event-points',
      data: singles,
      iconAtlas: MAP_SYMBOL_ATLAS,
      iconMapping: MAP_SYMBOL_ICON_MAPPING,
      getIcon: mapSymbolForEvent,
      getPosition: (event) => eventRepresentativePoint(event)!,
      getSize: (event) => event.id === selectedEventId ? 19 : zoom < 2.5 ? 13 : zoom < 4 ? 14.5 : 16,
      getColor: (event) => {
        const [red, green, blue] = SEVERITY_COLORS[event.severity];
        return [red, green, blue, pointAlpha(event, zoom, selectedEventId)];
      },
      sizeUnits: 'pixels',
      sizeMinPixels: 12,
      sizeMaxPixels: 20,
      alphaCutoff: 0.05,
      pickable: true,
      autoHighlight: false,
    }));
  }

  const labeled = showLabels
    ? singles
      .filter((event) => {
        const layerId = worldEventLayerIdForEvent(event);
        const labelMinZoom = layerId ? worldEventLayerById(layerId)?.labelMinZoom ?? 3 : 3;
        return zoom >= labelMinZoom
          && (event.id === selectedEventId || event.severity === 'critical' || event.category === 'natural-hazard');
      })
      .slice(0, zoom < 5 ? 80 : 220)
    : [];
  if (labeled.length) {
    layers.push(new TextLayer<GeoEvent>({
      id: 'world-event-labels',
      data: labeled,
      getPosition: (event) => eventRepresentativePoint(event)!,
      getText: eventLabel,
      getPixelOffset: [7, -8],
      getSize: (event) => event.id === selectedEventId ? 11 : 9,
      getColor: [226, 231, 229, 220],
      getTextAnchor: 'start',
      getAlignmentBaseline: 'bottom',
      fontFamily: MAP_MONO_FONT_FAMILY,
      fontWeight: 700,
      pickable: false,
    }));
  }
  return layers;
}
