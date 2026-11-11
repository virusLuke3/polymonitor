#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from pathlib import Path
from typing import Any, Dict, Optional

_scripts_root = Path(__file__).resolve().parents[1]
if str(_scripts_root) not in sys.path:
    sys.path.insert(0, str(_scripts_root))

try:
    import redis
except ImportError:
    redis = None

try:
    import requests
except ImportError:
    requests = None

from runtime.redis_snapshot_store import seed_writer
from api.config import load_api_settings
from api.services import breaking_event_radar_service
from runtime.market_search import build_market_search
from runtime.seed_meta import SeedMetaStore, build_seed_meta_payload, utc_now_iso, publish_snapshot, retained_snapshot
from runtime.redis_snapshot_store import create_snapshot_store as SnapshotStore


DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_LIMIT = 12
SEED_META_NAMESPACE = "seed-meta:evidence"
SEED_META_CACHE_KEY = "breaking-event-radar"
SEED_META_SERVICE_NAME = "polydata-breaking-event-radar-seed.service"


class _Logger:
    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        print(f"[breaking-event-radar] ERROR {message % args if args else message}", file=sys.stderr)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        print(f"[breaking-event-radar] WARN {message % args if args else message}", file=sys.stderr)


class _App:
    logger = _Logger()


def _redis_key(prefix: str, namespace: str, cache_key: str) -> str:
    return f"{str(prefix or '')}{namespace}:{cache_key}"


