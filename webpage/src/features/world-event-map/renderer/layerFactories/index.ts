import type { LayersList } from '@deck.gl/core';
import type { GeoEvent } from '../../domain/types';
import type { WorldEventMapState } from '../../state/mapState';
import { createEventGeometryLayers } from './eventGeometryLayers';
import { createEventPointLayers } from './eventPointLayer';

export { type EventCluster } from './eventPointLayer';
export { isHazardEvent } from './shared';

export function createWorldEventLayers(
  events: GeoEvent[],
  state: WorldEventMapState,
  showLabels = true,
  viewport?: [number, number, number, number],
): LayersList {
  return [
    ...createEventGeometryLayers(events, state.selectedEventId),
    ...createEventPointLayers({
      events,
      zoom: state.zoom,
      selectedEventId: state.selectedEventId,
      showLabels,
      viewport,
    }),
  ];
}
