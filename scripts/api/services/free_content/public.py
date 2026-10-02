from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from .registry import source_map
from .normalize import permission, utc
from .matching import relate, market_coverage
from .store import decode_state

CANDIDATES_PER_PUBLISHER = 512
RAW_CANDIDATES_PER_PUBLISHER = 2048
# One bounded collector cycle (90s) plus the longest watch sleep (60s).
CHECK_GRACE_SECONDS = 150
MAX_PUBLIC_ITEMS = 100


def source_is_stale(state, now):
    due = utc(state.get("next_check_at"))
    overdue = bool(state.get("last_success_at") and due and
        datetime.fromisoformat(due.replace("Z", "+00:00")) + timedelta(seconds=CHECK_GRACE_SECONDS) < now)
    return bool(state.get("snapshot_stale") or overdue)


def eligible_item(raw, sources, cutoff, now):
    """Apply the same public filters before a record consumes a candidate slot."""
    try:
        item = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return None, "invalid"
    if (not isinstance(item, dict) or not isinstance(item.get("title"), str)
        or not isinstance(item.get("url"), str) or not isinstance(item.get("summary", ""), str)
        or any(item.get(key) is not None and not isinstance(item[key], str)
               for key in ("published_at", "expires_at", "author", "publisher_id", "source_id"))
        or item.get("source_kind") not in {"news_report", "official_release", "alert", "observation"}):
        return None, "invalid"
    if any(item.get(key) and not utc(item[key]) for key in ("published_at", "expires_at")):
        return None, "invalid"
    if not permitted_item(item, sources, now):
        return None, "permission_or_expiry"
    stamp = now.isoformat().replace("+00:00", "Z")
    if item.get("published_at") and item["published_at"] > stamp:
        return None, "future"
    if item.get("published_at") and item["published_at"] < cutoff:
        return None, "window"
    try:
        if item["source_kind"] == "observation" and float(item.get("magnitude") or 0) < 4.5:
            return None, "low_magnitude"
    except (ValueError, TypeError):
        return None, "invalid"
    return item, None


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
    sources = source_map()
    publishers = sorted({source["publisher_name"] for source in sources.values()})
    placeholders = ",".join("?" for _ in publishers)
    records = storage.query_all(
        f"""
        SELECT 'source' AS record_kind, source_id AS id, state_json AS payload,
               NULL AS candidate_group, NULL AS candidate_total, NULL AS candidate_rank
        FROM content_source_state
        UNION ALL
        SELECT 'item' AS record_kind, id, raw_payload AS payload, source AS candidate_group, candidate_total, candidate_rank
        FROM (
            SELECT id,raw_payload,source,
                   ROW_NUMBER() OVER (PARTITION BY source ORDER BY (published_at IS NULL), published_at DESC, id) AS candidate_rank,
                   COUNT(*) OVER (PARTITION BY source) AS candidate_total
            FROM content_items
            WHERE provider='free-public' AND (published_at>=? OR published_at IS NULL)
                  AND source IN ({placeholders})
        ) AS candidates
        WHERE candidate_rank <= ?
        ORDER BY record_kind DESC, candidate_group, candidate_rank
        """,
        (cutoff, *publishers, RAW_CANDIDATES_PER_PUBLISHER),
    )
    result, coverage = [], {}
    for row in records:
        if row["record_kind"] == "source":
            result.append(row)
            continue
        publisher = row["candidate_group"]
        stats = coverage.setdefault(publisher, {"rawTotal": int(row["candidate_total"] or 0),
            "rawScanned": 0, "eligibleTotal": 0, "filteredByReason": {}})
        stats["rawScanned"] += 1
        _, reason = eligible_item(row["payload"], sources, cutoff, now)
        if reason:
            stats["filteredByReason"][reason] = stats["filteredByReason"].get(reason, 0) + 1
            continue
        stats["eligibleTotal"] += 1
        if stats["eligibleTotal"] <= CANDIDATES_PER_PUBLISHER:
            result.append(row)
    result.extend({"record_kind": "coverage", "id": publisher, "payload": json.dumps(stats)}
                  for publisher, stats in coverage.items())
    return result


def payload(storage, *, market=None, market_id=None, limit=20, days=7, now=None, records=None):
    now = now or datetime.now(timezone.utc)
    days = 30 if int(days) == 30 else 7
    limit = min(MAX_PUBLIC_ITEMS, max(1, int(limit)))
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
        stale = source_is_stale(state, now)
        statuses.append({**source, **state, "status": state.get("status", "not_requested"), "stale": stale})
    items = []
    scanned = 0
    candidate_stats = {row["id"]: json.loads(row["payload"]) for row in records if row["record_kind"] == "coverage"}
    filtered = {}
    for stats in candidate_stats.values():
        for reason, count in stats["filteredByReason"].items():
            filtered[reason] = filtered.get(reason, 0) + count
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
            item, reason = eligible_item(row.get("payload"), sources, cutoff, now)
            if reason:
                exclude(reason)
                continue
            try:
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
            # Scale the supplementary event quota with the requested page;
            # keep the original four-item quota for small preview consumers.
            if item["publisher_id"] in {"nws", "usgs", "nhc"} and len(group) >= max(4, (limit + 4) // 5):
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
    if candidate_stats:
        totals = {publisher: stats["eligibleTotal"] for publisher, stats in candidate_stats.items()}
    truncated = any(total > CANDIDATES_PER_PUBLISHER for total in totals.values()) or any(
        stats["rawTotal"] > stats["rawScanned"] for stats in candidate_stats.values())
    coverage = market_coverage(market, sources.values(), items) if market_id is not None else None
    return {
        "schemaVersion": 2,
        "generatedAt": now.isoformat().replace("+00:00", "Z"),
        "scope": "market" if market_id is not None else "global",
        "marketId": market_id,
        "market_id": market_id,
        "marketTitle": (market or {}).get("title"),
        "marketCoverage": coverage,
        "items": items[:limit],
        "count": len(items[:limit]),
        "matchedCount": len(items),
        "coverage": {"candidatesScanned": scanned, "candidateLimit": CANDIDATES_PER_PUBLISHER,
                     "limitScope": "publisher", "candidateTotals": totals, "truncated": truncated,
                     "rawCandidatesScanned": sum(stats["rawScanned"] for stats in candidate_stats.values()) if candidate_stats else scanned,
                     "rawCandidateLimit": RAW_CANDIDATES_PER_PUBLISHER,
                     "filteredByReason": filtered},
        "sourceMode": "database:free-public",
        "window": {"days": days, "from": cutoff, "to": now.isoformat().replace("+00:00", "Z")},
        "lastSuccessfulCheckAt": max(successful) if successful else None,
        "sources": statuses,
        "status": "unavailable"
        if unavailable
        else "ready"
        if coverage and coverage["status"] == "unsupported"
        else "partial"
        if truncated or filtered.get("invalid") or any(s["status"] not in {"ok", "unchanged", "healthy_empty"} or s["stale"] for s in statuses)
        else "ready",
        "empty_reason": (
            "sources_unavailable"
            if unavailable
            else "market_not_covered"
            if coverage and coverage["status"] == "unsupported"
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
