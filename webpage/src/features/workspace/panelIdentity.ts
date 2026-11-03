import type { PanelLayoutPrefs } from './panelLayout';

/** Old saved layouts refer to the same panel, not a newly enabled panel. */
export function canonicalPanelId(id: string): string {
  return id === 'polybeats-feed' ? 'polysignal-feed' : id;
}

export function migratePanelLayout(layout: PanelLayoutPrefs): PanelLayoutPrefs {
  const next = { ...layout };
  if (next['polybeats-feed']) {
    next['polysignal-feed'] ??= next['polybeats-feed'];
    delete next['polybeats-feed'];
  }
  return next;
}
