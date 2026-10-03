/** Opt-in, public snapshots only. Cache identity includes every request parameter. */
export interface ResourceCacheContract<T> {
  key: string;
  parse: (value: unknown) => T;
  updatedAt: (value: T) => number | null;
  maxAgeMs: number;
  /** Optional bounded recovery age; does not change fresh response acceptance. */
  staleAgeMs?: number;
  cache?: { version: number; maxChars?: number };
}

/** The same validation contract is used for dedicated and batched snapshots. */
export interface PanelSnapshotContract<T> extends ResourceCacheContract<T> {
  acceptStale?: boolean;
  shouldPersist?: (next: T, previous: T | null) => boolean;
}

const PREFIX = 'polymonitor:panel-resource:';
const MAX_ENTRIES = 32;
const MAX_TOTAL_CHARS = 2_000_000;
const MAX_CHARS = 256_000;
const storageKey = (key: string) => `${PREFIX}${key}`;

export function resourceIsCurrent(timestamp: number | null, maxAgeMs: number, now = Date.now()) {
  return timestamp != null && Number.isFinite(timestamp) && timestamp <= now + 60_000 && now - timestamp < maxAgeMs;
}

export function readResourceCache<T>(contract: ResourceCacheContract<T>, storage: Storage, now = Date.now()): T | null {
  if (!contract.cache) return null;
  const key = storageKey(contract.key);
  try {
    const raw = storage.getItem(key);
    if (!raw) return null;
    const envelope = JSON.parse(raw);
    if (raw.length > (contract.cache.maxChars ?? MAX_CHARS) || envelope.version !== contract.cache.version) throw new Error('Invalid cache version');
    const value = contract.parse(envelope.value);
    if (!resourceIsCurrent(contract.updatedAt(value), Math.max(contract.maxAgeMs, contract.staleAgeMs ?? contract.maxAgeMs), now)) throw new Error('Expired cache');
    return value;
  } catch {
    try { storage.removeItem(key); } catch { /* Storage is optional. */ }
    return null;
  }
}

export function writeResourceCache<T>(contract: ResourceCacheContract<T>, raw: unknown, storage: Storage, now = Date.now()) {
  if (!contract.cache) return;
  try {
    const value = contract.parse(raw);
    if (!resourceIsCurrent(contract.updatedAt(value), contract.maxAgeMs, now)) return;
    const encoded = JSON.stringify({ version: contract.cache.version, cachedAt: now, value: raw });
    if (encoded.length > (contract.cache.maxChars ?? MAX_CHARS)) return;
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
