import type { ScreenBox } from './layerFactories/eventClusters';

export const MAP_OCCLUDERS = '.wm-event-inspector, .wm-world-event-list > section, .wm-world-event-list-toggle, .wm-weather-deck-legend.is-open, .wm-map-legend-toggle, .wm-layer-sidebar, .wm-map-controls, .wm-map-radar-status, .wm-map-radar-status[open] > div, .wm-world-event-attribution, .wm-map-focus-toggle, .wm-aviation-lens, .wm-country-context-card';
export const boxesOverlap = (a: ScreenBox, b: ScreenBox) => a[0] < b[2] && a[2] > b[0] && a[1] < b[3] && a[3] > b[1];

/** Nearest available rectangle, shared by tooltips and selection reveal. */
export function clearMapPosition(point: { x: number; y: number }, size: [number, number],
  viewport: [number, number], occupied: ScreenBox[], margin = 12) {
  const [width, height] = size, [vw, vh] = viewport;
  const candidates = [point, ...occupied.flatMap(b => [
    { x: b[0] - width - margin, y: point.y }, { x: b[2] + margin, y: point.y },
    { x: point.x, y: b[1] - height - margin }, { x: point.x, y: b[3] + margin },
  ])].map(p => ({ x: Math.max(margin, Math.min(vw - width - margin, p.x)),
    y: Math.max(margin, Math.min(vh - height - margin, p.y)) }));
  const score = (p: { x: number; y: number }) => occupied.reduce((sum, b) => sum +
    Math.max(0, Math.min(p.x + width, b[2]) - Math.max(p.x, b[0])) *
    Math.max(0, Math.min(p.y + height, b[3]) - Math.max(p.y, b[1])), 0) * 1e6 +
    (p.x - point.x) ** 2 + (p.y - point.y) ** 2;
  return candidates.sort((a, b) => score(a) - score(b))[0]!;
}

/** Read layout only after UI/size changes, never on pointer movement. */
export function observeMapOcclusion(host: HTMLElement, onChange: (boxes: ScreenBox[]) => void) {
  const stage = host.closest('.wm-map-stage') || host.parentElement!;
  let frame = 0, last = '', disposed = false;
  const observed = new Set<Element>();
  const measure = () => {
    frame = 0;
    if (disposed) return;
    const controls = [...stage.querySelectorAll(MAP_OCCLUDERS)];
    for (const el of observed) if (el !== host && !controls.includes(el)) { resize.unobserve(el); observed.delete(el); }
    for (const el of controls) if (!observed.has(el)) { resize.observe(el); observed.add(el); }
    const rect = host.getBoundingClientRect();
    const boxes = controls.map(el => el.getBoundingClientRect()).filter(r => r.width && r.height && r.right > rect.left && r.left < rect.right && r.bottom > rect.top && r.top < rect.bottom)
      .map(r => [r.left - rect.left, r.top - rect.top, r.right - rect.left, r.bottom - rect.top] as ScreenBox);
    const key = JSON.stringify(boxes);
    if (key !== last) { last = key; onChange(boxes); }
  };
  const schedule = () => { if (!frame && !disposed) frame = requestAnimationFrame(measure); };
  const resize = new ResizeObserver(schedule);
  resize.observe(host); observed.add(host);
  const mutation = new MutationObserver(records => {
    if (records.some(r => [...r.addedNodes, ...r.removedNodes].some(n => n instanceof Element && (n.matches(MAP_OCCLUDERS) || n.querySelector(MAP_OCCLUDERS))))) schedule();
  });
  mutation.observe(stage, { childList: true, subtree: true });
  window.addEventListener('resize', schedule);
  window.addEventListener('scroll', schedule, { passive: true });
  stage.addEventListener('transitionend', schedule);
  stage.addEventListener('toggle', schedule, true);
  schedule();
  return { refresh: schedule, destroy() { disposed = true; cancelAnimationFrame(frame); resize.disconnect(); mutation.disconnect();
    window.removeEventListener('resize', schedule); window.removeEventListener('scroll', schedule); stage.removeEventListener('transitionend', schedule); stage.removeEventListener('toggle', schedule, true); } };
}
