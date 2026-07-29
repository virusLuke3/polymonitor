import type { GeoEvent } from '../domain/types';
import { eventMatchesWorldEventLayers, isHazardGeoEvent } from '../config/layerRegistry';
import type { WorldEventMapState, WorldEventTimeRange } from './mapState';

const TIME_RANGE_MS: Record<Exclude<WorldEventTimeRange, 'all'>, number> = {
  '1h': 60 * 60 * 1000,
  '6h': 6 * 60 * 60 * 1000,
  '24h': 24 * 60 * 60 * 1000,
  '48h': 48 * 60 * 60 * 1000,
  '7d': 7 * 24 * 60 * 60 * 1000,
};

export function filterWorldEventMapEvents(
  events: GeoEvent[],
  state: Pick<WorldEventMapState, 'timeRange' | 'severities'>,
  now = Date.now(),
) {
  const cutoff = state.timeRange === 'all' ? null : now - TIME_RANGE_MS[state.timeRange];
  const severities = new Set(state.severities);
  return events.filter((event) => {
    if (!severities.has(event.severity)) return false;
    if (isHazardGeoEvent(event)) {
      if (event.lifecycle === 'ended' || event.revision.cancelled) return false;
      const expiresAt = event.expiresAt ? Date.parse(event.expiresAt) : Number.NaN;
      if (Number.isFinite(expiresAt) && expiresAt <= now) return false;
    }
    if (cutoff == null) return true;
    const timestamp = event.updatedAt || event.occurredAt;
    if (!timestamp) return false;
    const parsed = Date.parse(timestamp);
    return Number.isFinite(parsed) && parsed >= cutoff && parsed <= now;
  });
}

export function filterWorldEventMapEventsForLayers(
  events: GeoEvent[],
  state: Pick<WorldEventMapState, 'activeLayerIds' | 'timeRange' | 'severities'>,
  now = Date.now(),
) {
  return filterWorldEventMapEvents(
    events.filter((event) => eventMatchesWorldEventLayers(event, state.activeLayerIds)),
    state,
    now,
  );
}
