import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { FeatureCollection } from 'geojson';
import { buildCountryGeometryIndex, normalizeCountryIdentity } from './countryGeometry';
import { eventMatchesCountry, filterWorldEventMapEvents } from '../state/selectors';
import type { GeoEvent } from './types';

const collection: FeatureCollection = {
  type: 'FeatureCollection',
  features: [{
    type: 'Feature',
    properties: {
      name: 'United States of America',
      'ISO3166-1-Alpha-2': 'US',
      'ISO3166-1-Alpha-3': 'USA',
    },
    geometry: {
      type: 'Polygon',
      coordinates: [[[-100, 30], [-90, 30], [-90, 40], [-100, 30]]],
    },
  }],
};

describe('country geometry identity', () => {
  it('keeps a neighbouring national polygon out of the brief and filter despite a shared border', () => {
    const real = JSON.parse(readFileSync(new URL('../../../../public/map-data/world-countries.geojson', import.meta.url), 'utf8')) as FeatureCollection;
    const index = buildCountryGeometryIndex(real);
    const event: GeoEvent = {id:'country-risk:MX', category:'country-risk', title:'Mexico evidence', summary:'',
      severity:'watch', countryCode:'MX', geometry:index.resolve('MX')!.geometry,
      sources:[], limitations:[], relatedMarketIds:[], properties:{}};
    expect(index.intersects('US', event.geometry!)).toBe(true);
    expect(eventMatchesCountry(event, 'US', index)).toBe(false);
    expect(eventMatchesCountry(event, 'MX', index)).toBe(true);
    expect(filterWorldEventMapEvents([event], {timeRange:'all',severities:['watch'],countryCode:'US'}, Date.now(), index)).toEqual([]);
    expect(eventMatchesCountry({...event,countryCode:undefined,properties:{countryCodes:['US','MX']}}, 'US', index)).toBe(true);
    expect(eventMatchesCountry({...event,countryCode:undefined,geometry:{type:'Point',coordinates:[-100,38]}}, 'US', index)).toBe(true);
  });
  it('resolves names, ISO codes and conservative aliases to the same polygon', () => {
    const index = buildCountryGeometryIndex(collection);
    expect(index.resolve('US')?.iso3).toBe('USA');
    expect(index.resolve('USA')?.iso2).toBe('US');
    expect(index.resolve('United States')?.geometry.type).toBe('Polygon');
  });

  it('rejects global and unknown labels instead of inventing coordinates', () => {
    const index = buildCountryGeometryIndex(collection);
    expect(index.resolve('Global')).toBeNull();
    expect(index.resolve('Acme Corporation')).toBeNull();
  });

  it('resolves UCDP country labels against shipped boundaries without resolving combined topics', () => {
    const real = JSON.parse(readFileSync(new URL('../../../../public/map-data/world-countries.geojson', import.meta.url), 'utf8')) as FeatureCollection;
    const index = buildCountryGeometryIndex(real);
    for (const [name, code] of Object.entries({
      'DR Congo (Zaire)': 'CD', 'Myanmar (Burma)': 'MM', 'Russia (Soviet Union)': 'RU',
      'Yemen (North Yemen)': 'YE', 'Cambodia (Kampuchea)': 'KH',
    })) expect(index.resolve(name)?.iso2).toBe(code);
    expect(index.resolve('ISRAEL / GAZA')).toBeNull();
  });

  it('normalizes punctuation without conflating arbitrary entities', () => {
    expect(normalizeCountryIdentity('Côte d’Ivoire')).toBe('cote d ivoire');
  });

  it('locates points and intersects event polygons without requiring fabricated country fields', () => {
    const index = buildCountryGeometryIndex(collection);
    expect(index.locate([-95, 34])?.iso2).toBe('US');
    expect(index.locate([10, 10])).toBeNull();
    expect(index.intersects('US', { type: 'Point', coordinates: [-95, 34] })).toBe(true);
    expect(index.intersects('US', {
      type: 'Polygon',
      coordinates: [[[-96, 32], [-92, 32], [-92, 36], [-96, 32]]],
    })).toBe(true);
    expect(index.intersects('US', { type: 'Point', coordinates: [10, 10] })).toBe(false);
  });
});

 it('indexes the source regional identifier without changing boundary coordinates', () => {
  const data = JSON.parse(readFileSync(new URL('../../../../public/map-data/world-countries.geojson', import.meta.url), 'utf8')) as FeatureCollection;
  const original = data.features.find(f => f.properties?.['ISO3166-1-Alpha-2'] === 'CN-TW')!;
  expect(original).toBeDefined();
  const index = buildCountryGeometryIndex(data);
  expect(index.resolve('CN-TW')?.iso2).toBe('TW');
  expect(index.resolve('TW')?.geometry).toEqual(original.geometry);
  expect(index.locate([121, 23.5])?.iso2).toBe('TW');
});
