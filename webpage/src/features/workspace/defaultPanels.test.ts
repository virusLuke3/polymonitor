import { describe, expect, it } from 'vitest';
import { reconcileDefaultPanels } from './defaultPanels';

describe('workspace default panel discovery', () => {
  it('fills legacy layouts without reordering or duplicating existing panels', () => {
    expect(reconcileDefaultPanels(['optional', 'old'], ['old', 'new'], null)).toEqual({
      activePanelIds: ['optional', 'old', 'new'], knownDefaultPanelIds: ['old', 'new'],
    });
  });
  it('adds future defaults but preserves explicitly hidden known panels and ignores opt-in panels', () => {
    const first = reconcileDefaultPanels(['optional'], ['old', 'new'], ['old']);
    expect(first.activePanelIds).toEqual(['optional', 'new']);
    expect(reconcileDefaultPanels([], ['old', 'new', 'future'], first.knownDefaultPanelIds).activePanelIds).toEqual(['future']);
    expect(reconcileDefaultPanels([], ['old', 'new'], first.knownDefaultPanelIds).activePanelIds).toEqual([]);
  });
  it('retains knowledge across a rollback and later reintroduction', () => {
    const rollback = reconcileDefaultPanels([], ['old'], ['old', 'new']);
    expect(reconcileDefaultPanels([], ['old', 'new'], rollback.knownDefaultPanelIds).activePanelIds).toEqual([]);
  });
  it('treats malformed legacy catalog data as uninitialized', () => {
    expect(reconcileDefaultPanels([], ['new'], {}).activePanelIds).toEqual(['new']);
  });
});
