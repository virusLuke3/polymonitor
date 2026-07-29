import type { Feature, FeatureCollection, MultiPolygon, Polygon } from 'geojson';
import type { GeoEventGeometry } from './types';

type CountryProperties = {
  name?: unknown;
  'ISO3166-1-Alpha-2'?: unknown;
  'ISO3166-1-Alpha-3'?: unknown;
};

export type CountryGeometry = {
  name: string;
  iso2: string;
  iso3: string;
  geometry: Extract<GeoEventGeometry, { type: 'Polygon' | 'MultiPolygon' }>;
};

export type CountryGeometryIndex = {
  countries: CountryGeometry[];
  resolve: (identity?: string | null) => CountryGeometry | null;
};

const COUNTRY_ALIASES: Record<string, string> = {
  america: 'US',
  bolivia: 'BO',
  'brunei darussalam': 'BN',
  burma: 'MM',
  'cape verde': 'CV',
  'congo brazzaville': 'CG',
  'congo kinshasa': 'CD',
  'cote d ivoire': 'CI',
  'democratic republic of congo': 'CD',
  'democratic republic of the congo': 'CD',
  'dr congo': 'CD',
  iran: 'IR',
  laos: 'LA',
  moldova: 'MD',
  northkorea: 'KP',
  'north korea': 'KP',
  palestine: 'PS',
  russia: 'RU',
  southkorea: 'KR',
  'south korea': 'KR',
  syria: 'SY',
  taiwan: 'TW',
  tanzania: 'TZ',
  'the gambia': 'GM',
  turkey: 'TR',
  uk: 'GB',
  'u k': 'GB',
  'united kingdom': 'GB',
  us: 'US',
  'u s': 'US',
  usa: 'US',
  'u s a': 'US',
  'united states': 'US',
  'united states of america': 'US',
  venezuela: 'VE',
  vietnam: 'VN',
};

export function normalizeCountryIdentity(value?: string | null) {
  return String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\b(the|republic|federal|democratic|state|states|of)\b/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function text(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

function countryFeature(feature: Feature): CountryGeometry | null {
  if (feature.geometry?.type !== 'Polygon' && feature.geometry?.type !== 'MultiPolygon') return null;
  const properties = (feature.properties || {}) as CountryProperties;
  const name = text(properties.name);
  const iso2 = text(properties['ISO3166-1-Alpha-2']).toUpperCase();
  const iso3 = text(properties['ISO3166-1-Alpha-3']).toUpperCase();
  if (!name || !/^[A-Z]{2}$/.test(iso2) || !/^[A-Z]{3}$/.test(iso3)) return null;
  return {
    name,
    iso2,
    iso3,
    geometry: feature.geometry as Polygon | MultiPolygon,
  };
}

export function buildCountryGeometryIndex(collection: FeatureCollection): CountryGeometryIndex {
  const countries = collection.features
    .map(countryFeature)
    .filter((country): country is CountryGeometry => country !== null);
  const lookup = new Map<string, CountryGeometry>();
  countries.forEach((country) => {
    lookup.set(country.iso2.toLowerCase(), country);
    lookup.set(country.iso3.toLowerCase(), country);
    lookup.set(normalizeCountryIdentity(country.name), country);
  });
  Object.entries(COUNTRY_ALIASES).forEach(([alias, iso2]) => {
    const country = lookup.get(iso2.toLowerCase());
    if (country) lookup.set(normalizeCountryIdentity(alias), country);
  });
  return {
    countries,
    resolve(identity) {
      const raw = String(identity || '').trim();
      if (!raw || /^global$/i.test(raw)) return null;
      return lookup.get(raw.toLowerCase()) || lookup.get(normalizeCountryIdentity(raw)) || null;
    },
  };
}
