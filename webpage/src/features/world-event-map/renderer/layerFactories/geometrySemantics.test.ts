import { geoArea } from 'd3-geo';
import { normalizePolygonWinding } from '../SvgMapRenderer';
import { describe, expect, it } from 'vitest';
import type { GeoEvent } from '../../domain/types';
import { boundsIntersect, coordinateBounds, eventGeometryBounds, eventRepresentativePoint } from './shared';
const event = (geometry: GeoEvent['geometry'], properties = {}): GeoEvent => ({ id: 'geometry', title: 'geometry',
  category: 'natural-hazard', severity: 'warning', geometry, properties, sources: [], relatedMarketIds: [], limitations: [], locationPrecision: 'region' });
describe('map geometry is evidence, not a decorative marker', () => {
  it('preserves polar and dateline interiors without filling the world', () => {
    for (const ring of [ [[-180,-80],[-90,-80],[0,-80],[90,-80],[180,-80],[-180,-80]], [[179,10],[-179,10],[-179,12],[179,12],[179,10]] ]) {
      for (const coordinates of [ring, [...ring].reverse()]) {
        const normalized = normalizePolygonWinding({ type: 'Polygon', coordinates: [coordinates] });
        expect(geoArea(normalized)).toBeLessThan(0.1);
      }
    }
  });
  it('places a polygon summary inside its shell and outside its hole', () => {
    const point = eventRepresentativePoint(event({ type: 'Polygon', coordinates: [
      [[0,0],[10,0],[10,10],[0,10],[0,0]], [[2,2],[8,2],[8,8],[2,8],[2,2]],
    ] }))!;
    expect(point[0]).toBeGreaterThan(0); expect(point[0]).toBeLessThan(10);
    expect(point[0] > 2 && point[0] < 8 && point[1] > 2 && point[1] < 8).toBe(false);
  });
  it('does not present a track endpoint as an observed cyclone center', () => {
    const line = { type: 'LineString', coordinates: [[10,10],[20,20]] } as const;
    expect(eventRepresentativePoint(event(line as any))).toBeNull();
    expect(eventRepresentativePoint(event(line as any, { geometries: { observedPosition: { type: 'Point', coordinates: [12,13] } } }))).toEqual([12,13]);
  });
  it('keeps dateline bounds compact and intersects both sides', () => {
    const bounds = coordinateBounds([[179,10],[-179,12]])!;
    expect(bounds[2] - bounds[0]).toBe(2);
    expect(boundsIntersect(bounds, [-180,0,-178,20])).toBe(true);
    expect(boundsIntersect(bounds, [178,0,180,20])).toBe(true);
    expect(boundsIntersect(bounds, [-20,0,20,20])).toBe(false);
  });
  it('retains a forecast path inside the viewport even when its observed center is outside', () => {
    const bounds = eventGeometryBounds(event({ type: 'Point', coordinates: [-80,20] }, {
      geometries: { forecastTrack: { type: 'LineString', coordinates: [[-80,20],[-40,30]] } },
    }))!;
    expect(boundsIntersect(bounds, [-45,25,-35,35])).toBe(true);
  });
});
