import { describe, expect, it } from 'vitest';
import { sourceStatusFromAdapter } from './sourceStatus';

describe('map source status', () => {
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
});
