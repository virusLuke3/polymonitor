from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from threading import Lock
from typing import Any, Callable, Dict

from .contracts import SourceFetchResult
from .source_health import SOURCE_COVERAGE


SNAPSHOT_NAMESPACE = "snapshot:world:natural-hazards"
CONDITION_NAMESPACE = SNAPSHOT_NAMESPACE + ":condition"
MAX_STALE_SECONDS = {
    "usgs": 3600, "usgs-volcano-cap": 21600, "nws": 900, "eccc": 900, "swic": 900,
    "nhc": 3600, "eonet": 21600, "gdacs": 21600,
    "firms": 5400, "climate-anomaly": 7 * 86400,
}
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def stale_source_result(snapshot_store: Any, key: str, error_code: str) -> SourceFetchResult | None:
    stale = snapshot_store.get_stale(SNAPSHOT_NAMESPACE, key)
    if not isinstance(stale, dict) or not isinstance(stale.get("events"), list):
        return None
    try:
        fetched = datetime.fromisoformat(str(stale.get("fetchedAt") or "").replace("Z", "+00:00"))
        age = (utc_now() - fetched).total_seconds()
        if age < 0 or age > MAX_STALE_SECONDS[key]:
            return None
    except (ValueError, TypeError, KeyError):
        return None
    return {
        "key": key,
        "status": "degraded",
        "coverage": SOURCE_COVERAGE[key],
        "events": stale["events"],
        "fetchedAt": stale.get("fetchedAt"),
        "dataUpdatedAt": stale.get("dataUpdatedAt"),
        "staleAfter": stale.get("staleAfter"),
        "lastSuccessAt": stale.get("fetchedAt"),
        "errorCode": error_code,
    }


def cached_source_result(snapshot_store: Any, key: str) -> SourceFetchResult | None:
    fresh = snapshot_store.get(SNAPSHOT_NAMESPACE, key)
    if isinstance(fresh, dict) and isinstance(fresh.get("events"), list):
        return {
            "key": key,
            "status": "partial" if fresh.get("isPartial") else "ok",
            "coverage": SOURCE_COVERAGE[key],
            "events": fresh["events"],
            "fetchedAt": fresh.get("fetchedAt"),
            "dataUpdatedAt": fresh.get("dataUpdatedAt"),
            "staleAfter": fresh.get("staleAfter"),
            "lastSuccessAt": fresh.get("fetchedAt"),
            "errorCode": None,
        }
    stale = stale_source_result(snapshot_store, key, f"{key}-cached-stale")
    if stale:
        condition = snapshot_store.get_stale(CONDITION_NAMESPACE, key) or {}
        remaining = float(condition.get("retryAt", 0)) - utc_now().timestamp()
        if remaining > 0:
            stale.update(errorCode=condition.get("errorCode"), retryAfterSeconds=remaining)
            if condition.get("condition"): stale["condition"] = condition["condition"]
    return stale


def source_refresh_due(result: Dict[str, Any], ttl_seconds: int) -> bool:
    """Refresh before expiry without changing the original freshness deadline.

    At most 30 seconds / 40% of the source TTL is reserved for acquisition.
    A 60-second NWS cache therefore never polls upstream faster than 36 seconds.
    """
    try:
        deadline = datetime.fromisoformat(str(result.get("staleAfter") or "").replace("Z", "+00:00"))
        return (deadline - utc_now()).total_seconds() <= min(30, ttl_seconds * .4)
    except (ValueError, TypeError):
        return False


