import { useMemo, useState } from 'preact/hooks';
import type { GeoEvent, GeoEventSeverity } from '../domain/types';

const LIST_RENDER_LIMIT = 300;
const SEVERITY_RANK: Record<GeoEventSeverity, number> = {
  critical: 3,
  warning: 2,
  watch: 1,
  info: 0,
};

function eventTimestamp(event: GeoEvent) {
  const parsed = Date.parse(event.updatedAt || event.occurredAt || '');
  return Number.isFinite(parsed) ? parsed : 0;
}

export function visibleAccessibleEvents(events: GeoEvent[], selectedEventId: string | null) {
  const ordered = [...events].sort((left, right) => (
    SEVERITY_RANK[right.severity] - SEVERITY_RANK[left.severity]
    || eventTimestamp(right) - eventTimestamp(left)
    || left.title.localeCompare(right.title)
  ));
  const visible = ordered.slice(0, LIST_RENDER_LIMIT);
  const selected = selectedEventId
    ? ordered.find((event) => event.id === selectedEventId)
    : null;
  if (selected && !visible.some((event) => event.id === selected.id)) visible.unshift(selected);
  return visible;
}

export function EventList({
  events,
  selectedEventId,
  onSelect,
}: {
  events: GeoEvent[];
  selectedEventId: string | null;
  onSelect: (eventId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const visibleEvents = useMemo(
    () => visibleAccessibleEvents(events, selectedEventId),
    [events, selectedEventId],
  );

  return (
    <div className={`wm-world-event-list ${open ? 'is-open' : ''}`}>
      <button
        type="button"
        className="wm-world-event-list-toggle"
        aria-expanded={open}
        aria-controls="wm-world-event-list-panel"
        onClick={() => setOpen((current) => !current)}
      >
        EVENTS {events.length}
      </button>
      {open ? (
        <section id="wm-world-event-list-panel" aria-labelledby="wm-world-event-list-heading">
          <header>
            <h2 id="wm-world-event-list-heading">Active mapped events</h2>
            <span>
              {visibleEvents.length === events.length
                ? `${events.length} events`
                : `Top ${visibleEvents.length} of ${events.length}`}
            </span>
          </header>
          {visibleEvents.length ? (
            <ol>
              {visibleEvents.map((event) => (
                <li key={event.id}>
                  <button
                    type="button"
                    className={event.id === selectedEventId ? 'is-selected' : ''}
                    aria-current={event.id === selectedEventId ? 'true' : undefined}
                    onClick={() => onSelect(event.id)}
                  >
                    <span className={`severity-${event.severity}`}>{event.severity}</span>
                    <strong>{event.title}</strong>
                    <small>{event.locationLabel || 'Mapped geometry'}</small>
                  </button>
                </li>
              ))}
            </ol>
          ) : <p>No events match the current layer, time and severity filters.</p>}
        </section>
      ) : null}
    </div>
  );
}
