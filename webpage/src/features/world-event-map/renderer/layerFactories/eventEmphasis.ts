import type { GeoEvent, GeoPoint, HazardEvent } from '../../domain/types';
import { eventRepresentativePoint, isHazardEvent, pointRadiusMeters } from './shared';
export { eventRepresentativePoint } from './shared';

export const HAZARD_PULSE_INTERVAL_MS = 500;
export const RECENT_EVENT_PULSE_MS = 30_000;

export type EventEmphasisTarget = {
  event: GeoEvent;
  position: GeoPoint;
  radius: number;
};

export type HazardPulseTarget = EventEmphasisTarget & {
  strength: 'strong' | 'warning';
};

export type RecentPulseTarget = EventEmphasisTarget & {
  fade: number;
};

export function targetForEvent(event: GeoEvent): EventEmphasisTarget | null {
  const position = eventRepresentativePoint(event);
  if (!position) return null;
  return {
    event,
    position,
    radius: event.geometry?.type === 'Point' ? pointRadiusMeters(event) : 24_000,
  };
}

function isAggregatedMajorFirmsEvent(event: HazardEvent) {
  if (event.hazardKind !== 'fire-detection') return true;
  return event.severity === 'warning'
    && event.metrics.kind === 'wildfire'
    && ((event.metrics.detectionCount || 0) > 1 || (event.metrics.fireRadiativePowerMw || 0) >= 1_000);
}

function isPulseEligibleHazard(event: GeoEvent): event is HazardEvent {
  return isHazardEvent(event) && isAggregatedMajorFirmsEvent(event);
}

function isMajorAviationInterruption(event: GeoEvent) {
  if (event.category !== 'infrastructure') return false;
  const mapEntity = String(event.properties.mapEntity || '');
  if (mapEntity !== 'air-hub' && mapEntity !== 'live-aircraft') return false;
  const riskScore = Number(event.properties.riskScore || 0);
  const status = String(event.properties.status || '').toLowerCase();
  return event.severity === 'critical'
    || riskScore >= 70
    || ['closed', 'disrupted', 'critical'].includes(status);
}

export function selectEventPulseCandidates(
  events: readonly GeoEvent[],
  selectedEventId: string | null,
) {
  return events.filter((event) => {
    if (isHazardEvent(event) && event.hazardKind === 'fire-detection') {
      return isPulseEligibleHazard(event);
    }
    if (event.id === selectedEventId) {
      const mapEntity = String(event.properties.mapEntity || '');
      return mapEntity !== 'air-route' && mapEntity !== 'air-flight';
    }
    return (isPulseEligibleHazard(event)
      && (event.severity === 'warning' || event.severity === 'critical'))
      || isMajorAviationInterruption(event);
  });
}

export function hazardPulseTargets(
  events: readonly GeoEvent[],
  selectedEventId: string | null,
  firstSeenAt: ReadonlyMap<string, number>,
  now: number,
  zoom = Number.POSITIVE_INFINITY,
) {
  const status: HazardPulseTarget[] = [];
  const recent: RecentPulseTarget[] = [];
  for (const event of events) {
    const eligibleHazard = isPulseEligibleHazard(event);
    const selected = event.id === selectedEventId;
    const majorAviationInterruption = isMajorAviationInterruption(event);
    if (!eligibleHazard && !selected && !majorAviationInterruption) continue;
    if (isHazardEvent(event) && event.hazardKind === 'fire-detection' && !eligibleHazard) continue;
    if (event.category === 'infrastructure') {
      const mapEntity = String(event.properties.mapEntity || '');
      if (mapEntity === 'air-route' || mapEntity === 'air-flight') continue;
    }
    const target = targetForEvent(event);
    if (!target) continue;
    if (selected || majorAviationInterruption || (eligibleHazard && event.severity === 'critical')) {
      status.push({ ...target, strength: 'strong' });
    } else if (eligibleHazard && event.severity === 'warning' && zoom >= 3) {
      status.push({ ...target, strength: 'warning' });
    }
    const firstSeen = firstSeenAt.get(event.id);
    const age = firstSeen == null ? Number.POSITIVE_INFINITY : Math.max(0, now - firstSeen);
    if (eligibleHazard
      && (event.severity === 'critical' || (event.severity === 'warning' && zoom >= 3))
      && age < RECENT_EVENT_PULSE_MS) {
      recent.push({ ...target, fade: Math.max(0, 1 - age / RECENT_EVENT_PULSE_MS) });
    }
  }
  const priority = (target: EventEmphasisTarget) => (
    Number(target.event.id === selectedEventId) * 10
    + (target.event.severity === 'critical' ? 3 : target.event.severity === 'warning' ? 2 : 0)
  );
  status.sort((left, right) => priority(right) - priority(left));
  recent.sort((left, right) => priority(right) - priority(left));
  const statusBudget = zoom < 2.5 ? 18 : zoom < 4 ? 50 : 120;
  const recentBudget = zoom < 2.5 ? 10 : zoom < 4 ? 25 : 60;
  return { status: status.slice(0, statusBudget), recent: recent.slice(0, recentBudget) };
}

export function hasAnimatedHazardPulse(
  events: readonly GeoEvent[],
  selectedEventId: string | null,
  firstSeenAt: ReadonlyMap<string, number>,
  now = Date.now(),
  zoom = Number.POSITIVE_INFINITY,
) {
  const targets = hazardPulseTargets(events, selectedEventId, firstSeenAt, now, zoom);
  return targets.status.length > 0 || targets.recent.length > 0;
}
