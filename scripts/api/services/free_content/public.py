from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from .registry import source_map
from .normalize import permission, utc
from .matching import relate
from .store import decode_state

CANDIDATES_PER_PUBLISHER = 256


def permitted_item(item, sources=None, now=None):
    if not isinstance(item, dict):
        return False
    sources = sources or source_map()
    source = sources.get(item.get("sourceId") or item.get("source_id"))
    if not source:
        return False
    expires = item.get("expires_at")
    active = not expires or (utc(expires) is not None and utc(expires) > (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z"))
    try:
        return permission(source, item)[0] and bool(item.get("display_allowed")) and active
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def filter_payload(payload):
    """Recheck even cached/legacy public paths; never trust an old display flag alone."""
    if not isinstance(payload, dict):
        return payload
    result = dict(payload)
    if isinstance(result.get("items"), list):
        sources = source_map()
        original = len(result["items"])
        result["items"] = [item for item in result["items"] if permitted_item(item, sources)]
        result["count"] = len(result["items"])
        if len(result["items"]) != original:
            result["matchedCount"] = len(result["items"])
            result["empty_reason"] = None if result["items"] else "no_public_content"
    return result


def read_records(storage, *, days=30, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    # One indexed local read: separate table checks/reads add multiple database
    # round trips on the existing cross-region runtime. Missing schema remains
    # an unavailable read, never a fabricated healthy empty result.
    publishers = sorted({source["publisher_name"] for source in source_map().values()})
    placeholders = ",".join("?" for _ in publishers)
    return storage.query_all(
        f"""
        SELECT 'source' AS record_kind, source_id AS id, state_json AS payload,
               NULL AS candidate_group, NULL AS candidate_total
        FROM content_source_state
        UNION ALL
        SELECT 'item' AS record_kind, id, raw_payload AS payload, source AS candidate_group, candidate_total
        FROM (
            SELECT id,raw_payload,source,
                   ROW_NUMBER() OVER (PARTITION BY source ORDER BY (published_at IS NULL), published_at DESC, id) AS candidate_rank,
                   COUNT(*) OVER (PARTITION BY source) AS candidate_total
            FROM content_items
            WHERE provider='free-public' AND (published_at>=? OR published_at IS NULL)
                  AND source IN ({placeholders})
        ) AS candidates
        WHERE candidate_rank <= ?
        """,
        (cutoff, *publishers, CANDIDATES_PER_PUBLISHER),
    )


def payload(storage, *, market=None, market_id=None, limit=20, days=7, now=None, records=None):
    now = now or datetime.now(timezone.utc)
    days = 30 if int(days) == 30 else 7
    cutoff = (now - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    sources = source_map()
    records = read_records(storage, days=days, now=now) if records is None else records
    states = {
        row["id"]: decode_state(row["payload"], row["id"])
        for row in records if row["record_kind"] == "source"
    }
    statuses = []
    for source in sources.values():
        if not source.get("enabled"):
            continue
        state = states.get(source["source_id"], {})
        due = utc(state.get("next_check_at"))
        stale = bool(state.get("snapshot_stale") or (state.get("last_success_at") and due and due < now.isoformat().replace("+00:00", "Z")))
        statuses.append({**source, **state, "status": state.get("status", "not_requested"), "stale": stale})
    items = []
    scanned = 0
    filtered = {}
    totals = {}
    def exclude(reason):
        filtered[reason] = filtered.get(reason, 0) + 1
    if records:
        # Existing provider/time index; bounded candidate recall, no HTTP in reads.
        for row in records:
            if row["record_kind"] != "item":
                continue
            scanned += 1
            if row.get("candidate_group"):
                totals[row["candidate_group"]] = int(row.get("candidate_total") or 0)
            try:
                item = json.loads(row.get("payload") or "{}")
            except (ValueError, TypeError):
                exclude("invalid")
                continue
            if (not isinstance(item, dict) or not isinstance(item.get("title"), str)
                or not isinstance(item.get("url"), str) or not isinstance(item.get("summary", ""), str)
                or any(item.get(key) is not None and not isinstance(item[key], str)
                       for key in ("published_at", "expires_at", "author", "publisher_id", "source_id"))
                or item.get("source_kind") not in {"news_report", "official_release", "alert", "observation"}):
                exclude("invalid")
                continue
            if not permitted_item(item, sources, now):
                exclude("permission_or_expiry")
                continue
            if item.get("expires_at") and item["expires_at"] <= now.isoformat().replace("+00:00", "Z"):
                continue
            if item.get("published_at") and item["published_at"] > now.isoformat().replace("+00:00", "Z"):
                exclude("future")
                continue
            if item.get("published_at") and item["published_at"] < cutoff:
                exclude("window")
                continue
            try:
                if item["source_kind"] == "observation" and float(item.get("magnitude") or 0) < 4.5:
                    exclude("low_magnitude")
                    continue
                relation, reason = relate(market, item) if market else (None, None)
            except (ValueError, TypeError, KeyError):
                exclude("invalid")
                continue
            if market_id is not None and (not market or relation == "unmatched"):
                exclude("unmatched")
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
    items.sort(key=lambda item: item.get("publishedAt") or "", reverse=True)
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
    truncated = any(total > CANDIDATES_PER_PUBLISHER for total in totals.values())
    return {
        "schemaVersion": 2,
        "generatedAt": now.isoformat().replace("+00:00", "Z"),
        "scope": "market" if market_id is not None else "global",
        "marketId": market_id,
        "market_id": market_id,
        "marketTitle": (market or {}).get("title"),
        "items": items[:limit],
        "count": len(items[:limit]),
        "matchedCount": len(items),
        "coverage": {"candidatesScanned": scanned, "candidateLimit": CANDIDATES_PER_PUBLISHER,
                     "limitScope": "publisher", "candidateTotals": totals, "truncated": truncated,
                     "filteredByReason": filtered},
        "sourceMode": "database:free-public",
        "window": {"days": days, "from": cutoff, "to": now.isoformat().replace("+00:00", "Z")},
        "lastSuccessfulCheckAt": max(successful) if successful else None,
        "sources": statuses,
        "status": "unavailable"
        if unavailable
        else "partial"
        if truncated or filtered.get("invalid") or any(s["status"] not in {"ok", "unchanged", "healthy_empty"} or s["stale"] for s in statuses)
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
