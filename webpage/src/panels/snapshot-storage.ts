// Large snapshots cannot fit the synchronous localStorage budget. This is a
// storage backend of resource-cache, not another request/cache lifecycle.
const DB = 'polymonitor-panel-snapshots-v1';
const MAX_CHARS = 16_000_000;
const MAX_ENTRIES = 96;

function transaction<T>(mode: IDBTransactionMode, work: (tx: IDBTransaction, result: (value: T) => void) => void): Promise<T | null> {
  return new Promise(resolve => {
    let db: IDBDatabase | undefined, tx: IDBTransaction | undefined, settled = false, value: T | null = null;
    const done = () => {
      if (settled) return;
      settled = true; clearTimeout(timer); db?.close(); resolve(value);
    };
    // Storage has its own bounded lifetime. Runtime releases network admission
    // earlier, without throwing away a valid read delayed by a busy main thread.
    const timer = setTimeout(() => { value = null; try { tx?.abort(); } catch { /* Finished. */ } done(); }, 5000);
    try {
      const open = indexedDB.open(DB, 1);
      open.onupgradeneeded = () => {
        open.result.createObjectStore('payloads');
        open.result.createObjectStore('metadata', { keyPath: 'key' });
      };
      open.onerror = open.onblocked = done;
      open.onsuccess = () => {
        db = open.result;
        if (settled) { db.close(); return; }
        db.onversionchange = () => db?.close();
        try {
          tx = db.transaction(['payloads', 'metadata'], mode);
          tx.oncomplete = done;
          tx.onerror = tx.onabort = () => { value = null; done(); };
          work(tx, next => { value = next; });
        } catch { done(); }
      };
    } catch { done(); }
  });
}

export function readLargeSnapshot(key: string) {
  return transaction<string>('readonly', (tx, result) => {
    const request = tx.objectStore('payloads').get(key);
    request.onsuccess = () => { if (typeof request.result === 'string') result(request.result); };
  });
}

export function removeLargeSnapshot(key: string) {
  return transaction('readwrite', tx => {
    tx.objectStore('payloads').delete(key); tx.objectStore('metadata').delete(key);
  });
}

export function writeLargeSnapshot(key: string, encoded: string, cachedAt: number) {
  if (encoded.length > MAX_CHARS) return Promise.resolve(null);
  return transaction('readwrite', tx => {
    const payloads = tx.objectStore('payloads'), metadata = tx.objectStore('metadata');
    payloads.put(encoded, key);
    metadata.put({ key, size: encoded.length, cachedAt });
    const request = metadata.getAll();
    request.onsuccess = () => {
      const rows = request.result as { key: string; size: number; cachedAt: number }[];
      let size = rows.reduce((sum, row) => sum + row.size, 0), count = rows.length;
      for (const row of rows.filter(row => row.key !== key).sort((a, b) => a.cachedAt - b.cachedAt)) {
        if (size <= MAX_CHARS && count <= MAX_ENTRIES) break;
        payloads.delete(row.key); metadata.delete(row.key); size -= row.size; count--;
      }
    };
  });
}
