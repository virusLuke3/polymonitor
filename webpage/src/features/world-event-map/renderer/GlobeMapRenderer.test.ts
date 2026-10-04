import { afterEach, expect, it, vi } from 'vitest';
vi.mock('globe.gl', () => ({ default: vi.fn() }));
import { GlobeMapRenderer } from './GlobeMapRenderer';

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
it('coalesces data, input and animation wakes into one native tick and cancels on pause', async () => {
  vi.useFakeTimers();
  vi.stubGlobal('requestAnimationFrame', (fn: () => void) => setTimeout(fn, 16));
  vi.stubGlobal('cancelAnimationFrame', (id: ReturnType<typeof setTimeout>) => clearTimeout(id));
  const renderer = new GlobeMapRenderer() as any;
  renderer.globe = { resumeAnimation: vi.fn(), pauseAnimation: vi.fn() };
  for (let i = 0; i < 50; i++) renderer.wake();
  await vi.advanceTimersByTimeAsync(16);
  expect(renderer.globe.resumeAnimation).toHaveBeenCalledTimes(1);
  expect(renderer.globe.pauseAnimation).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(500);
  expect(renderer.globe.resumeAnimation).toHaveBeenCalledTimes(1);
  renderer.wake(); renderer.pause();
  await vi.advanceTimersByTimeAsync(16);
  expect(renderer.globe.resumeAnimation).toHaveBeenCalledTimes(1);
});
it('precomputes immutable coordinate samples once and retires removed snapshots', () => {
  const renderer = new GlobeMapRenderer() as any;
  renderer.paused = true;
  const event = { id: 'area', category: 'infrastructure', severity: 'info', properties: {},
    geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] } };
  renderer.setEvents([event]);
  const samples = renderer.positionSamples.get(event);
  renderer.setEvents([event]);
  expect(renderer.positionSamples.get(event)).toBe(samples);
  renderer.setEvents([]);
  expect(renderer.positionSamples.size).toBe(0);
});
it('does not snap an in-progress gesture back when a source update carries the last published camera', () => {
  const renderer = new GlobeMapRenderer() as any;
  renderer.paused = true;
  const previous = renderer.state;
  renderer.state = { ...previous, center: { lon: 75, lat: 30 }, zoom: 3 };
  renderer.cameraPending = true;
  renderer.setState({ ...previous, timeRange: 'all' });
  expect(renderer.state.center).toEqual({ lon: 75, lat: 30 });
  expect(renderer.state.zoom).toBe(3);
  expect(renderer.state.timeRange).toBe('all');
  renderer.setState({ ...previous, center: { lon: -20, lat: 10 } });
  expect(renderer.state.center).toEqual({ lon: -20, lat: 10 });
  expect(renderer.cameraPending).toBe(false);
});
