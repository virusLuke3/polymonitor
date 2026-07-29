import { ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import type { Layer, LayersList } from '@deck.gl/core';
import type { GeoEvent, GeoEventSeverity } from '../../domain/types';
import { eventColor, eventLabel, pointRadiusMeters, SEVERITY_COLORS } from './shared';

export type EventCluster = {
  kind: 'event-cluster';
  id: string;
  coordinates: [number, number];
  eventIds: string[];
  count: number;
  severity: GeoEventSeverity;
  bounds: [number, number, number, number];
};

const SEVERITY_RANK: Record<GeoEventSeverity, number> = {
  info: 0,
  watch: 1,
  warning: 2,
  critical: 3,
};

function clusterPoints(events: GeoEvent[], zoom: number, selectedEventId: string | null) {
  if (zoom >= 4.5) return { singles: events, clusters: [] as EventCluster[] };
  const cellSize = Math.max(3, 28 / Math.pow(1.7, Math.max(0, zoom - 0.75)));
  const buckets = new Map<string, GeoEvent[]>();
  const singles: GeoEvent[] = [];
  for (const event of events) {
    if (event.id === selectedEventId || event.geometry?.type !== 'Point') {
      singles.push(event);
      continue;
    }
    const [lon, lat] = event.geometry.coordinates;
    const key = `${Math.floor((lon + 180) / cellSize)}:${Math.floor((lat + 90) / cellSize)}`;
    const bucket = buckets.get(key) || [];
    bucket.push(event);
    buckets.set(key, bucket);
  }
  const clusters: EventCluster[] = [];
  for (const [key, bucket] of buckets) {
    if (bucket.length < 3) {
      singles.push(...bucket);
      continue;
    }
    let lonTotal = 0;
    let latTotal = 0;
    let west = 180;
    let east = -180;
    let south = 90;
    let north = -90;
    let severity: GeoEventSeverity = 'info';
    for (const event of bucket) {
      const coordinates = event.geometry?.type === 'Point' ? event.geometry.coordinates : [0, 0];
      const lon = coordinates[0] ?? 0;
      const lat = coordinates[1] ?? 0;
      lonTotal += lon;
      latTotal += lat;
      west = Math.min(west, lon);
      east = Math.max(east, lon);
      south = Math.min(south, lat);
      north = Math.max(north, lat);
      if (SEVERITY_RANK[event.severity] > SEVERITY_RANK[severity]) severity = event.severity;
    }
    clusters.push({
      kind: 'event-cluster',
      id: `cluster:${key}:${bucket.length}`,
      coordinates: [lonTotal / bucket.length, latTotal / bucket.length],
      eventIds: bucket.map((event) => event.id),
      count: bucket.length,
      severity,
      bounds: [west, south, east, north],
    });
  }
  return { singles, clusters };
}

export function createEventPointLayers({
  events,
  zoom,
  selectedEventId,
  showLabels,
}: {
  events: GeoEvent[];
  zoom: number;
  selectedEventId: string | null;
  showLabels: boolean;
}): LayersList {
  const pointEvents = events.filter((event) => event.geometry?.type === 'Point');
  const { singles, clusters } = clusterPoints(pointEvents, zoom, selectedEventId);
  const layers: Layer[] = [];

  if (clusters.length) {
    layers.push(new ScatterplotLayer<EventCluster>({
      id: 'world-event-clusters',
      data: clusters,
      getPosition: (cluster) => cluster.coordinates,
      getRadius: (cluster) => Math.max(36_000, Math.log2(cluster.count + 1) * 34_000),
      getFillColor: (cluster) => {
        const [r, g, b] = SEVERITY_COLORS[cluster.severity];
        return [r, g, b, 105];
      },
      getLineColor: (cluster) => {
        const [r, g, b] = SEVERITY_COLORS[cluster.severity];
        return [r, g, b, 220];
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

  const labeled = showLabels && zoom >= 3.4
    ? singles
      .filter((event) => event.id === selectedEventId || event.severity === 'critical' || event.category === 'natural-hazard')
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
