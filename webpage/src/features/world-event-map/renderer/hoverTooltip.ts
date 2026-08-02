import type { GeoEvent } from '../domain/types';
import type { EventCluster } from './layerFactories';
import { isHazardEvent } from './layerFactories/shared';

export type WorldEventPickedObject =
  | GeoEvent
  | EventCluster
  | { properties?: { event?: GeoEvent } };

export function pickedWorldEvent(object?: WorldEventPickedObject | null): GeoEvent | null {
  if (!object) return null;
  if ('kind' in object && object.kind === 'event-cluster') return null;
  const featureEvent = (object as { properties?: { event?: GeoEvent } }).properties?.event;
  if (featureEvent?.id) return featureEvent;
  return object as GeoEvent;
}

export function pickedWorldEventCluster(object?: WorldEventPickedObject | null): EventCluster | null {
  return object && 'kind' in object && object.kind === 'event-cluster' ? object : null;
}

function escapeHtml(value: unknown) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function humanize(value: string) {
  return value.replace(/-/g, ' ').replace(/\b\w/g, (letter: string) => letter.toUpperCase());
}

function eventKind(event: GeoEvent) {
  if (isHazardEvent(event)) return humanize(event.hazardKind);
  const entity = String(event.properties.mapEntity || '').trim();
  return humanize(entity || event.category);
}

function eventMeta(event: GeoEvent) {
  const parts = [event.severity.toUpperCase()];
  if (event.locationLabel) parts.push(event.locationLabel);
  const provider = event.sources.find((source) => source.provider)?.provider;
  if (provider) parts.push(provider);
  return parts.map(escapeHtml).join(' · ');
}

/**
 * WorldMonitor-style lightweight hover content. Full evidence remains in the
 * click inspector; this formatter is intentionally synchronous and bounded.
 */
export function worldEventTooltipHtml(object?: WorldEventPickedObject | null): string | null {
  const cluster = pickedWorldEventCluster(object);
  if (cluster) {
    return [
      '<div class="wm-world-event-tooltip">',
      `<span class="wm-world-event-tooltip-kicker">${escapeHtml(cluster.severity.toUpperCase())} CLUSTER</span>`,
      `<strong>${cluster.count.toLocaleString('en-US')} mapped events</strong>`,
      '<small>Click to expand this area</small>',
      '</div>',
    ].join('');
  }

  const event = pickedWorldEvent(object);
  if (!event) return null;
  return [
    '<div class="wm-world-event-tooltip">',
    `<span class="wm-world-event-tooltip-kicker">${escapeHtml(eventKind(event))}</span>`,
    `<strong>${escapeHtml(event.title)}</strong>`,
    `<small>${eventMeta(event)}</small>`,
    '</div>',
  ].join('');
}
