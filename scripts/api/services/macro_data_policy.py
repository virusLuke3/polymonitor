"""Display bounds for macro snapshots; never delete or rewrite the source archive."""
from __future__ import annotations

from api.services.seed_recovery import age_seconds


def display_age(settings, name: str, default: int) -> int:
    return max(1, int(getattr(settings, name, default) or default))


def row_clock(row: dict):
    metadata = row.get("metadata") or {}
    return row.get("fetchedAt") or metadata.get("fetchedAt") or metadata.get("verifiedAt")


def bounded_rows(payload: dict, *, now: str, max_age: int, clock=row_clock) -> list[dict]:
    """Mutate only a caller-owned display copy, preserving acquisition/observation clocks."""
    original = [row for row in payload.get("items", []) if isinstance(row, dict)]
    kept = [row for row in original if age_seconds(clock(row), now) < max_age]
    expired = len(original) - len(kept)
    payload["displayRetention"] = {"maxAgeSeconds": max_age, "expiredItemCount": expired,
                                   "unknownClockItemCount": sum(not clock(row) for row in original)}
    if expired:
        payload["status"] = "degraded" if kept else "expired"
        sources = dict(payload.get("sources") or {})
        payload["acquisitionSources"] = dict(sources)
        expired_keys = {row.get("key") for row in original if row not in kept}
        payload["sources"] = {key: "expired" if (not kept or key in expired_keys)
                              and value in {"ok", "empty"} else value for key, value in sources.items()}
    payload["items"] = kept
    return kept


def read_seeded(store, reader, namespace: str, key: str):
    """A configured SQLite store owns truth, including an expired TTL or a miss."""
    if store is not None:
        payload = store.get(namespace, key)
        if isinstance(payload, dict):
            return {**payload, "cacheMode": "sqlite-seed"}
        payload = store.get_stale(namespace, key)
        return {**payload, "cacheMode": "stale-seed"} if isinstance(payload, dict) else None
    if callable(reader):
        try:
            payload = reader(namespace, key)
            if isinstance(payload, dict):
                return {**payload, "cacheMode": "redis-seed"}
        except Exception:
            pass
    return None
