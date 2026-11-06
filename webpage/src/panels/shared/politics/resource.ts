import { RuntimeResponseError } from '../../runtime-store';
import type { PanelSnapshotContract } from '../../resource-cache';
import { base, type Base } from './model';
export function politicsContract(id: string, validate: (value: unknown) => boolean): PanelSnapshotContract<unknown> {
  return { key: `politics:${id}:v1`, maxAgeMs: 600000, staleAgeMs: 7 * 86400000, acceptStale: true,
    cache: { version: 1, maxChars: 220000 },
    parse(value) { if (!base(value) || value.panelId !== id || !validate(value)) throw new RuntimeResponseError('Invalid politics snapshot'); return value; },
    updatedAt: value => base(value) ? Date.parse((value as Base).generatedAt) : null };
}
