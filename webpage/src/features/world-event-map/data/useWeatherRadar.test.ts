import { describe, expect, it } from 'vitest';
import { latestRadarFrame } from './useWeatherRadar';

describe('RainViewer manifest contract', () => {
  it('sorts actual past frames and uses the supplied opaque path', () => {
    const frame = latestRadarFrame({ host: 'https://tilecache.rainviewer.com', radar: { past: [
      { time: 100, path: '/v2/radar/old' }, { time: 300, path: '/v2/radar/future' },
      { time: 200, path: '/v2/radar/cc2b6ad6f468' },
    ] } }, 250_000);
    expect(frame.time).toBe(200);
    expect(frame.tiles).toContain('/v2/radar/cc2b6ad6f468/256/{z}/{x}/{y}/2/1_1.png');
    expect(frame.coverageTiles).toContain('/v2/coverage/0/');
  });
  it('rejects untrusted hosts, malformed paths and manifests without past observations', () => {
    for (const payload of [null, { host: 'https://evil.test', radar: { past: [] } },
      { host: 'https://tilecache.rainviewer.com', radar: { nowcast: [{ time: 100, path: '/v2/radar/test' }] } },
      { host: 'https://tilecache.rainviewer.com', radar: { past: [{ time: 100, path: '/v2/radar/../../evil' }] } },
    ]) expect(() => latestRadarFrame(payload, 200_000)).toThrow();
  });
});
