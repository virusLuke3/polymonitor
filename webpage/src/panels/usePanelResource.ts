import { createContext, createElement, type ComponentChildren } from 'preact';
import { useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'preact/hooks';
import type { PanelFetchContext, PanelModule, PanelRefreshConfig, PanelRuntimeStatus } from './types';
import { usePanelRuntime } from './usePanelRuntime';
import { readResourceCache, resourceIsCurrent, writeResourceCache, type ResourceCacheContract } from './resource-cache';

export interface PanelResource<T> extends ResourceCacheContract<T> {
  title: string;
  fetch: (context?: PanelFetchContext) => Promise<unknown>;
  refreshPolicy: PanelRefreshConfig;
  shouldPersist?: (next: T, previous: T | null) => boolean;
  statusLabel?: (value: T, status: PanelRuntimeStatus) => string | undefined;
}

type Consumer = { contract: PanelResource<unknown>; active: boolean; panelId: string | null };
type Owner = {
  runtime: ReturnType<typeof usePanelRuntime>;
  register: (contract: PanelResource<unknown>, active: boolean, seed: unknown, panelId: string | null) => { release: () => void; setActive: (active: boolean) => void };
  consumers: Map<symbol, Consumer>;
};
const ResourceOwner = createContext<Owner | null>(null);
export const PanelResourceVisibility = createContext(true);
export const PanelResourceView = createContext<string | null>(null);

/** Workspace status/retry use the actual resource owner, without domain knowledge. */
export function usePanelResourceBinding(panelId: string) {
  const owner = useContext(ResourceOwner);
  const consumer = owner && [...owner.consumers.values()].reverse().find(value => value.panelId === panelId);
  if (!owner || !consumer) return null;
  const status = owner.runtime.getStatus(consumer.contract.key);
  const value = owner.runtime.getData(consumer.contract.key);
  return { status: { ...status, label: value == null ? undefined : consumer.contract.statusLabel?.(value, status) },
    refresh: () => owner.runtime.refreshIds([consumer.contract.key], { reason: 'manual', force: true }) };
}

/** One owner for parameterized resources; the existing runtime remains the scheduler. */
export function PanelResourceProvider({ children }: { children: ComponentChildren }) {
  const consumers = useRef(new Map<symbol, Consumer>());
  const [revision, changed] = useState(0);
  const runtimeRef = useRef<ReturnType<typeof usePanelRuntime> | null>(null);
  const panels = useMemo(() => {
    const contracts = new Map([...consumers.current.values()].map(({ contract }) => [contract.key, contract]));
    return [...contracts.values()].map(contract => resourcePanel(contract));
  }, [revision]);
  const activePanelIds = useMemo(() => [...new Set([...consumers.current.values()]
    .filter(consumer => consumer.active).map(consumer => consumer.contract.key))], [revision]);
  const runtime = usePanelRuntime({ panels, activePanelIds });
  runtimeRef.current = runtime;
  const register = useCallback((contract: PanelResource<unknown>, active: boolean, seed: unknown, panelId: string | null) => {
    const token = Symbol(contract.key);
    const consumer = { contract, active, panelId };
    consumers.current.set(token, consumer);
    if (seed != null) runtimeRef.current?.setRuntimeData(current => current[contract.key] == null
      ? { ...current, [contract.key]: seed } : current);
    changed(value => value + 1);
    const release = () => {
      consumers.current.delete(token);
      if (![...consumers.current.values()].some(consumer => consumer.contract.key === contract.key)) {
        runtimeRef.current?.forgetIds([contract.key]);
      }
      changed(value => value + 1);
    };
    return { release, setActive: (next: boolean) => {
      if (consumer.active === next) return;
      consumer.active = next; changed(value => value + 1);
    } };
  }, []);
  return createElement(ResourceOwner.Provider, { value: { runtime, register, consumers: consumers.current } }, children);
}

function resourcePanel<T>(contract: PanelResource<T>): PanelModule {
  return {
    id: contract.key, title: contract.title, eyebrow: 'resource', description: contract.title,
    batch: false, refreshPolicy: contract.refreshPolicy,
    fetchData: async context => {
      const raw = await contract.fetch(context);
      const value = contract.parse(raw);
      if (!resourceIsCurrent(contract.updatedAt(value), contract.maxAgeMs)) throw new Error('Resource snapshot time is unknown or overdue');
      if (context?.signal.aborted) throw new DOMException('Aborted', 'AbortError');
      try {
        const previous = contract.shouldPersist ? readResourceCache(contract, window.localStorage) : null;
        if (!contract.shouldPersist || contract.shouldPersist(value, previous)) writeResourceCache(contract, raw, window.localStorage);
      } catch { /* Optional public cache. */ }
      return value;
    },
  };
}

/** Subscribe by complete request identity; no component owns a second request loop. */
export function usePanelResource<T>(contract: PanelResource<T>, active?: boolean) {
  const owner = useContext(ResourceOwner);
  const visible = useContext(PanelResourceVisibility);
  const panelId = useContext(PanelResourceView);
  if (!owner) throw new Error('Panel resources require PanelResourceProvider');
  // Complete keys describe immutable request meaning. Fresh object literals in
  // a consumer render must not repeatedly register/cancel the same request.
  const declaration = useMemo(() => contract, [contract.key, contract.maxAgeMs, contract.cache?.version,
    contract.refreshPolicy.tier, contract.refreshPolicy.intervalMs, contract.refreshPolicy.staleAfterMs,
    contract.refreshPolicy.retry?.attempts, contract.refreshPolicy.retry?.baseDelayMs, contract.refreshPolicy.retry?.maxDelayMs]);
  const seed = useMemo(() => {
    try { return readResourceCache(declaration, window.localStorage); } catch { return null; }
  }, [declaration]);
  const enabled = active ?? visible;
  const subscription = useRef<ReturnType<Owner['register']> | null>(null);
  useLayoutEffect(() => {
    const registration = owner.register(declaration as PanelResource<unknown>, enabled, seed, panelId);
    subscription.current = registration;
    return registration.release;
  }, [owner.register, declaration, seed, panelId]);
  useLayoutEffect(() => subscription.current?.setActive(enabled), [enabled]);
  const runtime = owner.runtime;
  const status = runtime.getStatus(contract.key);
  const latest = (runtime.getData(contract.key) ?? seed) as T | null;
  const timestamp = latest == null ? null : contract.updatedAt(latest);
  const [, tick] = useState(0);
  const expired = latest != null && timestamp != null && !resourceIsCurrent(timestamp, contract.maxAgeMs);
  useEffect(() => {
    if (timestamp == null || expired) return;
    const timer = window.setTimeout(() => tick(version => version + 1),
      Math.min(2_147_483_647, Math.max(1, timestamp + contract.maxAgeMs - Date.now())));
    return () => window.clearTimeout(timer);
  }, [timestamp, contract.maxAgeMs, expired]);
  const data = expired ? null : latest ?? null;
  return {
    data, status, expired, suspended: runtime.suspended || !enabled,
    loading: !data && !status.error && !expired,
    fromCache: data != null && status.checkedAt == null,
    error: status.error || (expired ? 'Resource snapshot is overdue' : null),
    refresh: () => runtime.refreshIds([contract.key], { reason: 'manual', force: true }),
  };
}
