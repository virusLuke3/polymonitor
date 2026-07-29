import type { RuntimeGeoSanctionsShockPayload } from '@/types';
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
