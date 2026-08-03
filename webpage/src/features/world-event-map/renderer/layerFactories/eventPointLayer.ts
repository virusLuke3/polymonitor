import { ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import type { Layer, LayersList } from '@deck.gl/core';
import type { Feature, Point } from 'geojson';
import Supercluster from 'supercluster';
import type { GeoEvent, GeoEventSeverity } from '../../domain/types';
import {
  worldEventLayerById,
  worldEventLayerIdForEvent,
} from '../../config/layerRegistry';
import {
  eventColor,
  eventLabel,
  MAP_MONO_FONT_FAMILY,
  pointRadiusMeters,
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
  label?: string;
};

type ClusterPointProperties = {
  eventId: string;
  severityRank: number;
  west: number;
  south: number;
  east: number;
  north: number;
  representativeEventId: string;
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

function pointFeature(event: GeoEvent): Feature<Point, ClusterPointProperties> {
  const [lon, lat] = event.geometry?.type === 'Point' ? event.geometry.coordinates : [0, 0];
  return {
    type: 'Feature',
    geometry: event.geometry as Point,
    properties: {
      eventId: event.id,
      severityRank: SEVERITY_RANK[event.severity],
      west: lon,
      south: lat,
      east: lon,
      north: lat,
      representativeEventId: event.id,
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

function rendersAsIndependentPoint(event: GeoEvent) {
  return isHazardEvent(event) && [
    'earthquake',
    'volcano',
    'tropical-cyclone',
    'tornado',
    'tsunami',
  ].includes(event.hazardKind);
}

function inViewport(event: GeoEvent, viewport: [number, number, number, number]) {
  if (event.geometry?.type !== 'Point') return false;
  const [lon, lat] = event.geometry.coordinates;
  return lon >= viewport[0] && lon <= viewport[2] && lat >= viewport[1] && lat <= viewport[3];
}

/** Persistent source index. Viewport/zoom queries never rebuild Supercluster. */
export class EventClusterIndex {
  private source: GeoEvent[] | null = null;
  private eventById = new Map<string, GeoEvent>();
  private independent: GeoEvent[] = [];
  private unclustered: UnclusteredBucket[] = [];
  private buckets: ClusterBucket[] = [];
  private queryKey = '';
  private queryResult: { singles: GeoEvent[]; clusters: EventCluster[] } | null = null;
  buildCount = 0;

  update(events: GeoEvent[]) {
    if (events === this.source) return;
    this.source = events;
    this.eventById = new Map();
    this.independent = [];
    this.unclustered = [];
    this.buckets = [];
    this.queryKey = '';
    this.queryResult = null;
    const grouped = new Map<string, GeoEvent[]>();
    for (const event of events) {
      if (event.geometry?.type !== 'Point') continue;
      if (event.properties.mapEntity === 'air-hub' || event.properties.mapEntity === 'live-aircraft') continue;
      const layerId = worldEventLayerIdForEvent(event);
      if (!layerId) continue;
      this.eventById.set(event.id, event);
      if (rendersAsIndependentPoint(event)) {
        this.independent.push(event);
        continue;
      }
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
          accumulated.west = Math.min(accumulated.west, properties.west);
          accumulated.south = Math.min(accumulated.south, properties.south);
          accumulated.east = Math.max(accumulated.east, properties.east);
          accumulated.north = Math.max(accumulated.north, properties.north);
        },
      });
      const eventById = new Map(bucketEvents.map((event) => [event.id, event]));
      index.load(bucketEvents.map(pointFeature));
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
    const key = `${normalizedZoom}|${selectedEventId || ''}|${viewport.map((value) => value.toFixed(3)).join(':')}`;
    if (key === this.queryKey && this.queryResult) return this.queryResult;
    const selected = selectedEventId ? this.eventById.get(selectedEventId) : undefined;
    const singles: GeoEvent[] = selected ? [selected] : [];
    const addVisible = (event: GeoEvent, revealLowPriority = true) => {
      if (event.id === selectedEventId || !inViewport(event, viewport)) return;
      if (revealLowPriority || zoom >= 3 || event.severity === 'warning' || event.severity === 'critical') {
        singles.push(event);
      }
    };
    for (const event of this.independent) {
      const layerId = worldEventLayerIdForEvent(event);
      const layer = layerId ? worldEventLayerById(layerId) : undefined;
      if (layer && zoom >= layer.minZoom) addVisible(event);
    }
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
          if (event) addVisible(event, false);
          continue;
        }
        const clusterId = Number(feature.properties.cluster_id);
        const properties = feature.properties as typeof feature.properties & ClusterAggregateProperties;
        const representative = bucket.eventById.get(properties.representativeEventId)
          || bucket.eventById.values().next().value as GeoEvent | undefined;
        if (!representative) continue;
        const leaves = bucket.index.getLeaves(clusterId, MAX_CLUSTER_LEAVES);
        const severity = severityFromRank(Number(properties.severityRank || 0));
        clusters.push({
          kind: 'event-cluster',
          id: `cluster:${bucket.id}:${clusterId}`,
          coordinates: feature.geometry.coordinates as [number, number],
          eventIds: leaves.map((leaf) => leaf.properties.eventId),
          count: Number(feature.properties.point_count),
          severity,
          bounds: [properties.west, properties.south, properties.east, properties.north],
          expansionZoom: bucket.index.getClusterExpansionZoom(clusterId),
          color: eventColor(representative),
          label: semanticLabel(representative),
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

  const priorityEvents = singles
    .filter((event) => (
      event.id === selectedEventId || event.severity === 'critical' || event.severity === 'warning'
    ))
    .slice(0, 120);
  if (priorityEvents.length) {
    layers.push(new ScatterplotLayer<GeoEvent>({
      id: 'world-event-priority-rings',
      data: priorityEvents,
      getPosition: (event) => event.geometry?.type === 'Point' ? event.geometry.coordinates : [0, 0],
      getRadius: (event) => pointRadiusMeters(event) * (event.id === selectedEventId ? 2.8 : 2.15),
      getFillColor: (event) => eventColor(event, event.id === selectedEventId ? 76 : 34),
      getLineColor: (event) => eventColor(event, event.id === selectedEventId ? 255 : 225),
      getLineWidth: (event) => event.id === selectedEventId ? 2.4 : 1.45,
      radiusMinPixels: 8,
      radiusMaxPixels: 34,
      lineWidthMinPixels: 1.25,
      pickable: false,
      stroked: true,
    }));
  }

  if (clusters.length) {
    layers.push(new ScatterplotLayer<EventCluster>({
      id: 'world-event-cluster-halos',
      data: clusters,
      getPosition: (cluster) => cluster.coordinates,
      getRadius: (cluster) => Math.max(52_000, Math.log2(cluster.count + 1) * 48_000),
      getFillColor: (cluster) => [cluster.color[0], cluster.color[1], cluster.color[2], 32],
      getLineColor: (cluster) => {
        const [red, green, blue] = SEVERITY_COLORS[cluster.severity];
        return [red, green, blue, 235];
      },
      getLineWidth: 2,
      radiusMinPixels: 10,
      radiusMaxPixels: 32,
      lineWidthMinPixels: 1.4,
      pickable: false,
      stroked: true,
    }));
    layers.push(new ScatterplotLayer<EventCluster>({
      id: 'world-event-clusters',
      data: clusters,
      getPosition: (cluster) => cluster.coordinates,
      getRadius: (cluster) => Math.max(36_000, Math.log2(cluster.count + 1) * 34_000),
      getFillColor: (cluster) => [cluster.color[0], cluster.color[1], cluster.color[2], 225],
      getLineColor: [255, 250, 222, 235],
      getLineWidth: 1.35,
      radiusMinPixels: 8,
      radiusMaxPixels: 27,
      lineWidthMinPixels: 1.15,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 250, 198, 118],
      stroked: true,
    }));
    layers.push(new TextLayer<EventCluster>({
      id: 'world-event-cluster-counts',
      data: clusters,
      getPosition: (cluster) => cluster.coordinates,
      getText: (cluster) => String(cluster.count),
      getSize: 11,
      getColor: [255, 252, 236, 255],
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'center',
      fontFamily: MAP_MONO_FONT_FAMILY,
      fontWeight: 800,
      outlineWidth: 2,
      outlineColor: [6, 10, 14, 255],
      pickable: false,
    }));
  }

  if (singles.length) {
    layers.push(new ScatterplotLayer<GeoEvent>({
      id: 'world-event-points',
      data: singles,
      getPosition: (event) => event.geometry?.type === 'Point' ? event.geometry.coordinates : [0, 0],
      getRadius: pointRadiusMeters,
      getFillColor: (event) => eventColor(event, event.id === selectedEventId ? 255 : 242),
      getLineColor: (event) => event.id === selectedEventId ? [255, 250, 222, 255] : eventColor(event, 255),
      getLineWidth: (event) => event.id === selectedEventId ? 2.4 : 1,
      radiusMinPixels: 4.5,
      radiusMaxPixels: 18,
      lineWidthMinPixels: 1.15,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 104],
      stroked: true,
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
      getPosition: (event) => event.geometry?.type === 'Point' ? event.geometry.coordinates : [0, 0],
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
