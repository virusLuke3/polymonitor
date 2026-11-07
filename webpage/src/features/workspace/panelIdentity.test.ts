import { expect, it } from 'vitest';
import { migratePanelLayout } from './panelIdentity';
import { reconcileDefaultPanels } from './defaultPanels';

it('removes retired IDs from local and account layouts without moving other panels', () => {
  const active = ['whale-tracker', 'polybeats-feed', 'crypto-watch', 'polysignal-feed'];
  const known = ['polybeats-feed', 'polysignal-feed', 'crypto-watch', 'whale-tracker', 'hidden-panel'];
  const defaults = ['crypto-watch', 'whale-tracker', 'hidden-panel'];
  const result = reconcileDefaultPanels(active, defaults, known);
  expect(result.activePanelIds).toEqual(['whale-tracker', 'crypto-watch']);
  expect(result.knownDefaultPanelIds).toEqual(['crypto-watch', 'whale-tracker', 'hidden-panel']);
  expect(migratePanelLayout({ 'polybeats-feed': { rowSpan: 2 }, 'polysignal-feed': { colSpan: 3 }, 'crypto-watch': { rowSpan: 2, colSpan: 1 } }))
    .toEqual({ 'crypto-watch': { rowSpan: 2, colSpan: 1 } });
  expect(reconcileDefaultPanels(result.activePanelIds, defaults, result.knownDefaultPanelIds)).toEqual(result);
});
