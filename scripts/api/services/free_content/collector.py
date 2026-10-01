from __future__ import annotations
import json, re, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import requests
from .http import fetch
from .normalize import parse_feed, plain, permission, utc
from .registry import sources, REGISTRY_PATH
from .store import ensure_schema, persist, save_state, source_states, prune


def snapshot_items(store, source):
    snapshot = store.get_stale("snapshot:world:natural-hazards", source["snapshot_key"])
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("events"), list):
        raise ValueError("shared-map-snapshot-unavailable")
    if not snapshot.get("fetchedAt"):
        raise ValueError("shared-map-snapshot-time-unknown")
    items = []
    for event in snapshot["events"]:
        ref = next((s for s in event.get("sources", []) if s.get("nativeId")), {})
        metrics = event.get("metrics") or {}
        item = {
            "external_id": ref.get("nativeId"),
            "event_id": event["id"],
            "title": event["title"],
            "url": ref.get("url"),
            "published_at": event.get("updatedAt") if source["source_kind"] == "alert" else event.get("occurredAt"),
            "updated_at": event.get("updatedAt"),
            "event_time": event.get("occurredAt"),
            "expires_at": event.get("expiresAt"),
            "source_kind": source["source_kind"],
            "topics": source["topics"],
            "excerpt_origin": "structured",
            "summary": "",
            "status": "Actual" if event.get("lifecycle") == "active" else "Ended",
            "message_type": "Cancel" if event.get("revision", {}).get("cancelled") else "Update",
            "severity": metrics.get("providerSeverity"),
            "area": event.get("locationLabel"),
            "place": event.get("locationLabel"),
            "magnitude": metrics.get("magnitude"),
            "geometry": event.get("geometry"),
            "language": "en",
        }
        if source["source_kind"] == "observation":
            item["summary"] = (
                f"Magnitude {metrics.get('magnitude')}; location: {event.get('locationLabel')}; depth: {metrics.get('depthKm')} km."
            )
        else:
            item["summary"] = (
                f"{event.get('title')}; area: {event.get('locationLabel')}; valid until {event.get('expiresAt') or 'unknown'}."
            )
        items.append(item)
    return items, snapshot


def retry_delay(value, now):
    try:
        return max(0, int(value))
    except (ValueError, TypeError):
        try:
            return max(0, int((parsedate_to_datetime(value) - now).total_seconds()))
        except (ValueError, TypeError):
            return 0


