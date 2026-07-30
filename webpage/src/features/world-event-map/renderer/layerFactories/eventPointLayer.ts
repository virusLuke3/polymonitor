import { ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import type { Layer, LayersList } from '@deck.gl/core';
import type { Feature, Point } from 'geojson';
import Supercluster from 'supercluster';
import type { GeoEvent, GeoEventSeverity } from '../../domain/types';
import {
  worldEventLayerById,
  worldEventLayerIdForEvent,
} from '../../config/layerRegistry';
import { eventColor, eventLabel, pointRadiusMeters, SEVERITY_COLORS } from './shared';

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
};

type ClusterPointProperties = {
  eventId: string;
  severityRank: number;
};

type ClusterAggregateProperties = {
  severityRank: number;
};

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
  return {
    type: 'Feature',
    geometry: event.geometry as Point,
    properties: {
      eventId: event.id,
      severityRank: SEVERITY_RANK[event.severity],
    },
  };
}

function clusterBounds(events: GeoEvent[]): [number, number, number, number] {
  let west = 180;
  let east = -180;
  let south = 90;
  let north = -90;
  for (const event of events) {
    if (event.geometry?.type !== 'Point') continue;
    const [lon, lat] = event.geometry.coordinates;
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  return [west, south, east, north];
}

export function clusterEventPoints(
  events: GeoEvent[],
  zoom: number,
  selectedEventId: string | null,
  viewport: [number, number, number, number] = [-180, -85, 180, 85],
) {
  const selected = events.filter((event) => event.id === selectedEventId);
  const grouped = new Map<string, GeoEvent[]>();
  for (const event of events) {
    if (event.id === selectedEventId || event.geometry?.type !== 'Point') continue;
    const layerId = worldEventLayerIdForEvent(event);
    if (!layerId) continue;
    const layer = worldEventLayerById(layerId);
    if (!layer || zoom < layer.minZoom) continue;
    const bucket = grouped.get(layerId) || [];
    bucket.push(event);
    grouped.set(layerId, bucket);
  }

  const singles = [...selected];
  const clusters: EventCluster[] = [];
  for (const [layerId, layerEvents] of grouped) {
    const layer = worldEventLayerById(layerId);
    if (!layer?.cluster || layer.clusterRadius <= 0) {
      singles.push(...layerEvents);
      continue;
    }
    const eventById = new Map(layerEvents.map((event) => [event.id, event]));
    const index = new Supercluster<ClusterPointProperties, ClusterAggregateProperties>({
      radius: layer.clusterRadius,
      minPoints: 3,
      maxZoom: 7,
      map: (properties) => ({ severityRank: properties.severityRank }),
      reduce: (accumulated, properties) => {
        accumulated.severityRank = Math.max(accumulated.severityRank, properties.severityRank);
      },
    });
    index.load(layerEvents.map(pointFeature));
    for (const feature of index.getClusters(viewport, Math.max(0, Math.floor(zoom)))) {
      if (!('cluster' in feature.properties)) {
        const event = eventById.get(feature.properties.eventId);
        if (event && (zoom >= 3 || event.severity === 'warning' || event.severity === 'critical')) {
          singles.push(event);
        }
        continue;
      }
      const clusterId = Number(feature.properties.cluster_id);
      const leaves = index
        .getLeaves(clusterId, Infinity)
        .flatMap((leaf) => {
          const event = eventById.get(leaf.properties.eventId);
          return event ? [event] : [];
        });
      const severity = severityFromRank(Number(feature.properties.severityRank || 0));
      const representative = leaves.reduce(
        (best, event) => SEVERITY_RANK[event.severity] > SEVERITY_RANK[best.severity] ? event : best,
        leaves[0]!,
      );
      clusters.push({
        kind: 'event-cluster',
        id: `cluster:${layerId}:${clusterId}`,
        coordinates: feature.geometry.coordinates as [number, number],
        eventIds: leaves.map((event) => event.id),
        count: Number(feature.properties.point_count),
        severity,
        bounds: clusterBounds(leaves),
        expansionZoom: index.getClusterExpansionZoom(clusterId),
        color: eventColor(representative),
      });
    }
  }
  return { singles, clusters };
}

export function createEventPointLayers({
  events,
  zoom,
  selectedEventId,
  showLabels,
  viewport,
}: {
  events: GeoEvent[];
  zoom: number;
  selectedEventId: string | null;
  showLabels: boolean;
  viewport?: [number, number, number, number];
}): LayersList {
  const pointEvents = events.filter((event) => (
    event.properties.mapEntity !== 'air-hub'
    && event.properties.mapEntity !== 'live-aircraft'
    && event.geometry?.type === 'Point'
  ));
  const { singles, clusters } = clusterEventPoints(pointEvents, zoom, selectedEventId, viewport);
  const layers: Layer[] = [];

  if (clusters.length) {
    layers.push(new ScatterplotLayer<EventCluster>({
      id: 'world-event-clusters',
      data: clusters,
      getPosition: (cluster) => cluster.coordinates,
      getRadius: (cluster) => Math.max(36_000, Math.log2(cluster.count + 1) * 34_000),
      getFillColor: (cluster) => [cluster.color[0], cluster.color[1], cluster.color[2], 115],
      getLineColor: (cluster) => {
        const [red, green, blue] = SEVERITY_COLORS[cluster.severity];
        return [red, green, blue, 220];
      },
      getLineWidth: 1.5,
      radiusMinPixels: 7,
      radiusMaxPixels: 25,
      lineWidthMinPixels: 1,
      pickable: true,
      autoHighlight: true,
      stroked: true,
    }));
    layers.push(new TextLayer<EventCluster>({
      id: 'world-event-cluster-counts',
      data: clusters,
      getPosition: (cluster) => cluster.coordinates,
      getText: (cluster) => String(cluster.count),
      getSize: 10,
      getColor: [245, 241, 224, 235],
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'center',
      fontFamily: 'monospace',
      fontWeight: 800,
      pickable: false,
    }));
  }

  if (singles.length) {
    layers.push(new ScatterplotLayer<GeoEvent>({
      id: 'world-event-points',
      data: singles,
      getPosition: (event) => event.geometry?.type === 'Point' ? event.geometry.coordinates : [0, 0],
      getRadius: pointRadiusMeters,
      getFillColor: (event) => eventColor(event, event.id === selectedEventId ? 245 : 185),
      getLineColor: (event) => event.id === selectedEventId ? [255, 250, 222, 255] : eventColor(event, 225),
      getLineWidth: (event) => event.id === selectedEventId ? 2.4 : 1,
      radiusMinPixels: 3.5,
      radiusMaxPixels: 15,
      lineWidthMinPixels: 1,
      pickable: true,
      autoHighlight: true,
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
      fontFamily: 'monospace',
      fontWeight: 700,
      pickable: false,
    }));
  }
  return layers;
}
