from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from agent.common.budget import claim_agent_live_call
from agent.common.gateway_client import call_market_wide_insight_gateway, gateway_configured

from .graph import forecast_run_id
from .service import LENS_ALIASES, VALID_LENSES, build_market_wide_fallback, build_market_wide_insight


SNAPSHOT_NAMESPACE = "agent:market-wide:snapshot"
SNAPSHOT_VERSION = "v1"
DEFAULT_LENSES = ("overview", "special", "trend")
SIGNAL_SNAPSHOT_NAMESPACE_ALPHA = "snapshot:signals:alpha"
SIGNAL_SNAPSHOT_NAMESPACE_WHALES = "snapshot:signals:whales"
SIGNAL_SNAPSHOT_NAMESPACE_SUSPICIOUS = "snapshot:signals:suspicious"


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def snapshot_ttl_seconds() -> int:
    try:
        return max(60, int(os.environ.get("POLYDATA_AGENT_MARKET_WIDE_SNAPSHOT_TTL_SECONDS", "43200")))
    except ValueError:
        return 43200


def snapshot_min_live_interval_seconds() -> int:
    try:
        return max(300, int(os.environ.get("POLYDATA_AGENT_MARKET_WIDE_MIN_LIVE_INTERVAL_SECONDS", "43200")))
    except ValueError:
        return 43200


def normalize_lens(lens: Any) -> str:
    value = str(lens or "overview").strip().lower()
    value = LENS_ALIASES.get(value, value)
    return value if value in VALID_LENSES else "overview"


def snapshot_cache_key(lens: Any) -> str:
    return f"{SNAPSHOT_VERSION}:{normalize_lens(lens)}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _items(payload: Any) -> list[Any]:
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload["items"]
    if isinstance(payload, list):
        return payload
    return []


def _safe_call(helpers: dict[str, Any], name: str, default: Any, *args: Any, **kwargs: Any) -> Any:
    fn = helpers.get(name)
    if not callable(fn):
        return default
    try:
        return fn(*args, **kwargs)
    except Exception:
        logger = getattr(helpers.get("app"), "logger", None)
        if logger is not None:
            logger.exception("agent snapshot source failed source=%s", name)
        return default


def _read_cached_snapshot(helpers: dict[str, Any], namespace: str, cache_key: str) -> dict[str, Any]:
    getter = helpers.get("get_cached_json")
    if callable(getter):
        cached = getter(namespace, cache_key)
        if isinstance(cached, dict):
            return cached
    store = helpers.get("SNAPSHOT_STORE")
    if store is not None and hasattr(store, "get"):
        fresh = store.get(namespace, cache_key)
        if isinstance(fresh, dict):
            return fresh
    if store is not None and hasattr(store, "get_stale"):
        stale = store.get_stale(namespace, cache_key)
        if isinstance(stale, dict):
            return stale
    return {}


def _json_key(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=True)


def _cached_signal_items(helpers: dict[str, Any], namespace: str, cache_key: str, limit: int) -> list[Any]:
    return _items(_read_cached_snapshot(helpers, namespace, cache_key))[:limit]


def _snapshot_age_seconds(snapshot: dict[str, Any]) -> float | None:
    data = snapshot.get("data") if isinstance(snapshot.get("data"), dict) else {}
    generated_at = data.get("snapshotGeneratedAt") or data.get("generatedAt") or snapshot.get("generatedAt")
    parsed = _parse_iso(generated_at)
    if parsed is None:
        return None
    return max(0.0, (_utc_now() - parsed).total_seconds())


def _return_skipped_snapshot(snapshot: dict[str, Any], reason: str) -> dict[str, Any]:
    skipped = dict(snapshot)
    data = dict(skipped.get("data") or {})
    data["source"] = "agent-snapshot"
    data["seedSkipped"] = True
    data["skipReason"] = reason
    data["snapshotLiveAttempted"] = False
    skipped["data"] = data
    skipped["skipped"] = True
    skipped["skipReason"] = reason
    skipped["liveAttempted"] = False
    return skipped


def build_market_wide_seed_payload(helpers: dict[str, Any], lens: Any, *, run_id: str | None = None) -> dict[str, Any]:
    active_markets = _safe_call(helpers, "get_active_markets_snapshot", {}, 80)
    market_groups = _safe_call(helpers, "get_market_groups_payload", {}, "", 1, 60, "active")
    content = _safe_call(helpers, "get_latest_content_payload", {}, 12)
    payload = {
        "lens": normalize_lens(lens),
        "markets": _items(active_markets)[:80],
        "marketGroups": _items(market_groups)[:60],
        "trades": _safe_call(helpers, "get_recent_trades_snapshot", [], 24)[:24],
        "oracle": _safe_call(helpers, "get_recent_oracle_snapshot", [], 24)[:24],
        "content": _items(content)[:12],
        "alphaSignals": _cached_signal_items(helpers, SIGNAL_SNAPSHOT_NAMESPACE_ALPHA, _json_key({"limit": 8}), 8),
        "whaleSignals": _cached_signal_items(
            helpers,
            SIGNAL_SNAPSHOT_NAMESPACE_WHALES,
            _json_key({"limit": 14, "lookbackDays": 7}),
            10,
        ),
        "suspiciousSignals": _cached_signal_items(helpers, SIGNAL_SNAPSHOT_NAMESPACE_SUSPICIOUS, _json_key({"limit": 12}), 10),
    }
    payload["forecastRunId"] = run_id or forecast_run_id(payload)
    return payload


