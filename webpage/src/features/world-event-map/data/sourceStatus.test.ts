import { describe, expect, it, vi } from 'vitest';
import type { HazardMapResponse } from '../domain/types';
import {
  sourceStatusFromAdapter,
  sourceStatusesAfterHazardRefreshFailure,
  sourceStatusesFromHazardResponse,
} from './sourceStatus';

describe('map source status', () => {
  it('marks unresolved official boundaries as partial while preserving the healthy CAP status', () => {
    const response = { events: [{ sources: [{ provider: 'NWS' }], properties: { unresolvedZoneCount: 1 } }],
      sources: [{ key: 'nws', status: 'ok', coverage: { label: 'NWS', gaps: [] } }],
    } as unknown as HazardMapResponse;
    expect(sourceStatusesFromHazardResponse(response)[0]).toMatchObject({ status: 'partial', phase: 'partial', eventCount: 1 });
    expect(response.sources[0]?.status).toBe('ok');
    response.events[0]!.geometry = { type: 'Point', coordinates: [145,15] };
    response.events[0]!.properties.unresolvedZoneCount = 0;
    expect(sourceStatusesFromHazardResponse(response)[0]).toMatchObject({ status: 'ok', phase: 'fresh' });
  });
  it('explains contract rejection separately from optional boundary coverage', () => {
    const response = { events: [], sources: [{ key: 'nws', status: 'ok',
      coverage: { label: 'NWS', gaps: [] } }] } as unknown as HazardMapResponse;
    const status = sourceStatusesFromHazardResponse(response, 2)[0];
    expect(status).toMatchObject({ status: 'partial', rejectedCount: 2 });
    expect(status?.message).toContain('2 records rejected by the map contract');
    expect(status?.message).not.toContain('optional official boundaries');
  });
  it('never turns an expired HTTP success body into a fresh source or rewrites its timestamps', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-01T06:42:00Z'));
    try {
      const response = { events: [], sources: [{ key: 'nws', status: 'ok',
        coverage: { label: 'NWS', gaps: [] }, fetchedAt: '2026-10-01T06:40:00Z',
        lastSuccessAt: '2026-10-01T06:40:00Z', staleAfter: '2026-10-01T06:41:00Z' }],
      } as unknown as HazardMapResponse;
      expect(sourceStatusesFromHazardResponse(response)[0]).toMatchObject({ status: 'degraded', phase: 'stale', eventCount: 0 });
      expect(sourceStatusesFromHazardResponse(response)[0]?.message).toContain('freshness deadline has passed');
      expect(response.sources[0]?.lastSuccessAt).toBe('2026-10-01T06:40:00Z');
    } finally { vi.useRealTimers(); }
  });
  it('keeps loading distinct from an empty successful source', () => {
    const loading = sourceStatusFromAdapter({
      key: 'fixture',
      label: 'Fixture',
      result: { events: [], rejected: [] },
      loaded: false,
    });
    const empty = sourceStatusFromAdapter({
      key: 'fixture',
      label: 'Fixture',
      payloadStatus: 'ok',
      result: { events: [], rejected: [] },
      loaded: true,
    });
    expect(loading.status).toBe('loading');
    expect(empty.status).toBe('ok');
  });

  it('marks contract rejection as partial without discarding valid events', () => {
    const status = sourceStatusFromAdapter({
      key: 'fixture',
      label: 'Fixture',
      payloadStatus: 'ok',
      result: {
        events: [{
          id: 'fixture:1',
          category: 'intel',
          title: 'Event',
          severity: 'watch',
          locationPrecision: 'unknown',
          sources: [{ provider: 'fixture' }],
          limitations: [],
          relatedMarketIds: [],
          properties: {},
        }],
        rejected: [{ index: 1, code: 'invalid-event', message: 'bad coordinates' }],
      },
      loaded: true,
    });
    expect(status).toMatchObject({ status: 'partial', eventCount: 1, rejectedCount: 1 });
  });

  it('preserves provider degradation and coverage reasons', () => {
    const response = {
      schemaVersion: 'natural-hazards.v1',
      generatedAt: '2026-07-29T12:00:00Z',
      events: [],
      sources: [{
        key: 'firms',
        status: 'degraded',
        coverage: {
          scope: 'global',
          label: 'NASA FIRMS satellite fire detections',
          isComplete: false,
          gaps: ['MAP_KEY is not configured'],
        },
        errorCode: 'configuration-required',
      }],
      isPartial: true,
      errors: [{ source: 'firms', code: 'configuration-required' }],
      counts: { events: 0, byHazardKind: {} },
    } satisfies HazardMapResponse;
    expect(sourceStatusesFromHazardResponse(response)[0]).toMatchObject({
      label: 'FIRMS',
      status: 'degraded',
      eventCount: 0,
    });
    expect(sourceStatusesFromHazardResponse(response)[0]?.message).toContain('configuration-required');
  });

  it('shows an initial failure and degrades retained snapshots on refresh failure', () => {
    expect(sourceStatusesAfterHazardRefreshFailure([], 'API 503', false)[0]).toMatchObject({
      key: 'natural-hazards',
      status: 'error',
      eventCount: 0,
      message: 'API 503',
    });
    const retained = sourceStatusesAfterHazardRefreshFailure([{
      key: 'usgs',
      label: 'USGS',
      status: 'ok',
      eventCount: 10,
      rejectedCount: 0,
    }], 'timeout', true);
    expect(retained[0]).toMatchObject({ status: 'degraded', eventCount: 10 });
    expect(retained[0]?.message).toContain('retaining the last successful snapshot');
  });

  it('counts NHC by its official provider name instead of the acronym substring', () => {
    const response = {
      events: [{ id: 'tropical-cyclone:nhc:a', sources: [{ provider: 'NOAA National Hurricane Center' }] }],
      sources: [{ key: 'nhc', status: 'ok', coverage: { label: 'NHC', gaps: [] } }],
    } as unknown as HazardMapResponse;
    expect(sourceStatusesFromHazardResponse(response)[0]).toMatchObject({ status: 'ok', eventCount: 1 });
  });

  it('keeps provider identities visible when the initial aggregate request fails', () => {
    const initial = sourceStatusesFromHazardResponse(null, 0, true);
    const failed = sourceStatusesAfterHazardRefreshFailure(initial, 'API timeout', false);
    expect(failed.map((source) => source.key)).toEqual([
      'usgs',
      'usgs-volcano-cap',
      'nhc',
      'eonet',
      'gdacs',
      'nws',
      'firms',
      'climate-anomaly',
    ]);
    expect(failed.every((source) => source.status === 'error')).toBe(true);
    expect(failed[0]?.message).toContain('Initial source load failed');
  });
});