def collect_one(storage, snapshot_store, source, old, *, probe=False, conditional=True):
    now = datetime.now(timezone.utc)
    deadline = time.monotonic() + 45
    stamp = now.isoformat().replace("+00:00", "Z")
    state = {
        **old,
        "source_id": source["source_id"],
        "checked_at": stamp,
        "parsed_count": 0,
        "new": 0,
        "updated": 0,
        "duplicate": 0,
        "excluded": 0,
        "public": 0,
    }
    try:
        with requests.Session() as session:
            if source["transport"] == "snapshot" and not probe:
                items, snapshot = snapshot_items(snapshot_store, source)
                meta = {"http_status": None, "final_url": source["feed_url"], "reused_snapshot": True}
                state["last_success_at"] = snapshot["fetchedAt"]
                state["snapshot_stale"] = bool(snapshot.get("staleAfter") and snapshot["staleAfter"] < stamp)
            else:
                # A failed parse/ingest must retry the body, not accept a 304 for
                # content that was never successfully validated and persisted.
                request_state = {} if probe or not conditional or old.get("status") == "error" else old
                body, meta = fetch(session, source["feed_url"], source, request_state, deadline=deadline)
                state.update(meta)
                if meta["http_status"] == 429:
                    state.update(
                        status="rate_limited",
                        error="HTTP 429",
                        failure_count=int(old.get("failure_count", 0)) + 1,
                        next_check_at=(
                            now
                            + timedelta(
                                seconds=max(source["poll_interval_seconds"], retry_delay(meta.get("retry_after"), now))
                            )
                        )
                        .isoformat()
                        .replace("+00:00", "Z"),
                    )
                    return state
                if meta["http_status"] == 304 and source["publisher_id"] != "global-voices":
                    state.update(
                        status="unchanged",
                        last_success_at=stamp,
                        error=None,
                        failure_count=0,
                        next_check_at=(now + timedelta(seconds=source["poll_interval_seconds"]))
                        .isoformat()
                        .replace("+00:00", "Z"),
                    )
                    return state
                if meta["http_status"] == 304:
                    rows = storage.query_all(
                        "SELECT raw_payload FROM content_items WHERE provider='free-public' AND source=? ORDER BY published_at DESC LIMIT 30",
                        (source["publisher_name"],),
                    )
                    items = [json.loads(row["raw_payload"]) for row in rows]
                    items = [item for item in items if item.get("permission_reason") == "article-rights-unverified"]
                    if not items:
                        state.update(
                            status="unchanged",
                            last_success_at=stamp,
                            error=None,
                            failure_count=0,
                            next_check_at=(now + timedelta(seconds=source["poll_interval_seconds"]))
                            .isoformat()
                            .replace("+00:00", "Z"),
                        )
                        return state
                    for item in items:
                        for key in ("content_version", "version_first_fetched_at", "fetched_at", "first_seen_at"):
                            item.pop(key, None)
                        item["rights_text"] = ""
                elif source["transport"] == "snapshot":
                    from .normalize import parse_geojson

                    items = parse_geojson(body, source)
                else:
                    items = parse_feed(body, source)
                state["last_success_at"] = stamp
            if source["publisher_id"] == "global-voices":
                # Only approved article hosts, metadata/rights inspection, bounded and cached.
                checked = 0
                for item in items:
                    if not item.get("author") or any(
                        s in item["author"].lower()
                        for s in ("dialogue earth", "the conversation", "occrp", "african arguments")
                    ):
                        continue
                    from .normalize import identity

                    prior = storage.query_one(
                        "SELECT raw_payload FROM content_items WHERE id=?", (identity(source, item),)
                    )
                    prior_item = json.loads(prior["raw_payload"]) if prior else {}
                    if prior_item.get("article_rights_checked") and all(
                        prior_item.get(key) == item.get(key) for key in ("title", "summary", "published_at")
                    ):
                        item["article_rights_checked"] = True
                    elif checked < 5:
                        checked += 1
                        try:
                            article, _ = fetch(session, item["url"], source, deadline=deadline)
                            html = article.decode("utf-8", "replace")
                            # Verify canonical article + its own rights, not the page-wide default alone.
                            body_match = re.search(
                                r"""<div[^>]*class=['"]entry['"][^>]*>(.*?)<!--\s*\.entry-container\s*-->""",
                                html,
                                re.S | re.I,
                            )
                            if not body_match:
                                raise ValueError("article-rights-section-unrecognized")
                            item["rights_text"] += " " + body_match.group(1)[:200000]
                            credits = re.search(
                                r"""<div[^>]*class=['"][^'"]*post-credit-container[^'"]*['"][^>]*>(.*?)(?:<!--\s*\.post-credit-container|<div[^>]*class=['"][^'"]*postfooter-headlines)""",
                                html,
                                re.S | re.I,
                            )
                            item["article_rights_checked"] = bool(
                                credits and "creativecommons.org/licenses/by/3.0" in credits.group(1)
                            )
                        except Exception:
                            item["article_rights_checked"] = False
            state.update(meta)
            state.update(parsed_count=len(items), error=None, failure_count=0)
            if not probe:
                counts = persist(storage, source, items, stamp)
                state.update(counts, last_ingest_counts=counts, last_ingested_at=stamp)
            else:
                state["public"] = sum(permission(source, item)[0] for item in items)
            age = re.search(r"(?:^|,)\s*max-age=(\d+)", meta.get("cache_control") or "")
            interval = max(source["poll_interval_seconds"], int(age.group(1)) if age else 0)
            state.update(
                status="stale" if state.get("snapshot_stale") else "ok" if items else "healthy_empty",
                next_check_at=(now + timedelta(seconds=interval)).isoformat().replace("+00:00", "Z"),
            )
    except Exception as exc:
        failures = int(old.get("failure_count", 0)) + 1
        meta = getattr(exc, "meta", {})
        state.update(meta)
        state.update(
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            failure_count=failures,
            next_check_at=(
                now
                + timedelta(
                    seconds=max(
                        source["poll_interval_seconds"],
                        min(3600, 60 * 2 ** min(failures, 6)),
                        retry_delay(meta.get("retry_after"), now),
                    )
                )
            )
            .isoformat()
            .replace("+00:00", "Z"),
        )
    return state


def due_sources(states, *, probe=False, force=False, selected=None, stamp=None):
    stamp = stamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return [
        s
        for s in sources()
        if s["enabled"]
        and (not selected or s["source_id"] in selected)
        and not (
            states.get(s["source_id"], {}).get("status") == "rate_limited"
            and states[s["source_id"]].get("next_check_at", "") > stamp
        )
        and (
            probe
            or force
            # Retry an overdue shared snapshot next cycle. This only reads the
            # existing local map cache; it never acquires an external source.
            or (not probe and s["transport"] == "snapshot"
                and states.get(s["source_id"], {}).get("status") in {"stale", "error"})
            or not states.get(s["source_id"], {}).get("next_check_at")
            or states[s["source_id"]]["next_check_at"] <= stamp
        )
    ]


def cycle(storage, snapshot_store, *, probe=False, force=False, selected=None, on_result=None):
    ensure_schema(storage)
    states = source_states(storage)
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    pending = due_sources(states, probe=probe, force=force, selected=selected, stamp=stamp)

    def run(source):
        state = collect_one(
            storage, snapshot_store, source, states.get(source["source_id"], {}), probe=probe, conditional=not force
        )
        if not probe:
            try:
                save_state(storage, source["source_id"], state)
            except Exception as exc:
                state = {**state, "status": "error", "error": "state-write-failed:" + type(exc).__name__}
        if on_result:
            on_result(state)
        return state

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run, pending))
    if not probe:
        prune(storage, json.loads(REGISTRY_PATH.read_text()), stamp)
    return results
