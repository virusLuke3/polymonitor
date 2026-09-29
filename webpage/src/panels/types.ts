import type { VNode } from 'preact';
import type { PanelDefinition, PanelRenderContext } from '@/types';

export type PanelRuntimeData = Record<string, unknown>;
export type PanelRuntimePhase = 'idle' | 'loading' | 'ready' | 'stale' | 'degraded' | 'error' | 'suspended';

export type PanelRuntimeContext = PanelRenderContext & {
  runtimeData: PanelRuntimeData;
};

export type PanelRenderer = (ctx: PanelRuntimeContext) => VNode;

export type RegistryEntry = PanelModule;

export type PanelEntryFragment = {
  render: PanelRenderer;
  size?: PanelDefinition['size'];
};

export type PanelRenderMap = Record<string, PanelEntryFragment>;

export type PanelRefreshTier = 'bootstrap' | 'fast' | 'slow' | 'manual';

export type PanelRefreshConfig = {
  tier: PanelRefreshTier;
  intervalMs?: number;
  staleAfterMs?: number;
  retry?: {
    attempts?: number;
    baseDelayMs?: number;
    maxDelayMs?: number;
  };
};

export type PanelFetchContext = {
  signal: AbortSignal;
  reason: 'bootstrap' | 'refresh' | 'interval' | 'retry' | 'manual';
};

export type PanelFetchData = (context?: PanelFetchContext) => Promise<unknown>;

export type PanelRuntimeStatus = {
  phase: PanelRuntimePhase;
  updatedAt: number | null;
  lastAttemptAt: number | null;
  failureCount: number;
  error: string | null;
  cacheMode?: string | null;
  freshness?: string | null;
  ageSeconds?: number | null;
};

export type PanelModule = PanelDefinition & {
  /** Another registered panel owns this view's shared snapshot and refresh. */
  dataSourceId?: string;
  /** Additional registered snapshots used by this panel's rendering. */
  dataDependencies?: string[];
  defaultEnabled?: boolean;
  maxBatchSize?: number;
  refreshPolicy?: PanelRefreshConfig;
  fetchData?: PanelFetchData;
  /** FocusedMarketStrip owns rendering for its fixed price, book and trade panels. */
  render?: PanelRenderer;
};
