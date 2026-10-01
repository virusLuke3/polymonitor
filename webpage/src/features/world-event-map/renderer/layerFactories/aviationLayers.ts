import type { Layer, LayersList } from '@deck.gl/core';
import { IconLayer, PathLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import { MAP_SYMBOL_MASK_ATLAS, MAP_SYMBOL_MASK_ICON_MAPPING } from '../../config/mapSymbols';
import type { GeoEvent } from '../../domain/types';
import type { WorldEventMapState } from '../../state/mapState';
import {
  type AviationAircraftMarker,
  aviationAltitudeColor,
  aviationBudget,
  aviationLiveAircraftMarkers,
  type AviationMotionPoint,
  type AviationRenderData,
  aviationRouteTone,
  type AviationViewport,
  groupId,
  isWatch,
  numberProperty,
  routeMotionPointsForGroups,
  seededFlightPointsForGroups,
  selectAviationRenderData,
  stringProperty,
} from './aviationScene';
import { mapLabelFontFamily } from './shared';

const AVIATION_COUNT_CHARACTER_SET = '0123456789';
const AVIATION_HUB_CHARACTER_SET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-';

export type AviationStaticLayerSections = {
  routeLayers: LayersList;
  hubLayers: LayersList;
  aircraftLayers: LayersList;
  labelLayers: LayersList;
  markerLayers: LayersList;
  data: AviationRenderData;
};

function routeWidth(event: GeoEvent, selectedGroupId: string | null) {
  if (selectedGroupId && groupId(event, 'routeId') === selectedGroupId) return 2.4;
  const layer = stringProperty(event, 'layer');
  const base = layer === 'trunk' ? 1.25 : layer === 'international' ? 0.9 : 0.55;
  return Math.max(0.5, Math.min(2.2, base + numberProperty(event, 'trafficScore') / 130));
}

function selectedRouteId(data: AviationRenderData, selectedEventId: string | null) {
  const selected = selectedEventId
    ? data.routes.find((event) => event.id === selectedEventId)
    : null;
  return selected ? groupId(selected, 'routeId') : null;
}

function routeAlpha(
  event: GeoEvent,
  selectedId: string | null,
  selectedGroupId: string | null,
  normalAlpha: number,
  selectedAlpha: number,
) {
  if (!selectedGroupId) return normalAlpha;
  return event.id === selectedId || groupId(event, 'routeId') === selectedGroupId ? selectedAlpha : 36;
}

function createAviationRouteLayers(
  data: AviationRenderData,
  state: Pick<WorldEventMapState, 'selectedEventId' | 'zoom'>,
): LayersList {
  if (!data.routes.length) return [];
  const selectedGroupId = selectedRouteId(data, state.selectedEventId);
  const underlay = new PathLayer<GeoEvent>({
      id: 'aviation-route-underlay',
      data: data.routes,
      getPath: (event) => event.geometry?.type === 'LineString' ? event.geometry.coordinates : [],
      getColor: (event) => aviationRouteTone(event, routeAlpha(
        event, state.selectedEventId, selectedGroupId, 34, 96,
      )),
      getWidth: (event) => routeWidth(event, selectedGroupId) + 1.1,
      widthMinPixels: 1,
      widthMaxPixels: 5,
      jointRounded: true,
      capRounded: true,
      pickable: false,
    });
  const core = new PathLayer<GeoEvent>({
      id: 'aviation-route-core',
      data: data.routes,
      getPath: (event) => event.geometry?.type === 'LineString' ? event.geometry.coordinates : [],
      getColor: (event) => aviationRouteTone(event, routeAlpha(
        event, state.selectedEventId, selectedGroupId, 112, 235,
      )),
      getWidth: (event) => routeWidth(event, selectedGroupId),
      widthMinPixels: 0.65,
      widthMaxPixels: 3.5,
      jointRounded: true,
      capRounded: true,
      pickable: true,
    });
  // At world scale the thin semantic core is enough; a second full-route
  // underlay doubles tessellation and turns the overview into glowing bands.
  // Restore it once detail is useful or a route is explicitly selected.
  return state.zoom < 4 && !selectedGroupId ? [core] : [underlay, core];
}

function liveAircraftColor(
  marker: AviationAircraftMarker,
  selectedEventId: string | null,
): [number, number, number, number] {
  const event = marker.event;
  const selected = event.id === selectedEventId;
  const alpha = selected ? 245 : isWatch(event) ? 220 : 174;
  if (Boolean(event.properties.onGround)) return [120, 120, 120, Math.min(alpha, 170)];
  const [red, green, blue] = aviationAltitudeColor(numberProperty(event, 'baroAltitude'));
  return [red, green, blue, alpha];
}

function createAviationMarkerLayerSections(
  data: AviationRenderData,
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'selectedEventId'>,
) {
  const budget = aviationBudget(state.zoom, state.aviationLens);
  const hubLayers: Layer[] = [];
  const aircraftLayers: Layer[] = [];
  const labelLayers: Layer[] = [];
  if (data.liveAircraft.length) {
    const liveMarkers = aviationLiveAircraftMarkers(
      data.liveAircraft,
      state.zoom,
      state.selectedEventId,
    );
    aircraftLayers.push(new IconLayer<AviationAircraftMarker>({
      id: 'aviation-live-aircraft',
      data: liveMarkers,
      iconAtlas: MAP_SYMBOL_MASK_ATLAS,
      iconMapping: MAP_SYMBOL_MASK_ICON_MAPPING,
      getIcon: () => 'aircraft',
      getPosition: (marker) => marker.position,
      getSize: (marker) => marker.event.id === state.selectedEventId ? 17 : isWatch(marker.event) ? 15 : 12,
      getAngle: (marker) => -numberProperty(marker.event, 'heading'),
      getColor: (marker) => liveAircraftColor(marker, state.selectedEventId),
      sizeUnits: 'pixels',
      sizeMinPixels: 8,
      sizeMaxPixels: 28,
      pickable: true,
    }));
    const overlaps = liveMarkers.filter((marker) => marker.count > 1);
    if (overlaps.length) {
      labelLayers.push(new TextLayer<AviationAircraftMarker>({
        id: 'aviation-live-aircraft-counts',
        data: overlaps,
        getPosition: (marker) => marker.position,
        getText: (marker) => String(marker.count),
        getPixelOffset: [8, -8],
        getSize: 11,
        getColor: [225, 247, 250, 230],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'center',
        fontFamily: mapLabelFontFamily(),
        fontWeight: 800,
        characterSet: AVIATION_COUNT_CHARACTER_SET,
        pickable: false,
      }));
    }
  }
  if (data.hubs.length) {
    hubLayers.push(new ScatterplotLayer<GeoEvent>({
      id: 'aviation-hubs',
      data: data.hubs,
      getPosition: (event) => event.geometry?.type === 'Point' ? event.geometry.coordinates : [0, 0],
      getRadius: (event) => Math.max(26_000, Math.min(76_000, 18_000 + numberProperty(event, 'routeCount') * 34)),
      getFillColor: (event) => isWatch(event) ? [255, 177, 76, 135] : [24, 211, 238, 112],
      getLineColor: (event) => isWatch(event) ? [255, 220, 130, 230] : [87, 235, 255, 225],
      getLineWidth: 1.5,
      radiusMinPixels: 4,
      radiusMaxPixels: 14,
      lineWidthMinPixels: 1,
      stroked: true,
      pickable: true,
    }));
    labelLayers.push(new TextLayer<GeoEvent>({
      id: 'aviation-hub-labels',
      data: data.hubs.slice(0, budget.hubLabels),
      getPosition: (event) => event.geometry?.type === 'Point' ? event.geometry.coordinates : [0, 0],
      getText: (event) => stringProperty(event, 'code'),
      getPixelOffset: [9, 10],
      getSize: 9,
      getColor: [174, 233, 241, 195],
      getTextAnchor: 'start',
      getAlignmentBaseline: 'center',
      fontFamily: mapLabelFontFamily(),
      fontWeight: 900,
      characterSet: AVIATION_HUB_CHARACTER_SET,
      pickable: false,
    }));
  }
  return { hubLayers, aircraftLayers, labelLayers };
}

/** Builds immutable route/marker layers plus their precomputed animation data. */
export function createAviationStaticLayerSections(
  events: GeoEvent[],
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'aviationRiskSource' | 'selectedEventId'>,
  viewport?: AviationViewport,
): AviationStaticLayerSections {
  const data = selectAviationRenderData(events, state, viewport);
  const markerSections = createAviationMarkerLayerSections(data, state);
  return {
    routeLayers: createAviationRouteLayers(data, state),
    ...markerSections,
    markerLayers: [
      ...markerSections.hubLayers,
      ...markerSections.aircraftLayers,
      ...markerSections.labelLayers,
    ],
    data,
  };
}

/**
 * The only layers recreated during aviation animation. Their source groups are
 * stable, and their count is bounded by the current zoom-level budget.
 */
export function createAviationDynamicLayers(
  data: AviationRenderData,
  animationTime = 0,
  zoom = 1.25,
  selectedEventId: string | null = null,
  hoveredEventId: string | null = null,
): LayersList {
  const routeRunners = routeMotionPointsForGroups(
    data.routeMotionGroups,
    animationTime,
    selectedEventId,
    selectedRouteId(data, selectedEventId),
  );
  const flightPoints = seededFlightPointsForGroups(
    data.flightMotionGroups,
    animationTime,
    zoom,
    selectedEventId,
  );
  const layers: Layer[] = [];
  if (routeRunners.length) {
    layers.push(new ScatterplotLayer<AviationMotionPoint>({
      id: 'aviation-route-runners',
      data: routeRunners,
      getPosition: (point) => point.position,
      getRadius: 18_000,
      getFillColor: (point) => point.color,
      getLineColor: [4, 12, 18, 230],
      getLineWidth: 1,
      radiusMinPixels: 2,
      radiusMaxPixels: 4,
      lineWidthMinPixels: 1,
      stroked: true,
      pickable: false,
    }));
  }
  if (flightPoints.length) {
    layers.push(new IconLayer<AviationMotionPoint>({
      id: 'aviation-seeded-aircraft',
      data: flightPoints,
      iconAtlas: MAP_SYMBOL_MASK_ATLAS,
      iconMapping: MAP_SYMBOL_MASK_ICON_MAPPING,
      getIcon: () => 'aircraft',
      getPosition: (point) => point.position,
      getSize: (point) => point.size,
      getAngle: (point) => point.angle - 90,
      getColor: (point) => point.color,
      sizeUnits: 'pixels',
      // The motion canvas is intentionally excluded from deck.gl GPU picking.
      // DeckMapRenderer performs a bounded CPU proximity hit-test over these
      // points so moving aircraft retain hover/click without a second full
      // framebuffer readback on every pointer move.
      pickable: false,
    }));
    const hovered = hoveredEventId && hoveredEventId !== selectedEventId
      ? flightPoints.filter((point) => point.event.id === hoveredEventId)
      : [];
    if (hovered.length) {
      layers.push(new ScatterplotLayer<AviationMotionPoint>({
        id: 'aviation-seeded-hover-ring',
        data: hovered,
        getPosition: (point) => point.position,
        getRadius: 21_000,
        getLineColor: (point) => [point.color[0], point.color[1], point.color[2], 185],
        getLineWidth: 1.2,
        radiusMinPixels: 8,
        radiusMaxPixels: 17,
        lineWidthMinPixels: 1,
        filled: false,
        stroked: true,
        pickable: false,
      }));
    }
    const selected = selectedEventId
      ? flightPoints.filter((point) => point.event.id === selectedEventId)
      : [];
    if (selected.length) {
      layers.push(
        new ScatterplotLayer<AviationMotionPoint>({
          id: 'aviation-seeded-selected-ring-outer',
          data: selected,
          getPosition: (point) => point.position,
          getRadius: 28_000,
          getLineColor: (point) => [point.color[0], point.color[1], point.color[2], 235],
          getLineWidth: 1.6,
          radiusMinPixels: 11,
          radiusMaxPixels: 23,
          lineWidthMinPixels: 1.3,
          filled: false,
          stroked: true,
          pickable: false,
        }),
        new ScatterplotLayer<AviationMotionPoint>({
          id: 'aviation-seeded-selected-ring-inner',
          data: selected,
          getPosition: (point) => point.position,
          getRadius: 21_000,
          getLineColor: [220, 244, 248, 210],
          getLineWidth: 1.2,
          radiusMinPixels: 8,
          radiusMaxPixels: 18,
          lineWidthMinPixels: 1,
          filled: false,
          stroked: true,
          pickable: false,
        }),
      );
    }
    const overlaps = flightPoints.filter((point) => point.count > 1);
    if (overlaps.length) {
      layers.push(new TextLayer<AviationMotionPoint>({
        id: 'aviation-seeded-aircraft-counts',
        data: overlaps,
        getPosition: (point) => point.position,
        getText: (point) => String(point.count),
        getPixelOffset: [8, -8],
        getSize: 11,
        getColor: [225, 247, 250, 230],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'center',
        fontFamily: mapLabelFontFamily(),
        fontWeight: 800,
        characterSet: AVIATION_COUNT_CHARACTER_SET,
        pickable: false,
      }));
    }
  }
  return layers;
}

/** Compatibility composition for the SVG renderer and factory callers. */
export function createAviationLayers(
  events: GeoEvent[],
  state: WorldEventMapState,
  animationTime = 0,
  viewport?: AviationViewport,
): LayersList {
  const sections = createAviationStaticLayerSections(events, state, viewport);
  const dynamic = createAviationDynamicLayers(
    sections.data,
    animationTime,
    state.zoom,
    state.selectedEventId,
  ).filter((layer): layer is Layer => Boolean(layer) && !Array.isArray(layer));
  return [
    ...sections.routeLayers,
    ...dynamic.filter((layer) => layer.id === 'aviation-route-runners'),
    ...sections.hubLayers,
    ...dynamic.filter((layer) => layer.id === 'aviation-seeded-aircraft'),
    ...sections.aircraftLayers,
    ...dynamic.filter((layer) => layer.id.includes('-hover-') || layer.id.includes('-selected-')),
    ...sections.labelLayers,
    ...dynamic.filter((layer) => layer.id.endsWith('-counts')),
  ];
}
