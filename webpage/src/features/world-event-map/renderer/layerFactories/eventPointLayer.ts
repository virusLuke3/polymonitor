import type { Layer, LayersList } from '@deck.gl/core';
import { IconLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import { worldEventLayerById, worldEventLayerIdForEvent } from '../../config/layerRegistry';
import {
  MAP_CLUSTER_COUNT_ATLAS,
  MAP_CLUSTER_COUNT_ICON_MAPPING,
  mapClusterCountIcon,
} from '../../config/mapClusterCountAtlas';
import {
  MAP_SEVERITY_STYLES,
  MAP_SYMBOL_ATLAS,
  MAP_SYMBOL_ICON_MAPPING,
  mapSymbolForEvent,
} from '../../config/mapSymbols';
import type { GeoEvent, GeoEventSeverity } from '../../domain/types';
import {
  type EventCluster,
  EventClusterIndex,
  type LabelProjection,
  type ScreenBox,
  SEVERITY_RANK,
} from './eventClusters';
import { createEventObservationLayer } from './eventObservationLayer';
import {
  continuousMetricRadiusMeters,
  eventLabel,
  eventRepresentativePoint,
  MAP_MONO_FONT_FAMILY,
  SEVERITY_COLORS,
} from './shared';

function pointAlpha(event: GeoEvent, zoom: number, selectedEventId: string | null) {
  if (event.id === selectedEventId) return 255;
  const base = event.severity === 'critical'
    ? 245
    : event.severity === 'warning'
      ? 225
      : event.severity === 'watch'
        ? 180
        : 145;
  const zoomScale = zoom < 2.5 ? 0.72 : zoom < 4 ? 0.86 : 1;
  const scaled = Math.round(base * zoomScale);
  if (event.severity === 'critical') return Math.max(205, scaled);
  if (event.severity === 'warning') return Math.max(150, scaled);
  return Math.max(event.severity === 'watch' ? 118 : 96, scaled);
}

function pointIconSize(event: GeoEvent, zoom: number, selectedEventId: string | null) {
  if (event.id === selectedEventId) return 22;
  if (zoom < 2.5) return 14;
  if (zoom < 4) return 16;
  return 18;
}

function clusterIconSize(cluster: EventCluster) {
  return Math.min(24, 15 + Math.log2(cluster.count + 1) * 1.25);
}

function severityRingColor(severity: GeoEventSeverity, alpha?: number): [number, number, number, number] {
  const [red, green, blue, baseAlpha] = MAP_SEVERITY_STYLES[severity].rgba;
  return [red, green, blue, alpha ?? baseAlpha];
}

export function createEventPointLayers({
  events,
  zoom,
  selectedEventId,
  showLabels,
  viewport,
  clusterIndex,
  project,
  occupiedScreenBoxes = [],
}: {
  events: GeoEvent[];
  zoom: number;
  selectedEventId: string | null;
  showLabels: boolean;
  viewport?: [number, number, number, number];
  clusterIndex?: EventClusterIndex;
  project?: LabelProjection;
  occupiedScreenBoxes?: ScreenBox[];
}): LayersList {
  const index = clusterIndex || new EventClusterIndex();
  index.update(events);
  const { singles, clusters } = index.query(zoom, selectedEventId, viewport);
  const layers: Layer[] = [
    ...createEventObservationLayer(events, zoom, selectedEventId, viewport),
  ].filter((layer): layer is Layer => Boolean(layer) && !Array.isArray(layer));

  if (clusters.length) {
    layers.push(new ScatterplotLayer<EventCluster>({
      id: 'world-event-cluster-severity-rings',
      data: clusters,
      getPosition: (cluster) => cluster.coordinates,
      getRadius: (cluster) => clusterIconSize(cluster) / 2 + 1,
      getFillColor: [0, 0, 0, 0],
      getLineColor: (cluster) => severityRingColor(cluster.severity),
      getLineWidth: (cluster) => MAP_SEVERITY_STYLES[cluster.severity].lineWidth,
      radiusUnits: 'pixels',
      lineWidthUnits: 'pixels',
      filled: false,
      stroked: true,
      pickable: false,
    }));
    const criticalClusters = clusters.filter((cluster) => cluster.severity === 'critical');
    if (criticalClusters.length) {
      layers.push(new ScatterplotLayer<EventCluster>({
        id: 'world-event-cluster-critical-rings',
        data: criticalClusters,
        getPosition: (cluster) => cluster.coordinates,
        getRadius: (cluster) => clusterIconSize(cluster) / 2 + 3.5,
        getFillColor: [0, 0, 0, 0],
        getLineColor: () => severityRingColor('critical', 145),
        getLineWidth: 1,
        radiusUnits: 'pixels',
        lineWidthUnits: 'pixels',
        filled: false,
        stroked: true,
        pickable: false,
      }));
    }
    layers.push(new IconLayer<EventCluster>({
      id: 'world-event-clusters',
      data: clusters,
      iconAtlas: MAP_SYMBOL_ATLAS,
      iconMapping: MAP_SYMBOL_ICON_MAPPING,
      getIcon: (cluster) => cluster.symbol,
      getPosition: (cluster) => cluster.coordinates,
      getSize: clusterIconSize,
      getColor: (cluster) => [255, 255, 255, cluster.color[3]],
      sizeUnits: 'pixels',
      sizeMinPixels: 15,
      sizeMaxPixels: 24,
      alphaCutoff: 0.05,
      pickable: true,
      autoHighlight: false,
    }));
    layers.push(new IconLayer<EventCluster>({
      id: 'world-event-cluster-counts',
      data: clusters,
      iconAtlas: MAP_CLUSTER_COUNT_ATLAS,
      iconMapping: MAP_CLUSTER_COUNT_ICON_MAPPING,
      getIcon: (cluster) => mapClusterCountIcon(cluster.count),
      getPosition: (cluster) => cluster.coordinates,
      getSize: 27,
      getColor: [255, 255, 255, 255],
      getPixelOffset: [9, 7],
      sizeUnits: 'pixels',
      sizeMinPixels: 22,
      sizeMaxPixels: 30,
      alphaCutoff: 0.02,
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
      id: 'world-event-point-severity-rings',
      data: singles,
      getPosition: (event) => eventRepresentativePoint(event)!,
      getRadius: (event) => pointIconSize(event, zoom, selectedEventId) / 2 + 0.75,
      getFillColor: [0, 0, 0, 0],
      getLineColor: (event) => severityRingColor(event.severity),
      getLineWidth: (event) => MAP_SEVERITY_STYLES[event.severity].lineWidth,
      radiusUnits: 'pixels',
      lineWidthUnits: 'pixels',
      filled: false,
      stroked: true,
      pickable: false,
    }));
    const criticalSingles = singles.filter((event) => event.severity === 'critical');
    if (criticalSingles.length) {
      layers.push(new ScatterplotLayer<GeoEvent>({
        id: 'world-event-point-critical-rings',
        data: criticalSingles,
        getPosition: (event) => eventRepresentativePoint(event)!,
        getRadius: (event) => pointIconSize(event, zoom, selectedEventId) / 2 + 3.2,
        getFillColor: [0, 0, 0, 0],
        getLineColor: () => severityRingColor('critical', 145),
        getLineWidth: 1,
        radiusUnits: 'pixels',
        lineWidthUnits: 'pixels',
        filled: false,
        stroked: true,
        pickable: false,
      }));
    }
    layers.push(new IconLayer<GeoEvent>({
      id: 'world-event-points',
      data: singles,
      iconAtlas: MAP_SYMBOL_ATLAS,
      iconMapping: MAP_SYMBOL_ICON_MAPPING,
      getIcon: mapSymbolForEvent,
      getPosition: (event) => eventRepresentativePoint(event)!,
      getSize: (event) => pointIconSize(event, zoom, selectedEventId),
      getColor: (event) => [255, 255, 255, pointAlpha(event, zoom, selectedEventId)],
      sizeUnits: 'pixels',
      sizeMinPixels: 14,
      sizeMaxPixels: 22,
      alphaCutoff: 0.05,
      pickable: true,
      autoHighlight: false,
    }));
  }

  const labelCandidates = showLabels
    ? singles
      .filter((event) => {
        const layerId = worldEventLayerIdForEvent(event);
        const labelMinZoom = layerId ? worldEventLayerById(layerId)?.labelMinZoom ?? 3 : 3;
        return zoom >= labelMinZoom
          && (event.id === selectedEventId
            || event.severity === 'critical'
            || (event.category === 'natural-hazard' && (zoom >= 4 || event.severity === 'warning')));
      })
    : [];
  const boxes: ScreenBox[] = [...occupiedScreenBoxes];
  if (project) {
    for (const event of singles) {
      const point = eventRepresentativePoint(event);
      const screen = point ? project(point) : null;
      if (!screen) continue;
      const radius = pointIconSize(event, zoom, selectedEventId) / 2 + 2;
      boxes.push([screen.x - radius, screen.y - radius, screen.x + radius, screen.y + radius]);
    }
    for (const cluster of clusters) {
      const screen = project(cluster.coordinates);
      if (!screen) continue;
      const radius = clusterIconSize(cluster) / 2 + 5;
      boxes.push([screen.x - radius, screen.y - radius, screen.x + radius, screen.y + radius]);
    }
  }
  const overlaps = (candidate: ScreenBox) => boxes.some((box) => !(
    candidate[2] < box[0] || candidate[0] > box[2] || candidate[3] < box[1] || candidate[1] > box[3]
  ));
  const labeled = labelCandidates
    .sort((left, right) => (
      Number(right.id === selectedEventId) - Number(left.id === selectedEventId)
      || SEVERITY_RANK[right.severity] - SEVERITY_RANK[left.severity]
      || Date.parse(right.updatedAt || '') - Date.parse(left.updatedAt || '')
    ))
    .filter((event) => {
      const point = eventRepresentativePoint(event);
      if (!point) return false;
      if (!project) return event.id === selectedEventId;
      const screen = project(point);
      if (!screen) return false;
      const label = eventLabel(event);
      const fontSize = event.id === selectedEventId ? 11 : 9;
      const width = Math.min(220, Math.max(28, label.length * fontSize * 0.62));
      const candidate: ScreenBox = [screen.x + 5, screen.y - fontSize - 13, screen.x + 5 + width, screen.y - 2];
      if (event.id !== selectedEventId && overlaps(candidate)) return false;
      boxes.push(candidate);
      return true;
    })
    .slice(0, zoom < 4 ? 24 : zoom < 5 ? 60 : 120);
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
      characterSet: 'auto',
      pickable: false,
    }));
  }
  return layers;
}
