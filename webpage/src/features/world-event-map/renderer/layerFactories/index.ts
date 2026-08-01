import type { LayersList } from '@deck.gl/core';
import type { GeoEvent } from '../../domain/types';
import type { WorldEventMapState } from '../../state/mapState';
import { createEventGeometryLayers } from './eventGeometryLayers';
import { createEventPointLayers } from './eventPointLayer';
import { createAviationLayers } from './aviationLayers';

export { type EventCluster } from './eventPointLayer';
export { isHazardEvent } from './shared';
export {
  aviationLayerStats,
  aviationLayerStatsForState,
  createAviationLayers,
} from './aviationLayers';

export type WorldEventStaticLayerSections = {
  geometry: LayersList;
  points: LayersList;
};

/**
 * Static event data is expensive to normalize and cluster.  Keep it separate
 * from the moving aviation overlay so a route runner does not rebuild every
 * hazard polygon, point and label on each animation tick.
 */
export function createWorldEventStaticLayerSections(
  events: GeoEvent[],
  state: WorldEventMapState,
  showLabels = true,
  viewport?: [number, number, number, number],
): WorldEventStaticLayerSections {
  return {
    geometry: createEventGeometryLayers(events, state.selectedEventId),
    points: createEventPointLayers({
      events,
      zoom: state.zoom,
      selectedEventId: state.selectedEventId,
      showLabels,
      viewport,
    }),
  };
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
