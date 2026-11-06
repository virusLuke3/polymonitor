import { expect, it } from 'vitest';
import { DEFAULT_PANEL_IDS, PANEL_REGISTRY } from '../../registry';
import { reconcileDefaultPanels } from '../../../features/workspace/defaultPanels';
import { politicsContract, politicsFreshnessMs } from './resource';
import { readResourceCache, resourceIsCurrent, writeResourceCache } from '../../resource-cache';
import { validRace, record, rows } from './model';

const ids = ['election','early-vote','nomination','seats','campaign-finance','government','executive','appointments','funding'].map(s => `politics-${s}`);
it('appends new panels to an old layout and respects subsequent explicit hides', () => {
  const before = ['crypto-watch', 'policy-progress'];
  const known = DEFAULT_PANEL_IDS.filter(id => !ids.includes(id));
  const next = reconcileDefaultPanels(before, DEFAULT_PANEL_IDS, known);
  expect(next.activePanelIds.slice(0,2)).toEqual(before);
  ids.forEach(id => { expect(next.activePanelIds).toContain(id); expect(PANEL_REGISTRY[id]?.fetchData).toBeTypeOf('function'); });
  expect(DEFAULT_PANEL_IDS).not.toContain('politics-legislation');
  const hidden = next.activePanelIds.filter(id => id !== 'politics-election');
  expect(reconcileDefaultPanels(hidden, DEFAULT_PANEL_IDS, next.knownDefaultPanelIds).activePanelIds).toEqual(hidden);
});

function storage() {
  const values = new Map<string, string>();
  return { get length() { return values.size; }, key: (i: number) => [...values.keys()][i] ?? null,
    getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); }, clear: () => values.clear() };
}

it.each([
  ['campaign-finance', 6, 18], ['nomination', 24, 72], ['election', 1, 3],
  ['seats', 0.5, 1.5], ['executive', 0.5, 24],
])('retains %s between acquisitions and ages by successful acquisition, not a later attempt', (name, cadenceHours, freshHours) => {
  const id = `politics-${name}`, now = Date.parse('2026-11-06T12:00:00Z'), hour = 3600000;
  const success = now - (Number(cadenceHours) - 0.1) * hour;
  const contract = politicsContract(id, () => true), cache = storage();
  const payload = { panelId: id, schemaVersion: 1, generatedAt: new Date(now).toISOString(),
    sources: [{ id: 'source', url: 'https://example.org', stale: false,
      lastSuccessAt: new Date(success).toISOString(), lastAttemptAt: new Date(now).toISOString() }] };
  const policy = PANEL_REGISTRY[id]!.refreshPolicy!;
  expect(policy.staleAfterMs).toBe(Number(freshHours) * hour);
  expect(contract.maxAgeMs).toBe(policy.staleAfterMs);
  expect(resourceIsCurrent(contract.updatedAt(payload), policy.staleAfterMs!, now)).toBe(true);
  writeResourceCache(contract, payload, cache, now);
  expect(readResourceCache(contract, cache, now)).toEqual(payload);
  expect(contract.updatedAt(payload)).toBe(success);
  expect(resourceIsCurrent(success, politicsFreshnessMs(id), success + Number(freshHours) * hour + 1)).toBe(false);
  // Failed acquisition changes neither the retained cache nor the success clock.
  const failed = { ...payload, generatedAt: new Date(now + hour).toISOString(),
    sources: [{ ...payload.sources[0], lastAttemptAt: new Date(now + hour).toISOString(), error: 'TimeoutError' }] };
  expect(contract.updatedAt(failed)).toBe(success);
  expect(readResourceCache(contract, cache, success + 7 * 86400000 + 1)).toBeNull();
  expect(contract.updatedAt({ ...payload, sources: [{ ...payload.sources[0], lastSuccessAt: null }] })).toBeNull();
});
it('rejects wrong identities and malformed nested votes rather than crashing a panel', () => {
  const contract = politicsContract('politics-nomination', value => record(value) && rows(value.items, validRace));
  const base = { panelId:'politics-nomination', schemaVersion:1, generatedAt:'2026-11-06T00:00:00Z', sources:[], items:[] };
  expect(contract.parse(base)).toEqual(base);
  expect(() => contract.parse({...base,panelId:'politics-election'})).toThrow();
  expect(() => contract.parse({...base,items:[{id:'x',title:'x',electionDate:'2026-01-01',choices:[{name:'a',party:'D',votes:'oops'}]}]})).toThrow();
});
