import { describe, expect, it, vi } from 'vitest';
import Supercluster from 'supercluster';
import { EventClusterIndex } from './eventClusters';
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
    expect(props.data[0].members.reduce((n: number, ref: { count: number }) => n + ref.count, 0)).toBe(240);
  });
  it('uses centered native text and one complete clickable background', () => {
    const result = layers();
    const count = result.find(layer => layer.id === 'world-event-cluster-counts')!;
    expect(count.constructor.name).toBe('TextLayer');
    expect(count.props).toMatchObject({ getTextAnchor: 'middle', getAlignmentBaseline: 'center', pickable: false });
    expect(result.find(layer => layer.id === 'world-event-clusters')?.props.pickable).toBe(true);
  });
});

describe('bounded cluster membership', () => {
  for (const size of [713, 5000]) it(`${size} events: queries never enumerate leaves; pages preserve every ID`, () => {
    const source = Array.from({ length: size }, (_, i) => ({ ...events[0]!, id: `fixture:${i}`,
      properties: { violenceType: String(i % 3 + 1) } }));
    const index = new EventClusterIndex(); index.update(source);
    const leaves = vi.spyOn(Supercluster.prototype, 'getLeaves');
    try {
      for (let i = 0; i < 50; i++) index.query(1.5, null, [-180 + i / 10, -80, 180, 80]);
      const presentation = index.presentation(1.5, null, undefined, ([x, y]) => ({ x: x * 10, y: y * 10 }));
      expect(leaves).not.toHaveBeenCalled();
      expect(index.buildCount).toBe(1);
      expect(presentation.clusters).toHaveLength(1);
      const cluster = presentation.clusters[0]!;
      expect(cluster.mixed).toBe(true); expect(cluster.count).toBe(size);
      const selection = index.selection(cluster);
      const all = Array.from({ length: Math.ceil(size / 30) }, (_, page) => selection.readPage(page * 30) || []).flat();
      expect(new Set(all.map(event => event.id)).size).toBe(size);
      expect(leaves.mock.calls.every(call => Number(call[1]) <= 31)).toBe(true);
      const selected = index.presentation(1.5, source[size - 1]!.id, undefined, ([x, y]) => ({ x, y }));
      const ids = [...selected.singles, ...selected.clusters.flatMap(c => Array.from({ length: Math.ceil(c.count / 30) }, (_, i) => index.readMembers(c, i * 30) || []).flat())].map(event => event.id);
      expect(ids).toHaveLength(size); expect(new Set(ids).size).toBe(size);
      index.update(source.slice(0, 3)); expect(selection.readPage(30)).toBeNull();
    } finally { leaves.mockRestore(); }
  });
  it('does not merge a chain across the viewport', () => {
    const source = Array.from({ length: 20 }, (_, i) => ({ ...events[0]!, id: `chain:${i}`,
      geometry: { type: 'Point' as const, coordinates: [i * 20, 0] as [number, number] } }));
    const index = new EventClusterIndex(); index.update(source);
    const result = index.presentation(8, null, [-180, -85, 180, 85], ([x, y]) => ({ x, y }));
    expect(result.clusters.every(cluster => cluster.bounds[2] - cluster.bounds[0] <= 76)).toBe(true);
  });
  it('reconciles a growing stack with an earlier neighbour and invalidates direct members', () => {
    const source = [0, 16, 2].map((x, i) => ({ ...events[0]!, id: `growth:${i}`,
      geometry: { type: 'Point' as const, coordinates: [x, 0] as [number, number] } }));
    const index = new EventClusterIndex(); index.update(source);
    const result = index.presentation(8, null, undefined, ([x, y]) => ({ x, y }));
    expect(result.clusters).toHaveLength(1);
    expect(result.clusters[0]!.count).toBe(3);
    const reference = result.clusters[0]!;
    expect(index.readMembers(reference)?.map(e => e.id).sort()).toEqual(source.map(e => e.id));
    index.update(source.map(e => ({ ...e, title: 'new revision' })));
    expect(index.selection(reference).readPage(0)).toBeNull();
    expect(index.readMembers(reference)).toBeNull();
  });
});
