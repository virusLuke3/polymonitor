import { describe, expect, it, vi } from 'vitest';
import type { PanelRenderContext } from '@/types';
import { panelFromRenderer } from './definePanel';

describe('panel input boundary', () => {
  it('passes only declared workspace inputs and shared snapshots to a view', () => {
    const render = vi.fn();
    const view = panelFromRenderer<'selectedWeatherCityId'>({ weather: { render } }, {
      id: 'weather', title: '', description: '', eyebrow: '',
      contextKeys: ['selectedWeatherCityId'],
      dataSourceId: 'weather-source',
      dataDependencies: ['additional-source'],
    });
    const weather = { items: [{ cityId: 'london' }] };
    const additional = { status: 'stale' };
    view.render!({
      selectedWeatherCityId: 'london', selectedMarketId: 42,
      runtimeData: { 'weather-source': weather, 'additional-source': additional, unrelated: {} },
    } as unknown as PanelRenderContext);
    expect(render).toHaveBeenCalledWith({
      selectedWeatherCityId: 'london',
      runtimeData: { 'weather-source': weather, 'additional-source': additional },
    });
    expect(render.mock.calls[0]?.[0].runtimeData['weather-source']).toBe(weather);
  });
});
