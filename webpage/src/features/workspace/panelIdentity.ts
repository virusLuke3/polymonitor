import type { PanelLayoutPrefs } from './panelLayout';

// Tombstones only: neither retired ID should return through an old account layout.
export const isRetiredPanel = (id: string) => id === 'polysignal-feed' || id === 'polybeats-feed';

export function canonicalPanelId(id: string): string {
  return id;
}

export function migratePanelLayout(layout: PanelLayoutPrefs): PanelLayoutPrefs {
  const next = { ...layout };
  for (const id of Object.keys(next)) if (isRetiredPanel(id)) delete next[id];
  return next;
}
