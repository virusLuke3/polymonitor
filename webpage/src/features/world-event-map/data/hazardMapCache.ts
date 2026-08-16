import type { HazardMapResponse } from '../domain/types';

export const HAZARD_MAP_SOURCE_KEYS = [
  'usgs',
  'eonet',
  'gdacs',
  'nws',
  'firms',
  'climate-anomaly',
] as const;

export type HazardMapSourceKey = typeof HAZARD_MAP_SOURCE_KEYS[number];

type HazardCacheEntry = {
  source: HazardMapSourceKey;
  storedAt: number;
  payload: HazardMapResponse;
};

const DATABASE_NAME = 'polymonitor-world-event-map';
const STORE_NAME = 'hazard-source-snapshots';
const DATABASE_VERSION = 1;
const LOCAL_STORAGE_PREFIX = 'polymonitor:hazard-map:last-good:';

function openDatabase(): Promise<IDBDatabase | null> {
  if (typeof indexedDB === 'undefined') return Promise.resolve(null);
  return new Promise((resolve) => {
    let request: IDBOpenDBRequest;
    try {
      request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    } catch {
      resolve(null);
      return;
    }
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME, { keyPath: 'source' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(null);
    request.onblocked = () => resolve(null);
  });
}

function localStorageKey(source: HazardMapSourceKey) {
  return `${LOCAL_STORAGE_PREFIX}${source}`;
}

function readLocalFallback(source: HazardMapSourceKey): HazardCacheEntry | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    const value = JSON.parse(localStorage.getItem(localStorageKey(source)) || 'null') as HazardCacheEntry | null;
    return value?.source === source && value.payload ? value : null;
  } catch {
    return null;
  }
}

function writeLocalFallback(entry: HazardCacheEntry) {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(localStorageKey(entry.source), JSON.stringify(entry));
  } catch {
    // Storage can be disabled or full. Network data remains usable in memory.
  }
}

export async function readHazardMapSnapshot(source: HazardMapSourceKey): Promise<HazardCacheEntry | null> {
  const database = await openDatabase();
  if (!database) return readLocalFallback(source);
  return new Promise((resolve) => {
    const transaction = database.transaction(STORE_NAME, 'readonly');
    const request = transaction.objectStore(STORE_NAME).get(source);
    request.onsuccess = () => resolve((request.result as HazardCacheEntry | undefined) || null);
    request.onerror = () => resolve(readLocalFallback(source));
    transaction.oncomplete = () => database.close();
    transaction.onabort = () => database.close();
  });
}

export async function writeHazardMapSnapshot(source: HazardMapSourceKey, payload: HazardMapResponse) {
  const entry: HazardCacheEntry = { source, storedAt: Date.now(), payload };
  const database = await openDatabase();
  if (!database) {
    writeLocalFallback(entry);
    return;
  }
  await new Promise<void>((resolve) => {
    const transaction = database.transaction(STORE_NAME, 'readwrite');
    transaction.objectStore(STORE_NAME).put(entry);
    transaction.oncomplete = () => {
      database.close();
      resolve();
    };
    transaction.onerror = () => {
      database.close();
      writeLocalFallback(entry);
      resolve();
    };
    transaction.onabort = () => {
      database.close();
      writeLocalFallback(entry);
      resolve();
    };
  });
}
