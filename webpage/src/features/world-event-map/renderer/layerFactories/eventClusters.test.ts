import { describe, expect, it } from 'vitest';
import { createEventPointLayers } from './eventPointLayer';
import type { GeoEvent } from '../../domain/types';
import type { Layer } from '@deck.gl/core';

const events = Array.from({ length: 240 }, (_, i): GeoEvent => ({ id: `count:${i}`, title: `count:${i}`,
  category: 'conflict', severity: 'critical', geometry: { type: 'Point', coordinates: [10, 10] },
  sources: [], limitations: [], relatedMarketIds: [], properties: {}, locationPrecision: 'exact' }));
const layers = () => createEventPointLayers({ events, zoom: 1.5, selectedEventId: null, showLabels: false }) as Layer[];
describe('map cluster counts after atlas retirement', () => {
  it('keeps the exact count above 100 instead of a 100+ badge', () => {
    const props = layers().find(layer => layer.id === 'world-event-cluster-counts')!.props as any;
    expect(props.getText(props.data[0])).toBe('240');
    expect(props.data[0].eventIds).toHaveLength(240);
  });
  it('uses centered native text and one complete clickable background', () => {
    const result = layers();
    const count = result.find(layer => layer.id === 'world-event-cluster-counts')!;
    expect(count.constructor.name).toBe('TextLayer');
    expect(count.props).toMatchObject({ getTextAnchor: 'middle', getAlignmentBaseline: 'center', pickable: false });
    expect(result.find(layer => layer.id === 'world-event-clusters')?.props.pickable).toBe(true);
  });
});
