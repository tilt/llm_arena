// Tiny IndexedDB store for finished run bundles in browser mode (per browser, per site).
import type { RunBundle } from "./contracts";

const DB = "llm-arena";
const STORE = "bundles";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const request = run(db.transaction(STORE, mode).objectStore(STORE));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export const saveBundle = (runId: string, bundle: RunBundle) => tx("readwrite", (s) => s.put(bundle, runId));
export const loadBundle = (runId: string) => tx<RunBundle | undefined>("readonly", (s) => s.get(runId));
export const listBundles = () => tx<RunBundle[]>("readonly", (s) => s.getAll());
export const deleteBundle = (runId: string) => tx("readwrite", (s) => s.delete(runId));
