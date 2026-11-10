import { readLargeSnapshot, writeLargeSnapshot, removeLargeSnapshot } from './snapshot-storage';

/** Display recovery for public overviews; freshness/execution clocks stay separate. */
export const PUBLIC_OVERVIEW_RETENTION_MS = 24 * 60 * 60_000;

export type ResourceCachePolicy = { version: number; maxChars?: number; storage?: 'indexeddb' };
/** Public snapshots only. Cache identity includes every request parameter. */
export interface ResourceCacheContract<T> {
  key: string;
  parse: (value: unknown) => T;
  updatedAt: (value: T) => number | null;
  maxAgeMs: number;
  /** Optional bounded recovery age; does not change fresh response acceptance. */
  staleAgeMs?: number;
  cache?: ResourceCachePolicy | null;
}

/** The same validation contract is used for dedicated and batched snapshots. */
export interface PanelSnapshotContract<T> extends ResourceCacheContract<T> {
  /** Required policy: null explicitly keeps execution/private resources in memory. */
  cache: ResourceCachePolicy | null;
  acceptStale?: boolean;
  /** Opt-in local display expiry on the existing Runtime sweep; preserve identity when unchanged. */
  revalidate?: (value: T, now: number) => T;
  shouldPersist?: (next: T, previous: T | null) => boolean;
}

const PREFIX = 'polymonitor:panel-resource:';
const MAX_ENTRIES = 96;
const MAX_TOTAL_CHARS = 2_000_000;
const MAX_CHARS = 256_000;
const storageKey = (key: string) => `${PREFIX}${key}`;

export function resourceIsCurrent(timestamp: number | null, maxAgeMs: number, now = Date.now()) {
  return timestamp != null && Number.isFinite(timestamp) && timestamp <= now + 60_000 && now - timestamp < maxAgeMs;
}

export type RestoredResource<T> = { value: T; checkedAt: number | null };

function decode<T>(contract: ResourceCacheContract<T>, raw: string, now: number): RestoredResource<T> {
  const envelope = JSON.parse(raw);
  if (!contract.cache || raw.length > (contract.cache.maxChars ?? MAX_CHARS) || envelope.version !== contract.cache.version
    || (envelope.key != null && envelope.key !== contract.key)) throw new Error('Invalid cache identity/version');
  const value = contract.parse(envelope.value);
  if (!resourceIsCurrent(contract.updatedAt(value), Math.max(contract.maxAgeMs, contract.staleAgeMs ?? contract.maxAgeMs), now)) throw new Error('Expired cache');
  const checkedAt = typeof envelope.checkedAt === 'number' && Number.isFinite(envelope.checkedAt)
    && envelope.checkedAt > 0 && envelope.checkedAt <= now ? envelope.checkedAt : null;
  return { value, checkedAt };
}

export function readResourceCacheEntry<T>(contract: ResourceCacheContract<T>, storage: Storage, now = Date.now()): RestoredResource<T> | null {
  if (!contract.cache || contract.cache.storage === 'indexeddb') return null;
  const key = storageKey(contract.key);
  try {
    const raw = storage.getItem(key);
    if (!raw) return null;
    return decode(contract, raw, now);
  } catch {
    try { storage.removeItem(key); } catch { /* Storage is optional. */ }
    return null;
  }
}

export function readResourceCache<T>(contract: ResourceCacheContract<T>, storage: Storage, now = Date.now()): T | null {
  return readResourceCacheEntry(contract, storage, now)?.value ?? null;
}

export function writeResourceCache<T>(contract: PanelSnapshotContract<T>, raw: unknown, storage: Storage | null, now = Date.now()) {
  if (!contract.cache) return;
  try {
    const value = contract.parse(raw);
    const retention = contract.acceptStale ? Math.max(contract.maxAgeMs, contract.staleAgeMs ?? contract.maxAgeMs) : contract.maxAgeMs;
    if (!resourceIsCurrent(contract.updatedAt(value), retention, now)) return;
    const encoded = JSON.stringify({ key: contract.key, version: contract.cache.version, cachedAt: now, checkedAt: now, value: raw });
    if (encoded.length > (contract.cache.maxChars ?? MAX_CHARS)) return;
    if (contract.cache.storage === 'indexeddb') {
      void writeLargeSnapshot(contract.key, encoded, now);
      return;
    }
    if (!storage) return;
    const key = storageKey(contract.key);
    // Bound this cache without touching other application storage.
    storage.setItem(key, encoded);
    const entries = Array.from({ length: storage.length }, (_, i) => storage.key(i))
      .filter((entry): entry is string => Boolean(entry?.startsWith(PREFIX)))
      .map(entry => {
        const value = storage.getItem(entry) || '';
        let cachedAt = 0;
        try { cachedAt = Number(JSON.parse(value).cachedAt) || 0; } catch { /* Evict malformed entries first. */ }
        return { key: entry, size: value.length, cachedAt };
      });
    let count = entries.length, size = entries.reduce((total, entry) => total + entry.size, 0);
    for (const entry of entries.filter(entry => entry.key !== key).sort((a, b) => a.cachedAt - b.cachedAt)) {
      if (count <= MAX_ENTRIES && size <= MAX_TOTAL_CHARS) break;
      storage.removeItem(entry.key); count--; size -= entry.size;
    }
  } catch { /* Quota, disabled storage or invalid content cannot break a panel. */ }
}

/** Large public resources use the same envelope/validation with an async backend. */
export async function readIndexedResource<T>(contract: ResourceCacheContract<T>): Promise<RestoredResource<T> | null> {
  if (contract.cache?.storage !== 'indexeddb') return null;
  const raw = await readLargeSnapshot(contract.key);
  if (!raw) return null;
  try { return decode(contract, raw, Date.now()); }
  catch { void removeLargeSnapshot(contract.key); return null; }
}
