import { RuntimeResponseError } from '../../runtime-store';
import type { PanelSnapshotContract } from '../../resource-cache';
import { base, type Base } from './model';

// Match politics/store.py's three acquisition cycles, not browser polling.
// Executive Actions retains the reused disclosure owner's 24h freshness window.
const freshnessHours: Record<string, number> = {
  election: 3, 'early-vote': 3, nomination: 72, 'campaign-finance': 18,
  seats: 1.5, government: 1.5, appointments: 1.5,
  funding: 1.5, executive: 24,
};
export function politicsFreshnessMs(id: string): number {
  const hours = freshnessHours[id.replace(/^politics-/, '')];
  if (hours === undefined) throw new Error(`Missing politics freshness policy: ${id}`);
  return hours * 3600000;
}

function lastSuccess(value: Base): number | null {
  const times = value.sources.map(source => source.lastSuccessAt ? Date.parse(source.lastSuccessAt) : NaN).filter(Number.isFinite);
  // generatedAt is a projection/attempt clock, not evidence of acquisition.
  return times.length ? Math.max(...times) : null;
}

export function politicsContract(id: string, validate: (value: unknown) => boolean): PanelSnapshotContract<unknown> {
  return { key: `politics:${id}:v1`, maxAgeMs: politicsFreshnessMs(id), staleAgeMs: 7 * 86400000, acceptStale: true,
    cache: { version: 1, maxChars: 220000 },
    parse(value) { if (!base(value) || value.panelId !== id || !validate(value)) throw new RuntimeResponseError('Invalid politics snapshot'); return value; },
    updatedAt: value => base(value) ? lastSuccess(value) : null };
}
