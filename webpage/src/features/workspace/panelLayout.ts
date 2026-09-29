export type PanelLayoutPrefs = Record<string, { rowSpan?: number; colSpan?: number }>;
export type PanelSizeHint = 'default' | 'wide' | 'tall' | undefined;

export function requestedPanelLayout(prefs: PanelLayoutPrefs, id: string, size: PanelSizeHint) {
  const clamp = (value: number, max: number) => Math.max(1, Math.min(max, Math.round(value)));
  return {
    rowSpan: clamp(prefs[id]?.rowSpan ?? (size === 'tall' ? 2 : 1), 4),
    colSpan: clamp(prefs[id]?.colSpan ?? (size === 'wide' ? 2 : 1), 3),
  };
}

/** The dashboard's existing fixed-size product policy, previously hidden in CSS.
 * Stored resize preferences are preserved; this does not enable free resizing. */
export function effectivePanelLayout(id: string, width: number) {
  if (id === 'market-tv-wire' || id === 'market-youtube-channels') {
    return { rowSpan: 2, column: `span ${width <= 760 ? 1 : id === 'market-youtube-channels' && width > 1500 ? 3 : 2}` };
  }
  if (id === 'market-summary' && width <= 760) return { rowSpan: 1, column: '1 / span 2' };
  return { rowSpan: 1, column: `span ${['breaking-event-radar', 'global-transport-shipping'].includes(id) ? 2 : 1}` };
}
