import type { VNode } from 'preact';
import type { PanelDefinition, PanelRenderContext } from '@/types';
import type { PanelSnapshotContract } from './resource-cache';

export type PanelRuntimeData = Record<string, unknown>;
export type PanelRuntimePhase = 'idle' | 'loading' | 'ready' | 'stale' | 'degraded' | 'error' | 'suspended';

export type PanelContextKey = Exclude<keyof PanelRenderContext, 'runtimeData'>;
/** Panels opt into the workspace inputs they actually consume. */
export type PanelInputs<K extends PanelContextKey = never> = Pick<PanelRenderContext, K | 'runtimeData'>;
export type PanelRuntimeContext = PanelInputs;

export type PanelRenderer<K extends PanelContextKey = never> = (ctx: PanelInputs<K>) => VNode;

export type RegistryEntry = PanelModule;

export type PanelEntryFragment<K extends PanelContextKey = never> = {
  render: PanelRenderer<K>;
  size?: PanelDefinition['size'];
};

export type PanelRenderMap<K extends PanelContextKey = never> = Record<string, PanelEntryFragment<K>>;

export type PanelRefreshTier = 'bootstrap' | 'fast' | 'slow' | 'manual';

export type PanelRefreshConfig = {
  tier: PanelRefreshTier;
  intervalMs?: number;
  staleAfterMs?: number;
  /** Whole request budget, including admission, fallback and response parsing. */
  requestTimeoutMs?: number;
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
  /** Optional domain label; request failure/age still belong to the runtime. */
  label?: string;
  updatedAt: number | null;
  lastAttemptAt: number | null;
  /** Successful HTTP/validation completion, distinct from the source timestamp. */
  checkedAt?: number | null;
  fetching?: boolean;
  failureCount: number;
  retryPending?: boolean;
  pendingSince?: number;
  error: string | null;
  cacheMode?: string | null;
  freshness?: string | null;
  ageSeconds?: number | null;
  retryable?: boolean;
  nextRetryAt?: number | null;
};

export type PanelModule = PanelDefinition & {
  /** Workspace fields passed to this panel, in addition to declared snapshots. */
  contextKeys?: readonly PanelContextKey[];
  /** Another registered panel owns this view's shared snapshot and refresh. */
  dataSourceId?: string;
  /** Additional registered snapshots used by this panel's rendering. */
  dataDependencies?: string[];
  defaultEnabled?: boolean;
  maxBatchSize?: number;
  /** Sources with their own endpoint still use shared cancellation and refresh. */
  batch?: boolean;
  /** Shared by batch requests and the individual fallback. */
  request?: { limit: number };
  /** Complete resource identity and validation, independent of transport. */
  snapshot?: PanelSnapshotContract<unknown>;
  refreshPolicy?: PanelRefreshConfig;
  fetchData?: PanelFetchData;
  /** FocusedMarketStrip owns rendering for its fixed price, book and trade panels. */
  render?: (ctx: PanelRenderContext) => VNode;
};
