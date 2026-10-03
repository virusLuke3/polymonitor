import type { PanelContextKey, PanelFetchContext, PanelInputs, PanelModule, PanelRenderMap } from './types';

type PanelDefinition<K extends PanelContextKey> = Omit<PanelModule, 'render' | 'contextKeys'> & (
  [K] extends [never] ? { contextKeys?: never } : { contextKeys: readonly K[] }
);

type RuntimeOptions = {
  tier: NonNullable<PanelModule['refreshPolicy']>['tier'];
  intervalMs?: number;
  staleAfterMs?: number;
  requestTimeoutMs?: number;
  retry?: NonNullable<PanelModule['refreshPolicy']>['retry'];
  batch?: boolean;
  limit?: number;
  fetchData: (context?: PanelFetchContext, limit?: number) => Promise<unknown>;
};

export function panelFromRenderer<K extends PanelContextKey = never>(
  renderers: PanelRenderMap<K>,
  definition: PanelDefinition<K>,
): PanelModule {
  const entry = renderers[definition.id];
  if (!entry) {
    throw new Error(`Missing panel renderer for ${definition.id}`);
  }
  const sources = [...new Set([definition.dataSourceId || definition.id, ...(definition.dataDependencies || [])])];
  const contextKeys = definition.contextKeys || [];
  return {
    ...definition,
    size: definition.size || entry.size,
    render: (context) => {
      const inputs = Object.fromEntries(contextKeys.map((key) => [key, context[key]]));
      return entry.render({
        ...inputs,
        runtimeData: Object.fromEntries(sources.map((id) => [id, context.runtimeData[id]])),
      } as PanelInputs<K>);
    },
  };
}

export function runtimePanelFromRenderer<K extends PanelContextKey = never>(
  renderers: PanelRenderMap<K>,
  definition: PanelDefinition<K>,
  runtime: RuntimeOptions,
): PanelModule {
  return panelFromRenderer(renderers, {
    ...definition,
    request: runtime.limit === undefined ? undefined : { limit: runtime.limit },
    batch: runtime.batch,
    fetchData: (context) => runtime.fetchData(context, runtime.limit),
    refreshPolicy: {
      tier: runtime.tier,
      intervalMs: runtime.intervalMs,
      staleAfterMs: runtime.staleAfterMs,
      requestTimeoutMs: runtime.requestTimeoutMs,
      retry: runtime.retry,
    },
  });
}
