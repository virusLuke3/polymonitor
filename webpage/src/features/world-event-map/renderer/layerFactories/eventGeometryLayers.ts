import { GeoJsonLayer, PathLayer, ScatterplotLayer } from '@deck.gl/layers';
import type { LayersList } from '@deck.gl/core';
import type { GeoEvent } from '../../domain/types';
import { isHazardEvent } from './shared';
import { createCountryRiskLayers, isCountryRiskArea } from './countryRiskLayers';
import { eventColor } from './shared';

type CycloneCenter = {
  event: GeoEvent;
  coordinates: [number, number];
};

export function createEventGeometryLayers(
  events: GeoEvent[],
  selectedEventId: string | null,
): LayersList {
  const lines = events.filter((event) => (
    event.properties.mapEntity !== 'air-route'
    && event.properties.mapEntity !== 'air-flight'
    && event.geometry?.type === 'LineString'
  ));
  const cycloneCenters: CycloneCenter[] = lines.flatMap((event) => {
    if (!isHazardEvent(event) || event.hazardKind !== 'tropical-cyclone' || event.geometry?.type !== 'LineString') {
      return [];
    }
    const coordinates = event.geometry.coordinates[event.geometry.coordinates.length - 1];
    return coordinates ? [{ event, coordinates }] : [];
  });
  const hazardAreas = events.filter((event) => (
    isHazardEvent(event)
    && (event.geometry?.type === 'Polygon' || event.geometry?.type === 'MultiPolygon')
  ));
  const contextAreas = events.filter((event) => (
    !isHazardEvent(event)
    && !isCountryRiskArea(event)
    && (event.geometry?.type === 'Polygon' || event.geometry?.type === 'MultiPolygon')
  ));
  const layers: LayersList = [];

  layers.push(...createCountryRiskLayers(events, selectedEventId));

  if (hazardAreas.length) {
    layers.push(new GeoJsonLayer({
      id: 'world-event-hazard-areas',
      data: {
        type: 'FeatureCollection',
        features: hazardAreas.map((event) => ({
          type: 'Feature',
          id: event.id,
          properties: { event },
          geometry: event.geometry,
        })),
      } as any,
      filled: true,
      stroked: true,
      getFillColor: (feature) => eventColor(feature.properties?.event as GeoEvent, 64),
      getLineColor: (feature) => eventColor(feature.properties?.event as GeoEvent, 220),
      getLineWidth: (feature) => feature.properties?.event?.id === selectedEventId ? 2.8 : 1.35,
      lineWidthMinPixels: 1,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 82],
    }));
  }

  if (contextAreas.length) {
    layers.push(new GeoJsonLayer({
      id: 'world-event-context-areas',
      data: {
        type: 'FeatureCollection',
        features: contextAreas.map((event) => ({
          type: 'Feature',
          id: event.id,
          properties: { event },
          geometry: event.geometry,
        })),
      } as any,
      filled: true,
      stroked: true,
      getFillColor: (feature) => eventColor(feature.properties?.event as GeoEvent, 38),
      getLineColor: (feature) => eventColor(feature.properties?.event as GeoEvent, 185),
      getLineWidth: (feature) => feature.properties?.event?.id === selectedEventId ? 2.5 : 1,
      lineWidthMinPixels: 1,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 72],
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
      highlightColor: [255, 250, 198, 128],
    }));
  }
  if (cycloneCenters.length) {
    layers.push(new ScatterplotLayer<CycloneCenter>({
      id: 'world-event-cyclone-centers',
      data: cycloneCenters,
      getPosition: (center) => center.coordinates,
      getRadius: (center) => center.event.id === selectedEventId ? 34_000 : 24_000,
      getFillColor: (center) => eventColor(center.event, 245),
      getLineColor: [235, 250, 255, 255],
      getLineWidth: (center) => center.event.id === selectedEventId ? 2.8 : 1.5,
      radiusMinPixels: 7,
      radiusMaxPixels: 22,
      lineWidthMinPixels: 1.2,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 112],
      stroked: true,
    }));
  }
  return layers;
}
