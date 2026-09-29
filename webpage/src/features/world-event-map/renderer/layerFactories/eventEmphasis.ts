import type { GeoEvent, GeoPoint } from '../../domain/types';
import { eventRepresentativePoint, isHazardEvent, markerSize } from './shared';
export { eventRepresentativePoint } from './shared';

export const RECENT_EVENT_PULSE_MS = 6_000;
export type EventEmphasisTarget = { event: GeoEvent; position: GeoPoint; radius: number };
export type RecentPulseTarget = EventEmphasisTarget & { fade: number; phase: number };

export function targetForEvent(event: GeoEvent): EventEmphasisTarget | null {
  const position = eventRepresentativePoint(event);
  return position ? { event, position, radius: markerSize(event, null) / 2 } : null;
}

export function selectEventPulseCandidates(events: readonly GeoEvent[], _selectedEventId: string | null) {
  return events.filter(event => isHazardEvent(event) && event.hazardKind !== 'fire-detection'
    && (event.severity === 'warning' || event.severity === 'critical'));
}

export function hazardPulseTargets(
  events: readonly GeoEvent[], selectedEventId: string | null,
  firstSeenAt: ReadonlyMap<string, number>, now: number, zoom = Number.POSITIVE_INFINITY,
) {
  const recent: RecentPulseTarget[] = [];
  for (const event of selectEventPulseCandidates(events, selectedEventId)) {
    const firstSeen = firstSeenAt.get(event.id);
    if (firstSeen == null) continue;
    const age = now - firstSeen;
    if (age < 0 || age >= RECENT_EVENT_PULSE_MS) continue;
    const target = targetForEvent(event);
    if (!target) continue;
    // Stable per-event phase; this is an attention cue, never a geographic radius.
    let hash = 0;
    for (const char of event.id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
    recent.push({ ...target, fade: 1 - age / RECENT_EVENT_PULSE_MS, phase: ((age + hash % 600) % 2000) / 2000 });
  }
  recent.sort((a, b) => Number(b.event.id === selectedEventId) - Number(a.event.id === selectedEventId)
    || Number(b.event.severity === 'critical') - Number(a.event.severity === 'critical'));
  return { recent: recent.slice(0, zoom < 2.5 ? 6 : 12) };
}

export function hasAnimatedHazardPulse(
  events: readonly GeoEvent[], selectedEventId: string | null, firstSeenAt: ReadonlyMap<string, number>,
  now = Date.now(), zoom = Number.POSITIVE_INFINITY,
) {
  return hazardPulseTargets(events, selectedEventId, firstSeenAt, now, zoom).recent.length > 0;
}
