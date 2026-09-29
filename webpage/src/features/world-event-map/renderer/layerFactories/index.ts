import type { LayersList } from '@deck.gl/core';
import type { GeoEvent } from '../../domain/types';
import type { WorldEventMapState } from '../../state/mapState';
import { createAviationLayers } from './aviationLayers';
import { type EventClusterIndex, type LabelProjection, type ScreenBox } from './eventClusters';
import { createEventGeometryLayers } from './eventGeometryLayers';
import { createEventPointLayers } from './eventPointLayer';

export {
  createAviationDynamicLayers,
  createAviationLayers,
  createAviationStaticLayerSections,
  type AviationStaticLayerSections,
} from './aviationLayers';
export {
  aviationLayerStats,
  aviationLayerStatsForState,
  aviationLiveAircraftMarkers,
  type AviationMotionPoint,
  type AviationRenderData,
  type AviationViewport,
} from './aviationScene';
export { EventClusterIndex, type EventCluster } from './eventClusters';
export {
  eventRepresentativePoint,
  hasAnimatedHazardPulse,
  hazardPulseTargets,
  RECENT_EVENT_PULSE_MS,
  selectEventPulseCandidates,
} from './eventEmphasis';
export { createEventInteractionLayers, createEventPulseLayers } from './eventEmphasisLayers';
export { isHazardEvent } from './shared';

export type WorldEventStaticLayerSections = {
  geometry: LayersList;
  points: LayersList;
};

/**
 * Static event data is expensive to normalize and cluster.  Keep it separate
 * from the moving aviation overlay so a route runner does not rebuild every
 * hazard polygon, point and label on each animation tick.
 */
function createWorldEventStaticLayerSections(
  events: GeoEvent[],
  state: WorldEventMapState,
  showLabels = true,
  viewport?: [number, number, number, number],
  clusterIndex?: EventClusterIndex,
): WorldEventStaticLayerSections {
  return {
    geometry: createEventGeometryLayers(events, state.selectedEventId, state.zoom, undefined, viewport),
    points: createEventPointLayers({
      events,
      zoom: state.zoom,
      selectedEventId: state.selectedEventId,
      showLabels,
      viewport,
      clusterIndex,
    }),
  };
}

export function createWorldEventGeometryLayers(
  events: GeoEvent[],
  selectedEventId: string | null,
  zoom: number,
  beforeId?: string,
  viewport?: [number, number, number, number],
) {
  return createEventGeometryLayers(events, selectedEventId, zoom, beforeId, viewport);
}

export function createWorldEventPointLayers(
  events: GeoEvent[],
  state: WorldEventMapState,
  viewport: [number, number, number, number] | undefined,
  clusterIndex: EventClusterIndex,
  project?: LabelProjection,
  occupiedScreenBoxes?: ScreenBox[],
  measureLabel?: (text: string, size: number) => number,
  screenSize?: [number, number],
) {
  return createEventPointLayers({
    events,
    zoom: state.zoom,
    selectedEventId: state.selectedEventId,
    showLabels: true,
    viewport,
    clusterIndex,
    project,
    occupiedScreenBoxes,
    measureLabel,
    screenSize,
  });
}

export function createWorldEventLayers(
  events: GeoEvent[],
  state: WorldEventMapState,
  showLabels = true,
  viewport?: [number, number, number, number],
  animationTime = 0,
): LayersList {
  const sections = createWorldEventStaticLayerSections(events, state, showLabels, viewport);
  return [
    // Risk and hazard polygons are the base thematic overlay.  Aviation must
    // sit above them; putting it first let translucent country fills mute the
    // route cores and runners in the final compositing order.
    ...sections.geometry,
    ...createAviationLayers(events, state, animationTime),
    ...sections.points,
  ];
}