def fetch_with_snapshot(
    *,
    key: str,
    snapshot_store: Any,
    source_lock: Lock,
    fetcher: Callable[[], Dict[str, Any]],
    ttl_seconds: int,
    refresh_ahead: bool = False,
) -> SourceFetchResult:
    def fresh_result():
        fresh = snapshot_store.get(SNAPSHOT_NAMESPACE, key)
        if not isinstance(fresh, dict) or not isinstance(fresh.get("events"), list):
            return None
        if refresh_ahead and source_refresh_due(fresh, ttl_seconds):
            return None
        return {"key": key, "status": "partial" if fresh.get("isPartial") else "ok",
            "coverage": SOURCE_COVERAGE[key], "events": fresh["events"],
            "fetchedAt": fresh.get("fetchedAt"), "dataUpdatedAt": fresh.get("dataUpdatedAt"),
            "staleAfter": fresh.get("staleAfter"), "lastSuccessAt": fresh.get("fetchedAt"), "errorCode": None}

    def failure_result(error_code, condition=None):
        stale = stale_source_result(snapshot_store, key, error_code)
        return {**(stale or {"key": key, "status": "error", "coverage": SOURCE_COVERAGE[key],
            "events": [], "fetchedAt": None, "dataUpdatedAt": None, "staleAfter": None,
            "lastSuccessAt": None, "errorCode": error_code}), **(condition or {})}

    fresh = fresh_result()
    if fresh is not None:
        return fresh
    shared_lock = getattr(snapshot_store, "fetch_lock", None)
    try:
        with source_lock, (shared_lock(SNAPSHOT_NAMESPACE, key, timeout=6) if shared_lock else nullcontext()):
            fresh = fresh_result()
            if fresh is not None:
                return fresh
            previous = snapshot_store.get_stale(CONDITION_NAMESPACE, key) or {}
            remaining = float(previous.get("retryAt", 0)) - utc_now().timestamp()
            if remaining > 0:
                return failure_result(previous["errorCode"], {
                    **({"condition": previous["condition"]} if previous.get("condition") else {}),
                    "retryAfterSeconds": remaining})
            try:
                provider_result = fetcher()
                if not isinstance(provider_result, dict) or not isinstance(provider_result.get("events"), list):
                    raise ValueError(f"{key}-provider-contract")
                fetched_at = utc_now()
                snapshot = {"events": provider_result["events"], "isPartial": bool(provider_result.get("is_partial")),
                    "fetchedAt": iso_utc(fetched_at), "dataUpdatedAt": provider_result.get("data_updated_at"),
                    "staleAfter": iso_utc(fetched_at + timedelta(seconds=ttl_seconds))}
                snapshot_store.set(SNAPSHOT_NAMESPACE, key, snapshot, ttl_seconds)
                # Reset failure history independently of the successful data timestamp.
                snapshot_store.set(CONDITION_NAMESPACE, key, {"retryAt": 0, "failures": 0}, ttl_seconds)
                return {"key": key, "status": "partial" if snapshot["isPartial"] else "ok",
                    "coverage": SOURCE_COVERAGE[key], "events": snapshot["events"],
                    "fetchedAt": snapshot["fetchedAt"], "dataUpdatedAt": snapshot["dataUpdatedAt"],
                    "staleAfter": snapshot["staleAfter"], "lastSuccessAt": snapshot["fetchedAt"], "errorCode": None}
            except Exception as exc:
                response = getattr(exc, "response", None)
                http_status = getattr(response, "status_code", None)
                failures = int(previous.get("failures", 0)) + 1
                retry_seconds = min(120, 15 * 2 ** min(failures - 1, 3))
                condition = {}
                if http_status in {401, 403, 429}:
                    condition["condition"] = "blocked" if http_status != 429 else "throttled"
                    value = str(getattr(response, "headers", {}).get("Retry-After") or "60")
                    try:
                        retry_seconds = float(value)
                    except ValueError:
                        try: retry_seconds = (parsedate_to_datetime(value) - utc_now()).total_seconds()
                        except (ValueError, TypeError): retry_seconds = 60
                    retry_seconds = max(1, retry_seconds) if http_status == 429 else 300
                condition["retryAfterSeconds"] = retry_seconds
                error_code = f"{key}-http-{http_status}" if http_status else f"{key}-stale-after-{exc.__class__.__name__}"
                snapshot_store.set(CONDITION_NAMESPACE, key, {"retryAt": utc_now().timestamp() + retry_seconds,
                    "failures": failures, "errorCode": error_code, **condition}, max(1, int(retry_seconds)))
                return failure_result(error_code, condition)
    except TimeoutError:
        return failure_result(f"{key}-shared-acquisition-deadline")
