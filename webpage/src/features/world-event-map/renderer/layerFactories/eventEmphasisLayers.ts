import type { Layer, LayersList } from '@deck.gl/core';
import { PathLayer, ScatterplotLayer } from '@deck.gl/layers';
import type { GeoEvent } from '../../domain/types';
import type { EventCluster } from './eventClusters';
import {
  type EventEmphasisTarget,
  hazardPulseTargets,
  type RecentPulseTarget,
  targetForEvent,
} from './eventEmphasis';
import { eventColor, clusterMarkerSize } from './shared';

export function createEventPulseLayers({
  events,
  selectedEventId,
  firstSeenAt,
  pulseTime,
  zoom = Number.POSITIVE_INFINITY,
}: {
  events: readonly GeoEvent[];
  selectedEventId: string | null;
  firstSeenAt: ReadonlyMap<string, number>;
  pulseTime: number;
  zoom?: number;
}): LayersList {
  const { recent } = hazardPulseTargets(events, selectedEventId, firstSeenAt, pulseTime, zoom);
  const layers: Layer[] = [];
  if (recent.length) {
    layers.push(new ScatterplotLayer<RecentPulseTarget>({
      id: 'world-event-recent-pulses',
      data: recent,
      getPosition: (target) => target.position,
      getRadius: target => target.radius + 3 + target.phase * 6,
      radiusUnits: 'pixels',
      getLineColor: target => eventColor(target.event, Math.round(120 * target.fade * (1 - target.phase))),
      getLineWidth: 1.5,
      radiusMinPixels: 0,
      radiusMaxPixels: 18,
      lineWidthMinPixels: 1.25,
      filled: false,
      stroked: true,
      pickable: false,
      updateTriggers: {
        getRadius: pulseTime,
        getLineColor: pulseTime,
      },
    }));
  }
  return layers;
}

function lineEvent(events: readonly GeoEvent[], id: string | null) {
  return id ? events.find((event) => event.id === id && event.geometry?.type === 'LineString') || null : null;
}

function pointTarget(events: readonly GeoEvent[], id: string | null) {
  if (!id) return null;
  const event = events.find((candidate) => candidate.id === id);
  return event ? targetForEvent(event) : null;
}

/** Explicit restrained hover and persistent selection; no deck.gl autoHighlight. */
export function createEventInteractionLayers(
  events: readonly GeoEvent[],
  selectedEventId: string | null,
  hoveredEventId: string | null,
  hoveredCluster: EventCluster | null = null,
): LayersList {
  const layers: Layer[] = [];
  if (hoveredCluster) {
    layers.push(new ScatterplotLayer<EventCluster>({
      id: 'world-event-cluster-hover-ring',
      data: [hoveredCluster],
      getPosition: (cluster) => cluster.coordinates,
      getRadius: cluster => clusterMarkerSize(cluster.count) / 2 + 2,
      radiusUnits: 'pixels',
      getLineColor: (cluster) => [cluster.color[0], cluster.color[1], cluster.color[2], 190],
      getLineWidth: 1.2,
      radiusMinPixels: 11,
      radiusMaxPixels: 34,
      lineWidthMinPixels: 1,
      filled: false,
      stroked: true,
      pickable: false,
    }));
  }
  const hoveredLine = hoveredEventId !== selectedEventId ? lineEvent(events, hoveredEventId) : null;
  if (hoveredLine) {
    layers.push(new PathLayer<GeoEvent>({
      id: 'world-event-hover-path',
      data: [hoveredLine],
      getPath: (event) => event.geometry?.type === 'LineString' ? event.geometry.coordinates : [],
      getColor: (event) => eventColor(event, 170),
      getWidth: 2.6,
      widthUnits: 'pixels',
      widthMinPixels: 1.4,
      widthMaxPixels: 5,
      pickable: false,
    }));
  }
  const selectedLineCandidate = lineEvent(events, selectedEventId);
  const selectedLineEntity = String(selectedLineCandidate?.properties.mapEntity || '');
  const selectedLine = selectedLineEntity === 'air-route' || selectedLineEntity === 'air-flight'
    ? null
    : selectedLineCandidate;
  if (selectedLine) {
    layers.push(new PathLayer<GeoEvent>({
      id: 'world-event-selected-path-outline',
      data: [selectedLine],
      getPath: (event) => event.geometry?.type === 'LineString' ? event.geometry.coordinates : [],
      getColor: (event) => eventColor(event, 225),
      getWidth: 3.4,
      widthUnits: 'pixels',
      widthMinPixels: 2,
      widthMaxPixels: 6,
      pickable: false,
    }));
  }
  const hovered = hoveredEventId !== selectedEventId ? pointTarget(events, hoveredEventId) : null;
  if (hovered) {
    layers.push(new ScatterplotLayer<EventEmphasisTarget>({
      id: 'world-event-hover-ring',
      data: [hovered],
      getPosition: (target) => target.position,
      getRadius: target => target.radius + 2,
      radiusUnits: 'pixels',
      getLineColor: (target) => eventColor(target.event, 190),
      getLineWidth: 1.2,
      radiusMinPixels: 7,
      radiusMaxPixels: 25,
      lineWidthMinPixels: 1,
      filled: false,
      stroked: true,
      pickable: false,
    }));
  }
  const selected = pointTarget(events, selectedEventId);
  if (selected) {
    layers.push(new ScatterplotLayer<EventEmphasisTarget>({
      id: 'world-event-selected-ring-outer', data: [selected],
      getPosition: target => target.position, getRadius: target => target.radius + 3,
      radiusUnits: 'pixels', lineWidthUnits: 'pixels', getLineWidth: 1.25,
      getLineColor: [235, 241, 245, 240], filled: false, stroked: true, pickable: false,
    }));
  }
  return layers;
}
