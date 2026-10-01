/** Opt-in, public snapshots only. Cache identity includes every request parameter. */
export interface ResourceCacheContract<T> {
  key: string;
  parse: (value: unknown) => T;
  updatedAt: (value: T) => number | null;
  maxAgeMs: number;
  cache?: { version: number };
}

const PREFIX = 'polymonitor:panel-resource:';
const MAX_ENTRIES = 8;
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
    if (raw.length > MAX_CHARS || envelope.version !== contract.cache.version) throw new Error('Invalid cache version');
    const value = contract.parse(envelope.value);
    if (!resourceIsCurrent(contract.updatedAt(value), contract.maxAgeMs, now)) throw new Error('Expired cache');
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
    const encoded = JSON.stringify({ version: contract.cache.version, value: raw });
    if (encoded.length > MAX_CHARS) return;
    const key = storageKey(contract.key);
    // Bound this cache without touching other application storage.
    storage.setItem(key, encoded);
    const keys = Array.from({ length: storage.length }, (_, i) => storage.key(i))
      .filter((entry): entry is string => Boolean(entry?.startsWith(PREFIX)));
    for (const entry of keys.filter(entry => entry !== key).slice(0, Math.max(0, keys.length - MAX_ENTRIES))) storage.removeItem(entry);
  } catch { /* Quota, disabled storage or invalid content cannot break a panel. */ }
}
