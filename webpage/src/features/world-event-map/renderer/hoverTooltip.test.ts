import { describe, expect, it } from 'vitest';
import type { GeoEvent } from '../domain/types';
import type { EventCluster } from './layerFactories';
import {
  pickedWorldEvent,
  pickedWorldEventCluster,
  worldEventTooltipHtml,
} from './hoverTooltip';

function event(overrides: Partial<GeoEvent> = {}): GeoEvent {
  return {
    id: 'event:1',
    category: 'conflict',
    title: 'Evidence <alert>',
    severity: 'warning',
    locationPrecision: 'country',
    locationLabel: 'Example',
    sources: [{ provider: 'UCDP' }],
    limitations: [],
    relatedMarketIds: [],
    properties: {},
    ...overrides,
  };
}

describe('world event hover tooltip', () => {
  it('unwraps GeoJSON features and escapes event content', () => {
    const target = { properties: { event: event() } };
    expect(pickedWorldEvent(target)?.id).toBe('event:1');
    expect(worldEventTooltipHtml(target)).toContain('Evidence &lt;alert&gt;');
    expect(worldEventTooltipHtml(target)).toContain('WARNING · Example · UCDP');
  });

  it('renders clusters instead of discarding their hover state', () => {
    const cluster: EventCluster = {
      kind: 'event-cluster',
      id: 'cluster:1',
      coordinates: [12, 34],
      eventIds: ['one', 'two'],
      count: 2,
      severity: 'critical',
      bounds: [10, 30, 14, 38],
      expansionZoom: 4,
      color: [255, 76, 70, 235],
    };
    expect(pickedWorldEvent(cluster)).toBeNull();
    expect(pickedWorldEventCluster(cluster)).toBe(cluster);
    expect(worldEventTooltipHtml(cluster)).toContain('2 mapped events');
  });
});
