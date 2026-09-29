import { clearMapPosition } from './mapOcclusion';
import type { ScreenBox } from './layerFactories/eventClusters';
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
export function selectionPanOffset(host: HTMLElement, point: { x: number; y: number }, occupied: ScreenBox[] = []) {
  const rect = host.getBoundingClientRect();
  const viewportBoxes: ScreenBox[] = [...occupied];
  if (rect.top < 0) viewportBoxes.push([0, 0, rect.width, -rect.top]);
  if (rect.bottom > innerHeight) viewportBoxes.push([0, innerHeight - rect.top, rect.width, rect.height]);
  const target = clearMapPosition({ x: point.x - 16, y: point.y - 16 }, [32, 32], [rect.width, rect.height], viewportBoxes, 16);
  return { x: point.x - target.x - 16, y: point.y - target.y - 16 };
}
