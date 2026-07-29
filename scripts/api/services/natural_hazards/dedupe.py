from __future__ import annotations

from typing import Any, Dict, Iterable


def latest_revision(events: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    by_id: dict[str, Dict[str, Any]] = {}
    for event in events:
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        current = by_id.get(event_id)
        event_time = str(event.get("updatedAt") or event.get("occurredAt") or "")
        current_time = str((current or {}).get("updatedAt") or (current or {}).get("occurredAt") or "")
        if current is None or event_time >= current_time:
            by_id[event_id] = event
    return list(by_id.values())
