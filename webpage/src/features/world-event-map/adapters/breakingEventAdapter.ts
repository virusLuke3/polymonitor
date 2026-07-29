import type { RuntimeBreakingEventRadarPayload } from '@/types';
import type { GeoEvent, GeoEventAdapterResult } from '../domain/types';
import { validateGeoEvents } from '../domain/validation';
import {
  isoTimestamp,
  nonEmpty,
  normalizedConfidence,
  normalizedFreshness,
  normalizedSeverity,
  normalizedSourceStatus,
  stableId,
} from './shared';

export function adaptBreakingEventPayload(payload?: RuntimeBreakingEventRadarPayload | null): GeoEventAdapterResult {
  const provider = nonEmpty(payload?.source) || 'breaking-event-radar';
  const candidates: GeoEvent[] = [];
  const missingId: GeoEventAdapterResult['rejected'] = [];
  (payload?.items || []).forEach((item, index) => {
    const id = stableId(provider, item.id);
    if (!id) {
      missingId.push({ index, code: 'missing-stable-id', message: 'breaking event has no provider-native id' });
      return;
    }
    const marketIds = [
      ...(item.relatedPolymarketMarketIds || []),
      ...(item.markets || []).flatMap((market) => market.marketId == null ? [] : [market.marketId]),
    ];
    candidates.push({
      id,
      category: 'intel',
      title: nonEmpty(item.title) || nonEmpty(item.entity) || nonEmpty(item.topic) || 'Breaking event',
      summary: nonEmpty(item.summary),
      severity: normalizedSeverity(item.severity),
      occurredAt: isoTimestamp(item.eventTime),
      locationPrecision: nonEmpty(item.country) ? 'country' : 'unknown',
      locationLabel: nonEmpty(item.country),
      confidence: normalizedConfidence(item.confidence),
      sources: [{
        provider: nonEmpty(item.source) || provider,
        url: nonEmpty(item.sourceUrl) || nonEmpty(payload?.sourceUrl),
        nativeId: nonEmpty(item.id),
        observedAt: isoTimestamp(item.eventTime),
        freshness: normalizedFreshness(payload?.freshness || payload?.cacheMode),
        status: normalizedSourceStatus(payload?.status),
      }],
      limitations: [
        'Country-level intelligence remains non-spatial until a verified region or polygon is available.',
      ],
      relatedMarketIds: [...new Set(marketIds.map(String))],
      properties: {
        mapEntity: 'intel-hotspot',
        topic: nonEmpty(item.topic),
        entity: nonEmpty(item.entity),
        country: nonEmpty(item.country),
        evidenceType: nonEmpty(item.evidenceType),
        sourceDiversity: item.sourceDiversity,
        velocityScore: item.velocityScore,
        tags: item.tags || [],
      },
    });
  });
  const validated = validateGeoEvents(candidates);
  return { events: validated.events, rejected: [...missingId, ...validated.rejected] };
}
