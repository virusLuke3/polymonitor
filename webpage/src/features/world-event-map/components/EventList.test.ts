import { describe, expect, it } from 'vitest';
import type { GeoEvent } from '../domain/types';
import { visibleAccessibleEvents } from './EventList';

function event(id: string, severity: GeoEvent['severity'] = 'info'): GeoEvent {
  return {
    id,
    category: 'natural-hazard',
    title: id,
    severity,
    geometry: { type: 'Point', coordinates: [0, 0] },
    locationPrecision: 'exact',
    sources: [{ provider: 'fixture', nativeId: id }],
    limitations: [],
    relatedMarketIds: [],
    properties: {},
  };
}

describe('accessible event list', () => {
  it('bounds the rendered list and always retains the selected event', () => {
    const events = Array.from({ length: 2_000 }, (_, index) => (
      event(`event-${index}`, index < 10 ? 'critical' : 'info')
    ));
    const visible = visibleAccessibleEvents(events, 'event-1999');
    expect(visible.length).toBe(301);
    expect(visible[0]?.id).toBe('event-1999');
    expect(visible.some((item) => item.id === 'event-0')).toBe(true);
  });
});
