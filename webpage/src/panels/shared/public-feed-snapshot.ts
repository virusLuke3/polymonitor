import type { PanelSnapshotContract } from '../resource-cache';
import { RuntimeResponseError, runtimeTimestamp } from '../runtime-store';
import { PUBLIC_OVERVIEW_RETENTION_MS, resourceIsCurrent } from '../resource-cache';

// Explicit public owners only. Account data, execution quotes and map/weather
// resources keep their domain contracts; a renderer never opts in implicitly.
const policies = {
  'nba-scoreboard': { fresh: 180_000, identity: ['id', 'name'] },
  'nba-intel': { fresh: 180_000, identity: ['headline', 'url'] },
  'espn-matchup-predictor': { fresh: 180_000, identity: ['eventId', 'name'] },
  'esports-intel': { fresh: 240_000, identity: ['id'] },
  'sports-odds': { fresh: 3 * 3_600_000, identity: ['id'] },
  'jin10-flash': { fresh: 300_000, identity: ['id', 'text', 'title'] },
  'f1-trackside': { fresh: 300_000, identity: ['id', 'title'] },
  'defi-token-watch': { fresh: 900_000, identity: ['id', 'symbol', 'name'] },
  'new-market-signals': { fresh: 900_000, identity: ['marketId', 'title'] },
} as const;
type PublicFeedId = keyof typeof policies;
const object = (value: unknown): value is Record<string, unknown> => value != null && typeof value === 'object' && !Array.isArray(value);
const failed = new Set(['error', 'failed', 'unavailable', 'warming', 'invalid', 'unknown', 'gateway-error', 'agent-error']);
const textArrays = new Set(['tags', 'contextTags', 'assetHints']);
const numberArrays = new Set(['sparkline', 'channelIds']);
const recordArrays = new Set(['starters', 'quotes', 'teamMetrics']);
const textFields = new Set(['title', 'headline', 'summary', 'name', 'symbol', 'url', 'sportTitle', 'sportKey']);

/** Feed rows are JSON records of scalar fields plus reviewed nested structures.
 * Reject structural corruption before a renderer calls trim/map/toUpperCase. */
function validRow(value: unknown, depth = 0): value is Record<string, unknown> {
  if (!object(value) || depth > 2) return false;
  return Object.entries(value).every(([key, field]) => {
    if (textFields.has(key)) return field == null || typeof field === 'string';
    if (field == null || ['string', 'boolean'].includes(typeof field)) return true;
    if (typeof field === 'number') return Number.isFinite(field);
    if (textArrays.has(key)) return Array.isArray(field) && field.every(item => typeof item === 'string');
    if (numberArrays.has(key)) return Array.isArray(field) && field.every(item => typeof item === 'number' && Number.isFinite(item));
    if (recordArrays.has(key)) return Array.isArray(field) && field.length <= 64 && field.every(item => validRow(item, depth + 1));
    return key === 'pm' && validRow(field, depth + 1);
  });
}

export function publicFeedSnapshot(panelId: PublicFeedId, limit: number): PanelSnapshotContract<unknown> {
  const policy = policies[panelId];
  const collection = panelId === 'f1-trackside' ? 'cards' : 'items';
  const revalidate = (value: unknown, now: number): unknown => {
    if (panelId !== 'defi-token-watch' || !object(value) || !Array.isArray(value.items)) return value;
    const items = value.items.filter(row => object(row) && resourceIsCurrent(
      runtimeTimestamp({ generatedAt: row.sourceFetchedAt || row.fetchedAt || value.generatedAt }), PUBLIC_OVERVIEW_RETENTION_MS, now));
    const stale = items.some(row => !resourceIsCurrent(
      runtimeTimestamp({ generatedAt: row.sourceFetchedAt || row.fetchedAt || value.generatedAt }), policy.fresh, now));
    return items.length === value.items.length && (!stale || value.status === 'stale') ? value : { ...value, items, status: 'stale',
      summary: { ...(object(value.summary) ? value.summary : {}), count: items.length } };
  };
  return {
    key: `public-feed:${panelId}:limit:${limit}:v1`, cache: { version: 1, maxChars: 128_000 },
    maxAgeMs: policy.fresh, staleAgeMs: PUBLIC_OVERVIEW_RETENTION_MS, acceptStale: true,
    updatedAt: runtimeTimestamp,
    revalidate,
    parse: value => {
      if (!object(value) || !Array.isArray(value[collection])) throw new RuntimeResponseError('Invalid public feed');
      if (value.panelId != null && value.panelId !== panelId) throw new RuntimeResponseError('Wrong public feed identity', false);
      if (runtimeTimestamp(value) == null || failed.has(String(value.status || '').toLowerCase())) throw new RuntimeResponseError('Public feed is unavailable');
      const rows = value[collection].slice(0, limit);
      const accepted = rows.filter(row => validRow(row) && policy.identity.some(key =>
        (typeof row[key] === 'string' && String(row[key]).trim()) || (typeof row[key] === 'number' && Number.isFinite(row[key]))));
      if (rows.length && !accepted.length) throw new RuntimeResponseError('No valid public feed rows');
      const result: Record<string, unknown> = { ...value, [collection]: accepted };
      let rejected = accepted.length !== rows.length;
      if (panelId === 'nba-intel') {
        if (!Array.isArray(value.lineups)) throw new RuntimeResponseError('Invalid NBA lineups');
        result.lineups = value.lineups.slice(0, limit).filter(row => validRow(row) && Array.isArray(row.starters));
        rejected ||= (result.lineups as unknown[]).length !== Math.min(value.lineups.length, limit);
      }
      if (object(value.sources) && Object.values(value.sources).some(state => /error|failed|unavailable|partial|degraded|timeout|missing/i.test(String(state)))) rejected = true;
      if (rejected && value.status !== 'stale') result.status = 'degraded';
      return revalidate(result, Date.now());
    },
    shouldPersist: value => object(value) && !failed.has(String(value.status || '').toLowerCase()),
  };
}
