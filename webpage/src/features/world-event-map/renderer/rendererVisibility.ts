export type ViewportRect = Pick<DOMRectReadOnly, 'top' | 'right' | 'bottom' | 'left' | 'width' | 'height'>;

export function rectIntersectsViewport(
  rect: ViewportRect,
  viewportWidth: number,
  viewportHeight: number,
) {
  if (rect.width <= 0 || rect.height <= 0 || viewportWidth <= 0 || viewportHeight <= 0) return false;
  return rect.bottom > 0
    && rect.right > 0
    && rect.top < viewportHeight
    && rect.left < viewportWidth;
}

// One visible safe area for both renderers; fixed mobile reports and a scrolled
// page must be measured in viewport coordinates before converting to map pixels.
export function selectionPanOffset(host: HTMLElement, point: { x: number; y: number }) {
  const rect = host.getBoundingClientRect();
  const left = Math.max(32, 16 - rect.left);
  let right = Math.min(rect.width - 64, innerWidth - rect.left - 16);
  const top = Math.max(32, 16 - rect.top);
  let bottom = Math.min(rect.height - 64, innerHeight - rect.top - 80);
  for (const panel of host.closest('.wm-map-stage')?.querySelectorAll('.wm-event-inspector') || []) {
    const box = panel.getBoundingClientRect();
    if (!rectIntersectsViewport(box, innerWidth, innerHeight)) continue;
    if (box.width > rect.width * 0.7) bottom = Math.min(bottom, box.top - rect.top - 24);
    else right = Math.min(right, box.left - rect.left - 24);
  }
  right = Math.max(left, right); bottom = Math.max(top, bottom);
  return { x: point.x - Math.max(left, Math.min(right, point.x)),
    y: point.y - Math.max(top, Math.min(bottom, point.y)) };
}
