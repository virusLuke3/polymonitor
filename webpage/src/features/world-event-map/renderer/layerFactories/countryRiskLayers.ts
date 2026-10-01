import { GeoJsonLayer } from '@deck.gl/layers';
import type { LayersList } from '@deck.gl/core';
import type { GeoEvent } from '../../domain/types';

import { countryRiskColor, isCountryRiskArea } from './shared';
export { countryRiskColor, isCountryRiskArea } from './shared';

export function createCountryRiskLayers(events: GeoEvent[], selectedEventId: string | null, beforeId?: string): LayersList {
  const areas = events.filter((event) => (
    isCountryRiskArea(event)
    && (event.geometry?.type === 'Polygon' || event.geometry?.type === 'MultiPolygon')
  ));
  if (!areas.length) return [];

  return [new GeoJsonLayer({
    id: 'world-event-country-risk',
    data: {
      type: 'FeatureCollection',
      features: areas.map((event) => ({
        type: 'Feature',
        id: event.id,
        properties: { event },
        geometry: event.geometry,
      })),
    } as any,
    filled: true,
    stroked: true,
    getFillColor: (feature) => countryRiskColor(
      feature.properties?.event as GeoEvent,
      feature.properties?.event?.id === selectedEventId ? 64 : 25,
    ),
    getLineColor: (feature) => countryRiskColor(
      feature.properties?.event as GeoEvent,
      feature.properties?.event?.id === selectedEventId ? 230 : 80,
    ),
    getLineWidth: (feature) => feature.properties?.event?.id === selectedEventId ? 1.8 : 0.5,
    lineWidthUnits: 'pixels',
    lineWidthMinPixels: 0.5,
    beforeId,
    wrapLongitude: true,
    pickable: true,
    autoHighlight: false,
  })];
}
