import { GeoJsonLayer, PathLayer } from '@deck.gl/layers';
import type { LayersList } from '@deck.gl/core';
import type { GeoEvent } from '../../domain/types';
import { eventColor } from './shared';

export function createEventGeometryLayers(
  events: GeoEvent[],
  selectedEventId: string | null,
): LayersList {
  const lines = events.filter((event) => (
    event.properties.mapEntity !== 'air-route'
    && event.properties.mapEntity !== 'air-flight'
    && event.geometry?.type === 'LineString'
  ));
  const areas = events.filter((event) => (
    event.geometry?.type === 'Polygon' || event.geometry?.type === 'MultiPolygon'
  ));
  const layers: LayersList = [];

  if (areas.length) {
    layers.push(new GeoJsonLayer({
      id: 'world-event-areas',
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
      getFillColor: (feature) => eventColor(feature.properties?.event as GeoEvent, 48),
      getLineColor: (feature) => eventColor(feature.properties?.event as GeoEvent, 220),
      getLineWidth: (feature) => feature.properties?.event?.id === selectedEventId ? 2.5 : 1,
      lineWidthMinPixels: 1,
      pickable: true,
      autoHighlight: true,
    }));
  }

  if (lines.length) {
    layers.push(new PathLayer<GeoEvent>({
      id: 'world-event-paths',
      data: lines,
      getPath: (event) => event.geometry?.type === 'LineString' ? event.geometry.coordinates : [],
      getColor: (event) => eventColor(event, event.id === selectedEventId ? 240 : 165),
      getWidth: (event) => event.id === selectedEventId ? 2.4 : 1.5,
      widthMinPixels: 0.6,
      widthMaxPixels: 5,
      jointRounded: true,
      capRounded: true,
      pickable: true,
      autoHighlight: true,
    }));
  }
  return layers;
}