class BreakingEventRadarWatcher:
    def __init__(self, *, redis_url: str, redis_prefix: str, snapshot_sqlite_path: str, settings: Any, limit: int, interval_seconds: int) -> None:
        if requests is None:
            raise RuntimeError("requests package is required. Install scripts/requirements.txt")
        self.settings = settings
        self.limit = max(1, int(limit or DEFAULT_LIMIT))
        self.interval_seconds = max(60, int(interval_seconds or DEFAULT_INTERVAL_SECONDS))
        self.redis_prefix = str(redis_prefix or "")
        self.redis_client = (redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
                             if redis is not None and str(redis_url or "").strip() else None)
        self.snapshot_store = SnapshotStore(snapshot_sqlite_path)
        self.seed_meta_store = SeedMetaStore(redis_client=self.redis_client, redis_prefix=self.redis_prefix, snapshot_store=self.snapshot_store)
        from api.clients.source_transport import source_session
        self.requests = source_session(requests)
        self.requests.trust_env = str(os.environ.get("POLYDATA_RUNTIME_TRUST_ENV", "0")).strip().lower() in {"1", "true", "yes", "on"}
        self.requests.headers.update({"User-Agent": "polydata-breaking-event-radar/1.0"})

    def ttl_seconds(self) -> int:
        configured = int(os.environ.get("POLYDATA_BREAKING_EVENT_RADAR_SEED_TTL_SECONDS", "0") or 0)
        if configured > 0:
            return configured
        return max(300, self.interval_seconds * 3)

    def redis_key(self) -> str:
        return _redis_key(
            self.redis_prefix,
            breaking_event_radar_service.BREAKING_EVENT_RADAR_SNAPSHOT_NAMESPACE,
            breaking_event_radar_service.BREAKING_EVENT_RADAR_CACHE_KEY,
        )

    def http_json_get(self, url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 12, headers: Optional[Dict[str, str]] = None) -> Any:
        from api.services.free_content.collector import retry_delay
        is_gdelt = urlsplit(url).hostname == "api.gdeltproject.org"
        is_pageviews = urlsplit(url).hostname == "wikimedia.org" and "/metrics/pageviews/per-article/" in url
        pageview_key = hashlib.sha256(url.encode()).hexdigest()
        if is_pageviews:
            saved = self.snapshot_store.get("source:breaking-pageviews", pageview_key)
            if isinstance(saved, dict) and saved.get("acquiredAt") and saved.get("items"):
                return saved
        state = self.snapshot_store.get_stale("state:content", "gdelt-backoff") or {} if is_gdelt else {}
        remaining = float(state.get("nextAttemptAt") or 0) - time.time()
        if is_gdelt and remaining > 0:
            response = requests.Response()
            response.status_code = 429
            response.headers["Retry-After"] = str(int(remaining) + 1)
            raise requests.HTTPError("GDELT retry backoff active", response=response)
        response = self.requests.get(url, params=params, timeout=timeout, headers=headers)
        if is_gdelt and response.status_code == 429:
            failures = int(state.get("failures") or 0) + 1
            delay = max(retry_delay(response.headers.get("Retry-After"), datetime.now(timezone.utc)), min(21600, 900 * 2 ** min(failures - 1, 5)))
            self.snapshot_store.set("state:content", "gdelt-backoff", {"nextAttemptAt": time.time() + delay, "failures": failures}, max(86400, delay))
        response.raise_for_status()
        if not response.content:
            return {}
        result = response.json()
        if is_gdelt:
            self.snapshot_store.set("state:content", "gdelt-backoff", {"nextAttemptAt": 0, "failures": 0}, 86400)
        if (is_pageviews and isinstance(result, dict) and isinstance(result.get("items"), list) and result["items"]
                and all(isinstance(row, dict) and isinstance(row.get("views"), int) and row["views"] >= 0
                        and re.fullmatch(r"\d{10}", str(row.get("timestamp", ""))) for row in result["items"])):
            result = {**result, "acquiredAt": utc_now_iso()}
            self.snapshot_store.set("source:breaking-pageviews", pageview_key, result, 21600, max_entries=32)
        return result

    def public_articles(self, seed: Dict[str, Any], *, max_records: int) -> list[dict]:
        """Reuse the existing content owner; no HTTP or database query fallback."""
        from api.services.free_content import public, snapshots
        now = datetime.now(timezone.utc)
        snapshot = self.snapshot_store.get_stale(snapshots.NAMESPACE, snapshots.CACHE_KEY)
        if snapshots._age(snapshot, now) > snapshots.MAX_STALE_SECONDS:
            raise RuntimeError("Public content owner unavailable")
        sources = public.source_map()
        terms = [str(term).strip() for term in (seed.get("publicTerms") or [seed.get("entity", "")]) if str(term or "").strip()]
        if not terms:
            return []
        pattern = re.compile(r"\b(?:" + "|".join(re.escape(term) for term in terms) + r")\b", re.I)
        cutoff = datetime.fromtimestamp(now.timestamp() - 86400, timezone.utc).isoformat().replace("+00:00", "Z")
        states = {r["id"]: public.decode_state(r["payload"], r["id"])
                  for r in snapshot["records"] if r["record_kind"] == "source"}
        articles = []
        for record in snapshot["records"]:
            if record["record_kind"] != "item":
                continue
            item, _ = public.eligible_item(record["payload"], sources, cutoff, now)
            if not item or not item.get("published_at") or not pattern.search(item["title"] + " " + item.get("summary", "")):
                continue
            state = states.get(item.get("source_id"), {})
            if state.get("status") not in {"ok", "unchanged", "healthy_empty"} or public.source_is_stale(state, now):
                continue
            articles.append({"title": item["title"], "url": item["url"],
                             "domain": sources[item["source_id"]]["publisher_name"],
                             "datetime": item["published_at"], "description": item.get("summary", "")[:260],
                             "acquiredAt": state.get("last_success_at"), "publicFeed": True,
                             "contentId": record["id"]})
        articles.sort(key=lambda item: item["datetime"], reverse=True)
        return articles[:max_records]

    def news_articles(self, seed: Dict[str, Any], *, max_records: int) -> list[dict]:
        """Bounded RSS metadata acquisition by this owner, never by the API."""
        from api.clients.source_transport import read_response_bytes
        from api.services.finance_watch.news import _parse_rss_items
        endpoint = str(getattr(self.settings, "google_news_rss_url", "") or "").strip()
        if not endpoint:
            raise ValueError("POLYDATA_GOOGLE_NEWS_RSS_URL is not configured")
        query = str(seed.get("newsQuery") or seed.get("entity") or "").strip()
        if not query:
            raise ValueError("News topic is missing")
        deadline = time.monotonic() + 20
        with self.requests.get(endpoint, params={"q": query + " when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
                               timeout=12, source_deadline=deadline, stream=True,
                               headers={"Accept": "application/rss+xml,application/xml"}) as response:
            response.raise_for_status()
            text = read_response_bytes(response, 1024 * 1024, deadline=deadline).decode("utf-8")
        now = datetime.now(timezone.utc)
        acquired_at = now.isoformat().replace("+00:00", "Z")
        rows = _parse_rss_items(text, panel_id="breaking-event-radar", limit=100)
        articles, seen = [], set()
        for row in rows:
            url = str(row.get("url") or "")
            parsed = urlsplit(url)
            published = datetime.fromisoformat(row["publishedAt"].replace("Z", "+00:00"))
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or url in seen
                    or not 0 <= (now - published).total_seconds() <= 86400):
                continue
            seen.add(url)
            articles.append({"title": row["title"], "url": url, "domain": row["source"],
                             "datetime": row["publishedAt"], "acquiredAt": acquired_at, "newsRss": True})
        return articles[:max(1, min(max_records, 50))]

    def service_context(self) -> Dict[str, Any]:
        context: Dict[str, Any] = {
            "SETTINGS": self.settings,
            "SNAPSHOT_STORE": self.snapshot_store,
            "app": _App(),
            "http_json_get": self.http_json_get,
            "public_articles": self.public_articles,
            "news_articles": self.news_articles,
            "utc_now_iso": utc_now_iso,
        }
        if str(os.environ.get("POLYDATA_BREAKING_EVENT_PM_SEARCH_ENABLED", "1")).strip().lower() in {"1", "true", "yes", "on"}:
            try:
                context["search_markets"] = build_market_search(self.settings)
            except Exception as exc:
                print(f"[breaking-event-radar] WARN market search disabled: {exc}", file=sys.stderr)
        return context

    def load_previous_payload(self) -> Dict[str, Any]:
        stale = self.snapshot_store.get_stale(
            breaking_event_radar_service.BREAKING_EVENT_RADAR_SNAPSHOT_NAMESPACE,
            breaking_event_radar_service.BREAKING_EVENT_RADAR_CACHE_KEY,
        )
        if isinstance(stale, dict):
            return stale
        if self.redis_client is None:
            return {}
        if getattr(self.snapshot_store, "backend", "sqlite") == "redis":
            return {}
        try:
            raw = self.redis_client.get(self.redis_key())
            if raw:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            print("[breaking-event-radar] WARN redis read failed", file=sys.stderr)
        return {}

    def store_payload(self, payload: Dict[str, Any]) -> None:
        ttl_seconds = self.ttl_seconds()
        publish_snapshot(
            snapshot_store=self.snapshot_store, namespace=breaking_event_radar_service.BREAKING_EVENT_RADAR_SNAPSHOT_NAMESPACE,
            cache_key=breaking_event_radar_service.BREAKING_EVENT_RADAR_CACHE_KEY, payload=payload, ttl_seconds=ttl_seconds,
            redis_client=self.redis_client, redis_cache_key=self.redis_key(),
        )

    def store_seed_meta(self, *, status: str, record_count: int, source_states: Dict[str, Any], error_summary: str | None, preserve_last_success: bool = False, source_success_at: str | None = None) -> None:
        previous = self.seed_meta_store.load(SEED_META_NAMESPACE, SEED_META_CACHE_KEY) or {}
        attempted_at = utc_now_iso()
        last_success_at = previous.get("lastSuccessAt")
        if not preserve_last_success and (status == "ok" or (status == "degraded" and record_count > 0)):
            last_success_at = source_success_at or attempted_at
        payload = build_seed_meta_payload(
            panel_id=SEED_META_CACHE_KEY,
            namespace=SEED_META_NAMESPACE,
            cache_key=SEED_META_CACHE_KEY,
            service_name=SEED_META_SERVICE_NAME,
            expected_interval_seconds=self.interval_seconds,
            status=status,
            last_attempt_at=attempted_at,
            last_success_at=last_success_at,
            record_count=record_count,
            source_states=source_states,
            error_summary=error_summary,
            cache_mode="seeded",
            payload_status=status,
            metadata={"workerVersion": "v1", "limit": self.limit},
        )
        payload["lastSuccessAt"] = last_success_at
        self.seed_meta_store.store(SEED_META_NAMESPACE, SEED_META_CACHE_KEY, payload)

    def store_seed_meta_fail_soft(self, **kwargs: Any) -> bool:
        try:
            self.store_seed_meta(**kwargs)
            return True
        except Exception as exc:
            print(
                f"[breaking-event-radar] WARN seed meta write failed: {exc.__class__.__name__}",
                file=sys.stderr,
            )
            return False

    @seed_writer
    def run_once(self) -> Dict[str, Any]:
        previous = self.load_previous_payload()
        topic_ids = breaking_event_radar_service.breaking_event_topic_ids()
        previous_rotation = (
            previous.get("rotation")
            if isinstance(previous.get("rotation"), dict)
            else {}
        )
        try:
            previous_index = int(previous_rotation.get("index", -1))
        except (TypeError, ValueError):
            previous_index = -1
        rotation_index = (previous_index + 1) % max(1, len(topic_ids))
        topic_id = topic_ids[rotation_index] if topic_ids else ""
        try:
            payload = breaking_event_radar_service.build_breaking_event_radar_payload(
                self.service_context(),
                limit=self.limit,
                topic_ids=[topic_id] if topic_id else None,
            )
            payload = breaking_event_radar_service.merge_breaking_event_radar_payloads(
                previous,
                {
                    **payload,
                    "rotation": {
                        "index": rotation_index,
                        "topicId": topic_id,
                        "totalTopics": len(topic_ids),
                    },
                },
                limit=self.limit,
            )
        except Exception as exc:
            if previous:
                preserved = retained_snapshot(previous)
                self.store_payload(preserved)
                self.store_seed_meta(status="preserved", record_count=len(previous.get("items") or []), source_states={"breakingEventRadar": "error"}, error_summary=str(exc), preserve_last_success=True)
                return {"status": "preserved", "payload": preserved}
            self.store_seed_meta(status="error", record_count=0, source_states={"breakingEventRadar": "error"}, error_summary=str(exc), preserve_last_success=True)
            raise

        record_count = len(payload.get("items") or [])
        if previous and record_count <= 0 and payload.get("errors"):
            preserved = retained_snapshot(previous)
            self.store_payload(preserved)
            self.store_seed_meta(
                status="preserved",
                record_count=len(previous.get("items") or []),
                source_states=payload.get("sources") if isinstance(payload.get("sources"), dict) else {"breakingEventRadar": "empty"},
                error_summary="Preserved previous breaking event radar snapshot because new payload was empty",
                preserve_last_success=True,
            )
            return {"status": "preserved", "payload": preserved}

        stale = payload.get("status") == "stale"
        payload = {**payload, "cacheMode": "stale-seed" if stale else "seeded", "freshness": "stale" if stale else "seeded"}
        self.store_payload(payload)
        status = str(payload.get("status") or ("ok" if record_count else "degraded"))
        self.store_seed_meta(
            status=status if status in {"ok", "degraded"} else "degraded",
            record_count=record_count,
            source_states=payload.get("sources") if isinstance(payload.get("sources"), dict) else {},
            error_summary="; ".join(payload.get("errors") or []) or None,
            preserve_last_success=bool(payload.get("errors")) and not any(
                int(value.get("count") or 0) > 0 for value in (payload.get("sources") or {}).values()
                if isinstance(value, dict)),
            source_success_at=payload.get("generatedAt"),
        )
        return {"status": status, "payload": payload}


