import type { LayersList } from '@deck.gl/core';
import type { GeoEvent } from '../../domain/types';
import type { WorldEventMapState } from '../../state/mapState';
import { createEventGeometryLayers } from './eventGeometryLayers';
import { createEventPointLayers } from './eventPointLayer';
import { createAviationLayers } from './aviationLayers';

export { type EventCluster } from './eventPointLayer';
export { isHazardEvent } from './shared';
export { aviationLayerStats, aviationLayerStatsForState } from './aviationLayers';

export function createWorldEventLayers(
  events: GeoEvent[],
  state: WorldEventMapState,
  showLabels = true,
  viewport?: [number, number, number, number],
  animationTime = 0,
  animate = true,
): LayersList {
  return [
    ...createAviationLayers(events, state, animationTime),
    ...createEventGeometryLayers(events, state.selectedEventId),
    ...createEventPointLayers({
      events,
      zoom: state.zoom,
      selectedEventId: state.selectedEventId,
      showLabels,
      viewport,
      animationTime,
      animate,
    }),
  ];
}
