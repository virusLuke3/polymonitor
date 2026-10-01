from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from .registry import source_map
from .normalize import permission, utc
from .matching import relate
from .store import source_states


def permitted_item(item, sources=None):
    sources = sources or source_map()
    source = sources.get(item.get("sourceId") or item.get("source_id"))
    if not source:
        return False
    expires = item.get("expires_at")
    active = not expires or expires > datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return permission(source, item)[0] and bool(item.get("display_allowed")) and active


def filter_payload(payload):
    """Recheck even cached/legacy public paths; never trust an old display flag alone."""
    if not isinstance(payload, dict):
        return payload
    result = dict(payload)
    if isinstance(result.get("items"), list):
        result["items"] = [item for item in result["items"] if permitted_item(item)]
        result["count"] = len(result["items"])
    return result


def payload(storage, *, market=None, market_id=None, limit=20, days=7, now=None):
    now = now or datetime.now(timezone.utc)
    days = 30 if int(days) == 30 else 7
    cutoff = (now - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    sources = source_map()
    states = source_states(storage)
    statuses = []
    for source in sources.values():
        state = states.get(source["source_id"], {})
        due = utc(state.get("next_check_at"))
        stale = bool(state.get("last_success_at") and due and due < now.isoformat().replace("+00:00", "Z"))
        statuses.append({**source, **state, "status": state.get("status", "not_requested"), "stale": stale})
    items = []
    if storage.table_exists("content_items"):
        # Existing provider/time index; bounded candidate recall, no HTTP in reads.
        rows = storage.query_all(
            "SELECT id,raw_payload FROM content_items WHERE provider='free-public' AND (published_at>=? OR published_at IS NULL) ORDER BY published_at DESC LIMIT 2000",
            (cutoff,),
        )
        for row in rows:
            try:
                item = json.loads(row.get("raw_payload") or "{}")
            except (ValueError, TypeError):
                continue
            if not permitted_item(item, sources):
                continue
            if item.get("expires_at") and item["expires_at"] <= now.isoformat().replace("+00:00", "Z"):
                continue
            if item.get("published_at") and item["published_at"] > now.isoformat().replace("+00:00", "Z"):
                continue
            if item["source_kind"] == "observation" and float(item.get("magnitude") or 0) < 4.5:
                continue
            relation, reason = relate(market, item) if market else (None, None)
            if market_id is not None and (not market or relation == "unmatched"):
                continue
            source = sources[item["source_id"]]
            summary = item.get("summary", "") if source.get("display_excerpt_allowed") else ""
            state = states.get(item["source_id"], {})
            items.append(
                {
                    **item,
                    "id": row["id"],
                    "contentType": "news",
                    "source": source["publisher_name"],
                    "sourceId": item["source_id"],
                    "sourceKind": item["source_kind"],
                    "publishedAt": item.get("published_at"),
                    "updatedAt": item.get("updated_at"),
                    "eventTime": item.get("event_time"),
                    "author": item.get("author"),
                    "summary": summary[:320],
                    "excerptFull": summary,
                    "excerptTruncated": len(summary) > 320,
                    "excerptOrigin": item.get("excerpt_origin"),
                    "permissionBasis": source["permission_basis"],
                    "policyUrl": source["policy_url"],
                    "licenseUrl": source.get("license_url"),
                    "relation": relation,
                    "relationReason": reason,
                    "sourceStatus": state.get("status", "not_requested"),
                }
            )
    if market_id is None:
        # Round-robin publishers, preserving chronology inside each publisher.
        groups = {}
        for item in items:
            group = groups.setdefault(item["publisher_id"], [])
            # High-frequency weather feeds supplement the default list.
            if item["publisher_id"] in {"nws", "usgs", "nhc"} and len(group) >= 4:
                continue
            group.append(item)
        balanced = []
        while any(groups.values()):
            for group in groups.values():
                if group:
                    balanced.append(group.pop(0))
        items = balanced
    successful = [s.get("last_success_at") for s in statuses if s.get("last_success_at")]
    unavailable = all(s["status"] not in {"ok", "unchanged", "healthy_empty"} for s in statuses)
    return {
        "scope": "market" if market_id is not None else "global",
        "marketId": market_id,
        "market_id": market_id,
        "marketTitle": (market or {}).get("title"),
        "items": items[:limit],
        "count": len(items[:limit]),
        "matchedCount": len(items),
        "sourceMode": "database:free-public",
        "window": {"days": days, "from": cutoff, "to": now.isoformat().replace("+00:00", "Z")},
        "lastSuccessfulCheckAt": max(successful) if successful else None,
        "sources": statuses,
        "status": "unavailable"
        if unavailable
        else "partial"
        if any(s["status"] not in {"ok", "unchanged", "healthy_empty"} for s in statuses)
        else "ready",
        "empty_reason": (
            "sources_unavailable"
            if unavailable
            else "no_market_match"
            if market_id is not None
            else "no_public_content"
        )
        if not items
        else None,
    }


def filter_bootstrap(value):
    if not isinstance(value, dict):
        return value
    result = dict(value)
    for key in ("contentPreview", "latestContentPreview"):
        if isinstance(result.get(key), list):
            result[key] = [item for item in result[key] if permitted_item(item)]
    return result


def filter_workspace(value):
    if not isinstance(value, dict):
        return value
    result = dict(value)
    if isinstance(result.get("content"), dict):
        result["content"] = filter_payload(result["content"])
    return result
