import { expect, it } from 'vitest';
import { migratePanelLayout } from './panelIdentity';
import { reconcileDefaultPanels } from './defaultPanels';

it('keeps the old position, size and subsequent explicit hides across migration', () => {
  const defaults = ['crypto-watch', 'polysignal-feed', 'whale-tracker'];
  const before = ['whale-tracker', 'polybeats-feed', 'crypto-watch'];
  const migrated = reconcileDefaultPanels(before, defaults, ['polybeats-feed', 'crypto-watch', 'whale-tracker']);
  expect(migrated.activePanelIds).toEqual(['whale-tracker', 'polysignal-feed', 'crypto-watch']);
  expect(migratePanelLayout({'polybeats-feed': {rowSpan: 2, colSpan: 3}, 'crypto-watch': {rowSpan: 1}}))
    .toEqual({'polysignal-feed': {rowSpan: 2, colSpan: 3}, 'crypto-watch': {rowSpan: 1}});
  expect(reconcileDefaultPanels(['whale-tracker', 'crypto-watch'], defaults, ['polybeats-feed', 'crypto-watch', 'whale-tracker']).activePanelIds)
    .toEqual(['whale-tracker', 'crypto-watch']);
  expect(reconcileDefaultPanels(['whale-tracker', 'crypto-watch'], defaults, migrated.knownDefaultPanelIds).activePanelIds)
    .toEqual(['whale-tracker', 'crypto-watch']);
});
it('deduplicates aliases and prefers already migrated sizes', () => {
  expect(reconcileDefaultPanels(['polybeats-feed', 'polysignal-feed'], ['polysignal-feed'], null).activePanelIds).toEqual(['polysignal-feed']);
  expect(migratePanelLayout({'polybeats-feed': {colSpan: 3}, 'polysignal-feed': {colSpan: 1}})).toEqual({'polysignal-feed': {colSpan: 1}});
});
