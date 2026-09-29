import { clearMapPosition } from './mapOcclusion';
import type { ScreenBox } from './layerFactories/eventClusters';
import type { WorldEventTooltipModel } from './hoverTooltip';
import type { MapHoverPosition } from './MapRenderer';

/** Renderer-owned SVG tooltip; hover never crosses into Preact/App state. */
export class RendererTooltip {
  private occupied: ScreenBox[] = [];
  setOcclusions(boxes: ScreenBox[]) { this.occupied = boxes; }
  private element: HTMLDivElement | null = null;

  constructor(private readonly host: HTMLElement) {}

  show(model: WorldEventTooltipModel | null, position: MapHoverPosition | null) {
    if (!model || !position) {
      this.clear();
      return;
    }
    const element = this.element || this.createElement();
    element.replaceChildren();
    const kicker = document.createElement('span');
    kicker.className = 'wm-world-event-tooltip-kicker';
    kicker.textContent = model.kicker;
    const title = document.createElement('strong');
    title.textContent = model.title;
    element.append(kicker, title);
    for (const detail of model.details) {
      const line = document.createElement('small');
      line.textContent = detail;
      element.append(line);
    }
    element.hidden = false;
    const target = clearMapPosition({ x: position.x + 12, y: position.y + 12 },
      [element.offsetWidth, element.offsetHeight], [this.host.clientWidth, this.host.clientHeight], this.occupied);
    element.style.transform = 'none';
    element.style.left = `${target.x}px`;
    element.style.top = `${target.y}px`;

  }

  clear() {
    if (this.element) this.element.hidden = true;
  }

  destroy() {
    this.element?.remove();
    this.element = null;
  }

  private createElement() {
    const element = document.createElement('div');
    element.className = 'deck-tooltip wm-weather-deck-tooltip wm-world-event-svg-tooltip wm-world-event-tooltip wm-world-event-renderer-tooltip';
    element.setAttribute('role', 'status');
    element.hidden = true;
    this.host.append(element);
    this.element = element;
    return element;
  }
}
