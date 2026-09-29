import type { PanelModule, PanelRenderMap } from '../types';

type RuntimeOptions = {
  tier: NonNullable<PanelModule['refreshPolicy']>['tier'];
  intervalMs?: number;
  fetchData: NonNullable<PanelModule['fetchData']>;
};

export function panelFromRenderer(
  renderers: PanelRenderMap,
  definition: Omit<PanelModule, 'render'>,
): PanelModule {
  const entry = renderers[definition.id];
  if (!entry) {
    throw new Error(`Missing panel renderer for ${definition.id}`);
  }
  return {
    ...definition,
    size: definition.size || entry.size,
    render: entry.render,
  };
}

export function runtimePanelFromRenderer(
  renderers: PanelRenderMap,
  definition: Omit<PanelModule, 'render' | 'fetchData' | 'refreshPolicy'>,
  runtime: RuntimeOptions,
): PanelModule {
  return panelFromRenderer(renderers, {
    ...definition,
    fetchData: runtime.fetchData,
    refreshPolicy: {
      tier: runtime.tier,
      intervalMs: runtime.intervalMs,
    },
  });
}