def _result_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    return {
        "status": result.get("status"),
        "payloadStatus": payload.get("status"),
        "cacheMode": payload.get("cacheMode"),
        "items": len(payload.get("items") or []),
        "sources": sources,
        "errors": payload.get("errors") or [],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed Breaking Event Radar snapshots into Redis and SQLite")
    parser.add_argument("--watch", action="store_true", help="Run continuously instead of once")
    parser.add_argument("--interval", type=int, default=int(os.environ.get("POLYDATA_BREAKING_EVENT_RADAR_WATCH_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)))
    parser.add_argument("--limit", type=int, default=int(os.environ.get("POLYDATA_BREAKING_EVENT_RADAR_LIMIT", DEFAULT_LIMIT)))
    return parser


def main() -> int:
    from runtime.environment import load_environment
    load_environment()
    args = build_arg_parser().parse_args()
    settings = load_api_settings()
    watcher = BreakingEventRadarWatcher(
        redis_url=settings.redis_url,
        redis_prefix=settings.redis_prefix,
        snapshot_sqlite_path=settings.snapshot_sqlite_path,
        settings=settings,
        limit=args.limit,
        interval_seconds=args.interval,
    )
    print(f"[breaking-event-radar] redis_key={watcher.redis_key()} sqlite={settings.snapshot_sqlite_path}", file=sys.stderr)
    if not args.watch:
        print(json.dumps(_result_summary(watcher.run_once()), ensure_ascii=False), file=sys.stderr)
        return 0
    while True:
        try:
            print(json.dumps(_result_summary(watcher.run_once()), ensure_ascii=False), file=sys.stderr)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            watcher.store_seed_meta_fail_soft(status="error", record_count=0, source_states={"breakingEventRadar": "error"}, error_summary=str(exc), preserve_last_success=True)
            print(f"[breaking-event-radar] ERROR watch loop failed: {exc}", file=sys.stderr)
        time.sleep(watcher.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
