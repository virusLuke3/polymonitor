import type { LayersList } from '@deck.gl/core';
import { ScatterplotLayer } from '@deck.gl/layers';
import type { GeoEvent } from '../../domain/types';
import { eventObservationTextureCandidates } from './eventObservations';
import { continuousMetricRadiusMeters, eventRepresentativePoint, SEVERITY_COLORS } from './shared';

export function createEventObservationLayer(
  events: GeoEvent[],
  zoom: number,
  selectedEventId: string | null,
  viewport?: [number, number, number, number],
): LayersList {
  const observations = eventObservationTextureCandidates(
    events,
    zoom,
    selectedEventId,
    viewport,
  );
  if (!observations.length) return [];
  return [new ScatterplotLayer<GeoEvent>({
    id: 'world-event-observation-texture',
    data: observations,
    getPosition: (event) => eventRepresentativePoint(event)!,
    getRadius: (event) => continuousMetricRadiusMeters(event) || 7_000,
    getFillColor: (event) => {
      const [red, green, blue] = SEVERITY_COLORS[event.severity];
      const alpha = event.severity === 'warning' ? 92 : event.severity === 'watch' ? 68 : 46;
      return [red, green, blue, alpha];
    },
    radiusMinPixels: zoom < 2.5 ? 1.5 : 1.8,
    radiusMaxPixels: zoom < 2.5 ? 4 : 5.5,
    pickable: false,
    stroked: false,
    filled: true,
  })];
}
