import type { Layer, LayersList } from '@deck.gl/core';
import { IconLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import { worldEventLayerById, worldEventLayerIdForEvent } from '../../config/layerRegistry';
import {
  MAP_SYMBOL_MASK_ATLAS, MAP_SYMBOL_MASK_ICON_MAPPING, mapSymbolForEvent,
} from '../../config/mapSymbols';
import type { GeoEvent } from '../../domain/types';
import {
  type EventCluster,
  EventClusterIndex,
  type LabelProjection,
  type ScreenBox,
  SEVERITY_RANK,
} from './eventClusters';
import { createEventObservationLayer } from './eventObservationLayer';
import {
  eventLabel,
  eventRepresentativePoint,
  mapLabelFontFamily,
  eventColor,
  markerSize,
  clusterMarkerSize,
} from './shared';

export function createEventPointLayers({
  events,
  zoom,
  selectedEventId,
  showLabels,
  viewport,
  clusterIndex,
  project,
  occupiedScreenBoxes = [],
  measureLabel,
  screenSize,
}: {
  events: GeoEvent[];
  zoom: number;
  selectedEventId: string | null;
  showLabels: boolean;
  viewport?: [number, number, number, number];
  clusterIndex?: EventClusterIndex;
  project?: LabelProjection;
  occupiedScreenBoxes?: ScreenBox[];
  measureLabel?: (text: string, size: number) => number;
  screenSize?: [number, number];
}): LayersList {
  const index = clusterIndex || new EventClusterIndex();
  index.update(events);
  const { singles, clusters } = index.query(zoom, selectedEventId, viewport);
  const layers: Layer[] = [
    ...createEventObservationLayer(events, zoom, selectedEventId, viewport),
  ].filter((layer): layer is Layer => Boolean(layer) && !Array.isArray(layer));

  if (clusters.length) {
    layers.push(new ScatterplotLayer<EventCluster>({
      id: 'world-event-clusters', data: clusters,
      getPosition: cluster => cluster.coordinates,
      getRadius: cluster => clusterMarkerSize(cluster.count) / 2,
      getFillColor: cluster => [...cluster.color.slice(0, 3), 235] as [number, number, number, number],
      getLineColor: [15, 18, 21, 255], getLineWidth: 1,
      radiusUnits: 'pixels', lineWidthUnits: 'pixels', filled: true, stroked: true,
      pickable: true, autoHighlight: false,
    }));
    layers.push(new TextLayer<EventCluster>({
      id: 'world-event-cluster-counts', data: clusters,
      getPosition: cluster => cluster.coordinates, getText: cluster => String(cluster.count),
      getSize: 12, getColor: [12, 15, 18, 255], getTextAnchor: 'middle', getAlignmentBaseline: 'center',
      fontFamily: mapLabelFontFamily(), fontWeight: 600, characterSet: 'auto', pickable: false,
    }));
  }
  if (singles.length) {
    layers.push(new IconLayer<GeoEvent>({
      id: 'world-event-points', data: singles,
      iconAtlas: MAP_SYMBOL_MASK_ATLAS, iconMapping: MAP_SYMBOL_MASK_ICON_MAPPING,
      getIcon: mapSymbolForEvent, getPosition: event => eventRepresentativePoint(event)!,
      getSize: event => markerSize(event, selectedEventId), getColor: event => eventColor(event, 245),
      sizeUnits: 'pixels', sizeMinPixels: 10, sizeMaxPixels: 20,
      alphaCutoff: 0.05, pickable: true, autoHighlight: false,
    }));
  }

  const labelFor = (event: GeoEvent) => event.id === selectedEventId ? event.title.slice(0, 64) : eventLabel(event);
  const labelCandidates = showLabels
    ? singles
      .filter((event) => {
        const layerId = worldEventLayerIdForEvent(event);
        const labelMinZoom = layerId ? worldEventLayerById(layerId)?.labelMinZoom ?? 3 : 3;
        return event.id === selectedEventId || (zoom >= labelMinZoom
          && ( event.severity === 'critical'
            || (event.category === 'natural-hazard' && (zoom >= 4 || event.severity === 'warning'))));
      })
    : [];
  const boxes: ScreenBox[] = [...occupiedScreenBoxes];
  if (project) {
    for (const event of singles) {
      const point = eventRepresentativePoint(event);
      const screen = point ? project(point) : null;
      if (!screen) continue;
      const radius = markerSize(event, selectedEventId) / 2 + 2;
      boxes.push([screen.x - radius, screen.y - radius, screen.x + radius, screen.y + radius]);
    }
    for (const cluster of clusters) {
      const screen = project(cluster.coordinates);
      if (!screen) continue;
      const radius = clusterMarkerSize(cluster.count) / 2 + 5;
      boxes.push([screen.x - radius, screen.y - radius, screen.x + radius, screen.y + radius]);
    }
  }
  const overlaps = (candidate: ScreenBox) => boxes.some((box) => !(
    candidate[2] < box[0] || candidate[0] > box[2] || candidate[3] < box[1] || candidate[1] > box[3]
  ));
  const placements = new Map<string, { offset: [number, number]; anchor: "start" | "end"; baseline: "top" | "bottom" }>();
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
      const label = labelFor(event);
      const fontSize = event.id === selectedEventId ? 13 : 11;
      // The renderer measures the loaded font. No DOM or second layout engine here.
      const width = measureLabel?.(label, fontSize) ?? 220;
      const gap = markerSize(event, selectedEventId) / 2 + 4;
      const candidates = [
        { offset: [gap, -gap] as [number, number], anchor: 'start' as const, baseline: 'bottom' as const },
        { offset: [gap, gap] as [number, number], anchor: 'start' as const, baseline: 'top' as const },
        { offset: [-gap, -gap] as [number, number], anchor: 'end' as const, baseline: 'bottom' as const },
        { offset: [-gap, gap] as [number, number], anchor: 'end' as const, baseline: 'top' as const },
      ];
      for (const placement of candidates) {
        const x = screen.x + placement.offset[0] - (placement.anchor === 'end' ? width : 0);
        const y = screen.y + placement.offset[1] - (placement.baseline === 'bottom' ? fontSize + 3 : 0);
        const box: ScreenBox = [x, y, x + width, y + fontSize + 3];
        if (screenSize && (x < 4 || y < 4 || box[2] > screenSize[0] - 4 || box[3] > screenSize[1] - 4)) continue;
        if (overlaps(box)) continue;
        boxes.push(box); placements.set(event.id, placement); return true;
      }
      // A selected title has priority over other markers; keep its measured
      // box inside the map and avoid fixed controls/inspector when possible.
      if (event.id === selectedEventId && screenSize) {
        let x = Math.max(4, Math.min(screen.x + gap, screenSize[0] - width - 4));
        let y = Math.max(4, Math.min(screen.y - fontSize - gap, screenSize[1] - fontSize - 7));
        for (const box of occupiedScreenBoxes) {
          if (x < box[2] && x + width > box[0] && y < box[3] && y + fontSize + 3 > box[1]) {
            x = Math.max(4, box[0] - width - 4);
          }
        }
        placements.set(event.id, { offset: [x - screen.x, y - screen.y], anchor: 'start', baseline: 'top' });
        boxes.push([x, y, x + width, y + fontSize + 3]);
        return true;
      }
      return false;
    })
    .slice(0, zoom < 4 ? 24 : zoom < 5 ? 60 : 120);
  if (labeled.length) {
    layers.push(new TextLayer<GeoEvent>({
      id: 'world-event-labels',
      data: labeled,
      getPosition: (event) => eventRepresentativePoint(event)!,
      getText: labelFor,
      getPixelOffset: event => placements.get(event.id)?.offset ?? [7, -8],
      getSize: (event) => event.id === selectedEventId ? 13 : 11,
      getColor: [226, 231, 229, 220],
      getTextAnchor: event => placements.get(event.id)?.anchor ?? 'start',
      getAlignmentBaseline: event => placements.get(event.id)?.baseline ?? 'bottom',
      fontFamily: mapLabelFontFamily(),
      fontWeight: 500,
      characterSet: 'auto',
      pickable: false,
    }));
  }
  return layers;
}
