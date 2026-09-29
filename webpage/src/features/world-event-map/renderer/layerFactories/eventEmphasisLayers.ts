import type { Layer, LayersList } from '@deck.gl/core';
import { PathLayer, ScatterplotLayer } from '@deck.gl/layers';
import type { GeoEvent } from '../../domain/types';
import type { EventCluster } from './eventClusters';
import {
  type EventEmphasisTarget,
  type HazardPulseTarget,
  hazardPulseTargets,
  type RecentPulseTarget,
  targetForEvent,
} from './eventEmphasis';
import { eventColor } from './shared';

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
  const { status, recent } = hazardPulseTargets(events, selectedEventId, firstSeenAt, pulseTime, zoom);
  const layers: Layer[] = [];
  if (status.length) {
    layers.push(new ScatterplotLayer<HazardPulseTarget>({
      id: 'world-event-status-pulses',
      data: status,
      getPosition: (target) => target.position,
      getRadius: (target) => {
        const wave = 0.5 + 0.5 * Math.sin(
          pulseTime / (target.strength === 'warning' ? 900 : 400),
        );
        return target.radius * (target.strength === 'warning' ? 1.35 + wave * 0.25 : 1.45 + wave * 0.75);
      },
      getLineColor: (target) => eventColor(target.event, target.strength === 'warning' ? 58 : 126),
      getLineWidth: (target) => target.strength === 'warning' ? 1 : 1.5,
      radiusMinPixels: 8,
      radiusMaxPixels: 34,
      lineWidthMinPixels: 1,
      filled: false,
      stroked: true,
      pickable: false,
      updateTriggers: {
        getRadius: pulseTime,
        getLineColor: pulseTime,
      },
    }));
  }
  if (recent.length) {
    layers.push(new ScatterplotLayer<RecentPulseTarget>({
      id: 'world-event-recent-pulses',
      data: recent,
      getPosition: (target) => target.position,
      getRadius: (target) => {
        const wave = 0.5 + 0.5 * Math.sin(pulseTime / 318);
        return target.radius * (1.6 + wave * 1.05);
      },
      getLineColor: (target) => eventColor(target.event, Math.round(150 * target.fade)),
      getLineWidth: 1.5,
      radiusMinPixels: 9,
      radiusMaxPixels: 38,
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
      getRadius: (cluster) => Math.max(52_000, Math.log2(cluster.count + 1) * 48_000) * 1.18,
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
      getRadius: (target) => target.radius * 1.38,
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
    layers.push(
      new ScatterplotLayer<EventEmphasisTarget>({
        id: 'world-event-selected-ring-outer',
        data: [selected],
        getPosition: (target) => target.position,
        getRadius: (target) => target.radius * 2.05,
        getLineColor: (target) => eventColor(target.event, 235),
        getLineWidth: 1.7,
        radiusMinPixels: 10,
        radiusMaxPixels: 36,
        lineWidthMinPixels: 1.4,
        filled: false,
        stroked: true,
        pickable: false,
      }),
      new ScatterplotLayer<EventEmphasisTarget>({
        id: 'world-event-selected-ring-inner',
        data: [selected],
        getPosition: (target) => target.position,
        getRadius: (target) => target.radius * 1.48,
        getLineColor: [220, 244, 248, 210],
        getLineWidth: 1.25,
        radiusMinPixels: 8,
        radiusMaxPixels: 28,
        lineWidthMinPixels: 1,
        filled: false,
        stroked: true,
        pickable: false,
      }),
    );
  }
  return layers;
}
