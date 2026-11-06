import { expect, it } from 'vitest';
import { DEFAULT_PANEL_IDS, PANEL_REGISTRY } from '../../registry';
import { reconcileDefaultPanels } from '../../../features/workspace/defaultPanels';
import { politicsContract } from './resource';
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
it('rejects wrong identities and malformed nested votes rather than crashing a panel', () => {
  const contract = politicsContract('politics-nomination', value => record(value) && rows(value.items, validRace));
  const base = { panelId:'politics-nomination', schemaVersion:1, generatedAt:'2026-11-06T00:00:00Z', sources:[], items:[] };
  expect(contract.parse(base)).toEqual(base);
  expect(() => contract.parse({...base,panelId:'politics-election'})).toThrow();
  expect(() => contract.parse({...base,items:[{id:'x',title:'x',electionDate:'2026-01-01',choices:[{name:'a',party:'D',votes:'oops'}]}]})).toThrow();
});