def _seed_live_enabled() -> bool:
    return _truthy_env("POLYDATA_AGENT_SEED_ENABLED", False) and _truthy_env("POLYDATA_AGENT_ENABLED", False)


def _snapshot_from_insight(lens: str, insight: dict[str, Any], *, live_attempted: bool, budget: dict[str, Any] | None) -> dict[str, Any]:
    now = _utc_now()
    ttl = snapshot_ttl_seconds()
    data = dict(insight)
    data["lens"] = lens
    data["cacheStatus"] = "snapshot"
    data["source"] = "agent-snapshot"
    data["snapshotGeneratedAt"] = data.get("generatedAt") or _iso(now)
    data["snapshotExpiresAt"] = _iso(now + timedelta(seconds=ttl))
    data["snapshotLiveAttempted"] = live_attempted
    if budget is not None:
        data["dailyBudget"] = budget
    return {
        "schemaVersion": 1,
        "lens": lens,
        "generatedAt": data["snapshotGeneratedAt"],
        "expiresAt": data["snapshotExpiresAt"],
        "liveAttempted": live_attempted,
        "budget": budget,
        "data": data,
    }


def build_market_wide_snapshot(
    helpers: dict[str, Any],
    lens: Any,
    *,
    live: bool = True,
    force: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    normalized_lens = normalize_lens(lens)
    existing = read_market_wide_snapshot(helpers, normalized_lens, allow_stale=True)
    if existing is not None and not force:
        age_seconds = _snapshot_age_seconds(existing)
        if age_seconds is not None and age_seconds < snapshot_min_live_interval_seconds():
            return _return_skipped_snapshot(existing, "fresh-snapshot")
        if not (live and _seed_live_enabled()):
            return _return_skipped_snapshot(existing, "live-disabled-existing-snapshot")

    payload = build_market_wide_seed_payload(helpers, normalized_lens, run_id=run_id)
    live_allowed = bool(live and _seed_live_enabled())
    budget: dict[str, Any] | None = None
    if live_allowed:
        if gateway_configured():
            budget = {
                "enabled": True,
                "delegatedToGateway": True,
                "kind": f"market-wide-seed:{normalized_lens}",
            }
        else:
            live_allowed, budget = claim_agent_live_call(f"market-wide-seed:{normalized_lens}")
    if live_allowed:
        insight = call_market_wide_insight_gateway(payload) if gateway_configured() else build_market_wide_insight(payload)
        insight.setdefault("forecastRunId", payload.get("forecastRunId"))
        return _snapshot_from_insight(normalized_lens, insight, live_attempted=True, budget=budget)
    reason = "seed-disabled" if live else "fallback-only"
    if budget is not None and budget.get("enabled"):
        reason = "seed-budget-exhausted"
    insight = build_market_wide_fallback(payload, reason=reason)
    return _snapshot_from_insight(normalized_lens, insight, live_attempted=False, budget=budget)


def store_market_wide_snapshot(helpers: dict[str, Any], snapshot: dict[str, Any]) -> None:
    lens = normalize_lens(snapshot.get("lens"))
    key = snapshot_cache_key(lens)
    ttl = snapshot_ttl_seconds()
    setter = helpers.get("set_cached_json")
    if callable(setter):
        setter(SNAPSHOT_NAMESPACE, key, snapshot, ttl)
    store = helpers.get("SNAPSHOT_STORE")
    if store is not None and hasattr(store, "set"):
        store.set(SNAPSHOT_NAMESPACE, key, snapshot, ttl)


def read_market_wide_snapshot(helpers: dict[str, Any], lens: Any, *, allow_stale: bool = True) -> dict[str, Any] | None:
    key = snapshot_cache_key(lens)
    getter = helpers.get("get_cached_json")
    if callable(getter):
        cached = getter(SNAPSHOT_NAMESPACE, key)
        if isinstance(cached, dict):
            return cached
    store = helpers.get("SNAPSHOT_STORE")
    if store is not None and hasattr(store, "get"):
        cached = store.get(SNAPSHOT_NAMESPACE, key)
        if isinstance(cached, dict):
            return cached
    if allow_stale and store is not None and hasattr(store, "get_stale"):
        stale = store.get_stale(SNAPSHOT_NAMESPACE, key)
        if isinstance(stale, dict):
            stale = dict(stale)
            data = dict(stale.get("data") or {})
            data["cacheStatus"] = "stale-snapshot"
            data["source"] = "agent-snapshot"
            stale["data"] = data
            return stale
    return None


def snapshot_response(snapshot: dict[str, Any]) -> dict[str, Any]:
    data = snapshot.get("data")
    if not isinstance(data, dict):
        return {}
    response = dict(data)
    response.setdefault("lens", normalize_lens(snapshot.get("lens")))
    response.setdefault("source", "agent-snapshot")
    response.setdefault("cacheStatus", "snapshot")
    response.setdefault("snapshotGeneratedAt", snapshot.get("generatedAt"))
    response.setdefault("snapshotExpiresAt", snapshot.get("expiresAt"))
    return response


def seed_market_wide_snapshots(
    helpers: dict[str, Any],
    lenses: list[str] | tuple[str, ...] = DEFAULT_LENSES,
    *,
    live: bool = True,
    force: bool = False,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    run_id = f"fig-seed-{_iso(_utc_now()).replace(':', '').replace('-', '')}"
    for lens in lenses:
        snapshot = build_market_wide_snapshot(helpers, lens, live=live, force=force, run_id=run_id)
        if not snapshot.get("skipped"):
            store_market_wide_snapshot(helpers, snapshot)
        snapshots.append(snapshot)
    return snapshots
