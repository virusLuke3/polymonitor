import type { PanelSnapshotContract } from './resource-cache';
import { RuntimeResponseError, runtimeTimestamp } from './runtime-store';

/** All public owners use the same storage/runtime. No Panel ID allowlist. */
export function publicSnapshot<T>(options: Omit<PanelSnapshotContract<T>, 'cache'> & {
  version: number; maxChars?: number; storage?: 'indexeddb';
}): PanelSnapshotContract<T> {
  const { version, maxChars = 256_000, storage, ...contract } = options;
  return { ...contract, cache: { version, maxChars, ...(storage ? { storage } : {}) } };
}

export const record = (value: unknown): value is Record<string, any> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
export const records = (value: unknown): value is Record<string, any>[] => Array.isArray(value) && value.every(record);
export const strings = (value: unknown) => Array.isArray(value) && value.every(entry => typeof entry === 'string');
export const textFields = (value: Record<string, any>, fields: string[]) =>
  fields.every(key => value[key] == null || typeof value[key] === 'string');

/** Header validation is shared; domain parsers still own nested shapes and clocks. */
export function publicPayload(value: unknown, id: string): Record<string, any> {
  if (!record(value) || (value.panelId != null && value.panelId !== id)
    || !textFields(value, ['generatedAt', 'status', 'cacheMode']) || runtimeTimestamp(value) === null
    || /^(warming|error|failed|unavailable|invalid|unknown|gateway-error|agent-error)$/.test(value.status || '')) {
    throw new RuntimeResponseError(`Invalid public snapshot: ${id}`);
  }
  return value;
}

/** Common list envelope; the owner supplies validation and its independent clocks. */
export function publicListSnapshot(options: {
  id: string; limit: number; maxAgeMs: number; staleAgeMs: number;
  validate: (value: Record<string, any>) => boolean; maxChars?: number; storage?: 'indexeddb';
}): PanelSnapshotContract<unknown> {
  return publicSnapshot<unknown>({
    key: `public:${options.id}:limit:${options.limit}:v1`, version: 1, maxChars: options.maxChars, storage: options.storage,
    maxAgeMs: options.maxAgeMs, staleAgeMs: options.staleAgeMs, acceptStale: true,
    updatedAt: runtimeTimestamp,
    parse(value) {
      const payload = publicPayload(value, options.id);
      if (!records(payload.items) || !options.validate(payload)) throw new RuntimeResponseError(`Invalid ${options.id} fields`);
      return { ...payload, items: payload.items.slice(0, options.limit) };
    },
  });
}
