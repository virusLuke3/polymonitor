import { publicListSnapshot, publicPayload, publicSnapshot, record, records, strings, textFields } from '../public-snapshot';
import { RuntimeResponseError, runtimeTimestamp } from '../runtime-store';
import { PUBLIC_OVERVIEW_RETENTION_MS } from '../resource-cache';

const optional = (value: unknown, validate: (value: any) => boolean) => value == null || validate(value);
const texts = [ 'title', 'name', 'label', 'summary', 'source', 'sourceUrl', 'url', 'city', 'country', 'status'];
const rows = (value: unknown): value is Record<string, any>[] => records(value) && value.every(row => textFields(row, texts));
const links = (value: unknown) => rows(value) && value.every(row => optional(row.matchReasons, strings));
const evidenceRows = (value: unknown) => rows(value) && value.every(row => optional(row.tags, strings) && optional(row.markets, links));
const summary = (value: unknown) => optional(value, entry => record(entry) && Object.values(entry).every(v => v == null || ['string', 'number', 'boolean'].includes(typeof v)));

/** Same content owner, two directory projections; selection is all categories. */
export function mediaSnapshot(id: string, limit: number) {
  return publicListSnapshot({ id, limit, maxAgeMs: 30 * 60_000, staleAgeMs: 6 * 3_600_000,
    validate: value => value.items.every((row: Record<string, any>) => typeof row.id === 'string'
      && textFields(row, [...texts, 'displayName', 'category', 'region', 'hlsUrl', 'sourceType', 'youtubeLiveVideoId', 'youtubeChannelId'])
      && ['marketTags', 'matchedTerms', 'hlsProbeStreams'].every(key => optional(row[key], strings))
      && optional(row.playbackSources, sources => records(sources) && sources.every(source =>
        ['hls', 'youtube', 'youtube-channel'].includes(source.kind) && textFields(source, ['url', 'videoId', 'channelId']))))
      && optional(value.categories, categories => rows(categories) && categories.every(row => typeof row.id === 'string'))
      && optional(value.errors, strings) && summary(value.summary),
  });
}

export function newsSnapshot(id: string, limit: number) {
  return publicListSnapshot({ id, limit, maxAgeMs: 15 * 60_000, staleAgeMs: PUBLIC_OVERVIEW_RETENTION_MS,
    validate: value => evidenceRows(value.items) && summary(value.summary),
  });
}

export function transportSnapshot(limit: number) {
  return publicListSnapshot({ id: 'global-transport-shipping', limit, maxAgeMs: 2 * 3_600_000, staleAgeMs: 6 * 3_600_000,
    storage: 'indexeddb', maxChars: 2_000_000,
    validate: value => evidenceRows(value.items) && summary(value.summary)
      && optional(value.aviation, aviation => record(aviation) && ['routes', 'hubs', 'liveFlights', 'flights', 'ops', 'airlines', 'news'].every(key =>
        optional(aviation[key], entries => rows(entries) && entries.every(row => optional(row.riskSources, strings)
          && optional(row.trend, trend => Array.isArray(trend) && trend.every(v => v == null || ['number', 'string'].includes(typeof v)))))))
      && optional(value.evidence, evidence => record(evidence) && ['routes', 'risks', 'ops'].every(key => optional(evidence[key], records))),
  });
}

export function energySnapshot(limit: number) {
  return publicListSnapshot({ id: 'energy-gasoline-shock', limit, maxAgeMs: 18 * 3_600_000, staleAgeMs: 18 * 3_600_000,
    validate: value => rows(value.items) && optional(value.summary, summary => record(summary)
      && textFields(summary, ['signal', 'bias']) && optional(summary.linkedMarkets, strings)),
  });
}

export function calendarSnapshot(limit: number) {
  const event = (value: any) => record(value) && textFields(value, ['id', 'kind', 'title', 'releaseAt', 'releaseTimeEt', 'referencePeriod', 'sourceUrl']);
  return publicListSnapshot({ id: 'cpi-release-calendar', limit, maxAgeMs: 3 * 3_600_000, staleAgeMs: 3 * 3_600_000,
    validate: value => value.items.every(event) && optional(value.summary, s => record(s)
      && textFields(s, ['signal', 'risk', 'baselineLabel', 'consensusStatus'])
      && ['nextEvent', 'nextCpi', 'nextPce', 'nextNfp', 'nextFomc'].every(key => optional(s[key], event)))
      && ['baseline', 'consensus'].every(key => optional(value[key], s => record(s) && textFields(s, ['label', 'status', 'marketTitle', 'marketSlug']))),
  });
}

export const nowcastSnapshot = publicSnapshot<unknown>({
  key: 'public:inflation-nowcast:v1', version: 1, maxAgeMs: 90 * 60_000, staleAgeMs: 90 * 60_000,
  updatedAt: runtimeTimestamp,
  parse(value) {
    const payload = publicPayload(value, 'inflation-nowcast');
    const row = (v: any) => record(v) && Object.values(v).every(field => typeof field === 'string');
    if (!['monthOverMonth', 'yearOverYear'].every(key => optional(payload[key], row))
      || !optional(payload.quarterly, entries => Array.isArray(entries) && entries.every(row))) throw new RuntimeResponseError('Invalid nowcast');
    return payload;
  },
});

export function transmissionSnapshot(limit: number) {
  return publicSnapshot<unknown>({ key: `public:commodity-equity-transmission:limit:${limit}:v1`, version: 1,
    maxAgeMs: 5 * 60_000, staleAgeMs: 15 * 60_000, acceptStale: true, updatedAt: runtimeTimestamp,
    parse(value) {
      const payload = publicPayload(value, 'commodity-equity-transmission');
      if (!rows(payload.commodities) || !rows(payload.transmissions) || !summary(payload.summary)
        || !payload.transmissions.every(row => textFields(row, ['chainLabel', 'formula', 'shockLabel', 'lagLabel', 'commodityId'])
          && ['winners', 'losers', 'spreadWatch', 'linkedMarkets'].every(key => optional(row[key], rows)))) {
        throw new RuntimeResponseError('Invalid commodity transmission');
      }
      return { ...payload, transmissions: payload.transmissions.slice(0, limit) };
    },
  });
}
