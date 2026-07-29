import type { RuntimeGeoSanctionsShockPayload } from '@/types';
import type { CountryGeometryIndex } from '../domain/countryGeometry';
import type { GeoEvent, GeoEventAdapterResult } from '../domain/types';
import { validateGeoEvents } from '../domain/validation';
import {
  finiteNumber,
  isoTimestamp,
  nonEmpty,
  normalizedSeverity,
  normalizedSourceStatus,
  stableId,
} from './shared';

export function adaptGeoShockPayload(payload?: RuntimeGeoSanctionsShockPayload | null): GeoEventAdapterResult {
  const provider = nonEmpty(payload?.conflictProvider) || nonEmpty(payload?.source) || 'ucdp';
  const sourceStatus = normalizedSourceStatus(payload?.conflictState || payload?.status);
  const candidates: GeoEvent[] = [];
  const missingId: GeoEventAdapterResult['rejected'] = [];

  (payload?.items || []).forEach((item, index) => {
    const id = stableId(provider, item.id);
    if (!id) {
      missingId.push({ index, code: 'missing-stable-id', message: 'conflict event has no provider-native id' });
      return;
    }
    const longitude = finiteNumber(item.longitude);
    const latitude = finiteNumber(item.latitude);
    const hasPoint = longitude != null
      && latitude != null
      && longitude >= -180
      && longitude <= 180
      && latitude >= -90
      && latitude <= 90;
    const country = nonEmpty(item.country);
    const title = nonEmpty(item.headline)
      || [nonEmpty(item.sideA), nonEmpty(item.sideB)].filter(Boolean).join(' vs ')
      || nonEmpty(item.locationLabel)
      || 'Conflict event';
    candidates.push({
      id,
      category: String(item.kind || '').toLowerCase().includes('unrest') ? 'unrest' : 'conflict',
      title,
      summary: nonEmpty(item.summary),
      severity: normalizedSeverity(item.severity),
      occurredAt: isoTimestamp(item.occurredAt),
      geometry: hasPoint ? { type: 'Point', coordinates: [longitude, latitude] } : undefined,
      locationPrecision: hasPoint ? 'exact' : country ? 'country' : 'unknown',
      locationLabel: nonEmpty(item.locationLabel) || country,
      sources: [{
        provider,
        url: nonEmpty(item.sourceUrl) || nonEmpty(payload?.sourceUrl),
        nativeId: nonEmpty(item.id),
        observedAt: isoTimestamp(item.occurredAt),
        status: sourceStatus,
      }],
      limitations: [
        'Fatality estimates and conflict classification may be revised by the source.',
        ...(hasPoint ? [] : ['The source did not provide renderable point geometry.']),
      ],
      relatedMarketIds: [],
      properties: {
        mapEntity: 'conflict-event',
        country,
        sideA: nonEmpty(item.sideA),
        sideB: nonEmpty(item.sideB),
        deathsBest: finiteNumber(item.deathsBest) ?? 0,
        deathsLow: finiteNumber(item.deathsLow),
        deathsHigh: finiteNumber(item.deathsHigh),
        violenceType: nonEmpty(item.violenceType),
        rawSeverity: nonEmpty(item.severity),
        tags: item.tags || [],
      },
    });
  });

  const validated = validateGeoEvents(candidates);
  return { events: validated.events, rejected: [...missingId, ...validated.rejected] };
}

function countryRiskSeverity(count: number) {
  if (count >= 25) return 'warning' as const;
  return 'watch' as const;
}

function countryRiskCategory(source?: string | null) {
  const normalized = String(source || '').toLowerCase();
  return normalized.includes('ofac') || normalized.includes('federal register')
    ? 'sanctions' as const
    : 'country-risk' as const;
}

export function adaptGeoShockCountryRiskPayload(
  payload: RuntimeGeoSanctionsShockPayload | null | undefined,
  countries: CountryGeometryIndex | null,
): GeoEventAdapterResult {
  if (!payload || !countries) return { events: [], rejected: [] };
  const provider = nonEmpty(payload.source) || 'OFAC / Federal Register / UCDP';
  const sourceStatus = normalizedSourceStatus(payload.status);
  const candidates: GeoEvent[] = [];
  const rejected: GeoEventAdapterResult['rejected'] = [];

  (payload.targetBreakdown || []).forEach((target, index) => {
    const label = nonEmpty(target.label);
    const country = countries.resolve(label);
    if (!label || !country) {
      rejected.push({
        index,
        code: 'unresolved-country-geometry',
        message: `risk target is not a verified country identity: ${label || 'unknown'}`,
      });
      return;
    }
    const count = Math.max(0, finiteNumber(target.count) ?? 0);
    if (!count) {
      rejected.push({
        index,
        code: 'empty-country-risk-evidence',
        message: `risk target has no source-backed evidence count: ${label}`,
      });
      return;
    }
    const latestSource = nonEmpty(target.latestSource);
    const category = countryRiskCategory(latestSource);
    candidates.push({
      id: `geo-sanctions-shock:${country.iso2}`,
      category,
      title: category === 'sanctions'
        ? `Sanctions activity: ${country.name}`
        : `Country risk evidence: ${country.name}`,
      summary: nonEmpty(target.latestHeadline) || nonEmpty(payload.summary?.targetSummary),
      severity: countryRiskSeverity(count),
      occurredAt: isoTimestamp(target.latestOccurredAt),
      updatedAt: isoTimestamp(payload.generatedAt),
      geometry: country.geometry,
      locationPrecision: 'country',
      countryCode: country.iso2,
      locationLabel: country.name,
      sources: [{
        provider: latestSource || provider,
        url: nonEmpty(payload.sourceUrl),
        nativeId: `country:${country.iso2}`,
        observedAt: isoTimestamp(target.latestOccurredAt),
        status: sourceStatus,
      }],
      limitations: [
        'The polygon is a country-level evidence aggregate, not an incident footprint.',
        'Counts combine configured OFAC, Federal Register and conflict feeds and are not legal advice.',
        'A global new-sanctions count is not attributed to a country unless the source target is explicit.',
      ],
      relatedMarketIds: [],
      properties: {
        mapEntity: 'country-risk-area',
        country: country.name,
        countryCode: country.iso2,
        evidenceCount: count,
        latestHeadline: nonEmpty(target.latestHeadline),
        latestSource,
        ofacRecordCountTotal: finiteNumber(payload.ofacRecordCountTotal),
        globalNewSanctionsCount: finiteNumber(payload.summary?.newSanctionsCount),
        riskMappingVersion: 'geo-shock-country-risk.v1',
      },
    });
  });

  const validated = validateGeoEvents(candidates);
  return { events: validated.events, rejected: [...rejected, ...validated.rejected] };
}
