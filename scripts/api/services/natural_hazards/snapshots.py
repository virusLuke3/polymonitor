from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict

from .contracts import SourceFetchResult
from .source_health import SOURCE_COVERAGE


SNAPSHOT_NAMESPACE = "snapshot:world:natural-hazards"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_with_snapshot(
    *,
    key: str,
    snapshot_store: Any,
    fetcher: Callable[[], Dict[str, Any]],
    ttl_seconds: int,
) -> SourceFetchResult:
    fresh = snapshot_store.get(SNAPSHOT_NAMESPACE, key)
    if isinstance(fresh, dict) and isinstance(fresh.get("events"), list):
        return {
            "key": key,
            "status": "ok",
            "coverage": SOURCE_COVERAGE[key],
            "events": fresh["events"],
            "fetchedAt": fresh.get("fetchedAt"),
            "dataUpdatedAt": fresh.get("dataUpdatedAt"),
            "staleAfter": fresh.get("staleAfter"),
            "lastSuccessAt": fresh.get("fetchedAt"),
            "errorCode": None,
        }

    try:
        provider_result = fetcher()
        if not isinstance(provider_result, dict) or not isinstance(provider_result.get("events"), list):
            raise ValueError(f"{key}-provider-contract")
        fetched_at = utc_now()
        snapshot = {
            "events": provider_result["events"],
            "fetchedAt": iso_utc(fetched_at),
            "dataUpdatedAt": provider_result.get("data_updated_at"),
            "staleAfter": iso_utc(fetched_at + timedelta(seconds=ttl_seconds)),
        }
        snapshot_store.set(SNAPSHOT_NAMESPACE, key, snapshot, ttl_seconds)
        return {
            "key": key,
            "status": "ok",
            "coverage": SOURCE_COVERAGE[key],
            "events": snapshot["events"],
            "fetchedAt": snapshot["fetchedAt"],
            "dataUpdatedAt": snapshot["dataUpdatedAt"],
            "staleAfter": snapshot["staleAfter"],
            "lastSuccessAt": snapshot["fetchedAt"],
            "errorCode": None,
        }
    except Exception as exc:
        stale = snapshot_store.get_stale(SNAPSHOT_NAMESPACE, key)
        if isinstance(stale, dict) and isinstance(stale.get("events"), list):
            return {
                "key": key,
                "status": "degraded",
                "coverage": SOURCE_COVERAGE[key],
                "events": stale["events"],
                "fetchedAt": stale.get("fetchedAt"),
                "dataUpdatedAt": stale.get("dataUpdatedAt"),
                "staleAfter": stale.get("staleAfter"),
                "lastSuccessAt": stale.get("fetchedAt"),
                "errorCode": f"{key}-stale-after-{exc.__class__.__name__}",
            }
        return {
            "key": key,
            "status": "error",
            "coverage": SOURCE_COVERAGE[key],
            "events": [],
            "fetchedAt": None,
            "dataUpdatedAt": None,
            "staleAfter": None,
            "lastSuccessAt": None,
            "errorCode": f"{key}-{exc.__class__.__name__}",
        }
