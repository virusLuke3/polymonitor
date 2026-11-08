from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


from api.services import sports_odds_service
from runtime import sports_odds_watcher
from runtime.snapshot_store import SnapshotStore


class FakeLogger:
    def exception(self, *args, **kwargs) -> None:
        return None


class FakeApp:
    logger = FakeLogger()


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value


def make_settings(snapshot_path: str = "", *, api_key: str = "fixture-key") -> SimpleNamespace:
    return SimpleNamespace(
        redis_url="redis://test/0",
        redis_prefix="polydata:",
        snapshot_sqlite_path=snapshot_path,
        the_odds_api_base_url="https://example.test",
        the_odds_api_key=api_key,
        the_odds_source_url="https://the-odds-api.com/",
        sports_odds_ttl_seconds=180,
        sports_odds_sport_key="upcoming",
        sports_odds_regions="us",
        sports_odds_markets="h2h",
        sports_odds_pm_search_enabled=True,
    )


def odds_fixture() -> list[dict]:
    return [
        {
            "id": "event-1",
            "sport_key": "basketball_nba",
            "sport_title": "NBA",
            "commence_time": "2026-05-12T23:00:00Z",
            "home_team": "Boston Celtics",
            "away_team": "New York Knicks",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "last_update": "2026-05-12T18:00:00Z",
                    "markets": [{"key": "h2h", "outcomes": [{"name": "Boston Celtics", "price": 1.8}, {"name": "New York Knicks", "price": 2.1}]}],
                },
                {
                    "key": "fanduel",
                    "title": "FanDuel",
                    "last_update": "2026-05-12T18:01:00Z",
                    "markets": [{"key": "h2h", "outcomes": [{"name": "Boston Celtics", "price": 1.9}, {"name": "New York Knicks", "price": 2.0}]}],
                },
            ],
        }
    ]


class SportsOddsServiceTestCase(unittest.TestCase):
    def make_context(self, *, api_key: str = "fixture-key", payload: list[dict] | None = None) -> dict:
        settings = make_settings(api_key=api_key)

        def http_json_get(url, params=None, timeout=12, headers=None):
            self.assertEqual("fixture-key", params.get("apiKey"))
            self.assertIn("/v4/sports/upcoming/odds/", url)
            return odds_fixture() if payload is None else payload

        return {
            "SETTINGS": settings,
            "app": FakeApp(),
            "http_json_get": http_json_get,
            "search_markets": lambda query, limit=3: {"items": [{"id": 9, "title": query, "latestPrice": "0.60"}]},
            "utc_now_iso": lambda: "2026-05-12T18:02:00Z",
        }

    def test_snapshot_normalizes_bookmaker_consensus_and_pm_delta(self):
        payload = sports_odds_service.get_sports_odds_snapshot(self.make_context(), limit=4)

        self.assertEqual("ok", payload["status"])
        self.assertEqual(1, len(payload["items"]))
        item = payload["items"][0]
        self.assertEqual("New York Knicks @ Boston Celtics", item["event"])
        self.assertEqual(2, item["bookmakerCount"])
        self.assertEqual("matched", item["pm"]["status"])
        self.assertGreater(item["consensusProbability"], 0)
        self.assertGreaterEqual(len(item["quotes"]), 2)

    def test_missing_key_returns_renderable_degraded_payload(self):
        ctx = self.make_context(api_key="")
        payload = sports_odds_service.get_sports_odds_snapshot(ctx, limit=4)

        self.assertEqual("degraded", payload["status"])
        self.assertEqual("missing-key", payload["sources"]["theOddsApi"])
        self.assertEqual([], payload["items"])

    def test_api_reads_seeded_sqlite_snapshot_without_live_fetch(self):
        with tempfile.TemporaryDirectory() as snapshot_dir:
            settings = make_settings(str(Path(snapshot_dir) / "snapshots.sqlite3"))
            store = SnapshotStore(settings.snapshot_sqlite_path)
            cache_key = sports_odds_service.build_sports_odds_cache_key(settings, limit=8)
            seeded = {"generatedAt": "2026-05-12T18:00:00Z", "status": "ok", "items": [{"id": "seeded", "event": "Seed @ Home"}]}
            store.set(sports_odds_service.SPORTS_ODDS_NAMESPACE, cache_key, seeded, 300)
            ctx = {
                "SETTINGS": settings,
                "SNAPSHOT_STORE": store,
                "get_cached_json": lambda namespace, key: None,
                "utc_now_iso": lambda: "2026-05-12T18:02:00Z",
            }
            with patch.object(sports_odds_service, "fetch_live_sports_odds_payload", side_effect=AssertionError("live fetch should not run")):
                payload = sports_odds_service.get_sports_odds_snapshot(ctx, limit=8)

        self.assertEqual("sqlite-seed", payload["cacheMode"])
        self.assertEqual("seeded", payload["items"][0]["id"])


    def test_newer_watcher_snapshot_beats_old_request_size_cache(self):
        old = {"generatedAt": "2026-07-21T09:00:00Z", "items": [{"id": "old"}]}
        current = {"generatedAt": "2026-09-23T01:00:00Z", "items": [{"id": str(i)} for i in range(12)]}
        ctx = self.make_context()
        ctx["get_cached_json"] = lambda namespace, key: current if json.loads(key)["limit"] == 32 else old
        with patch.dict("os.environ", {"POLYDATA_SPORTS_ODDS_LIMIT": "32"}), patch.object(
            sports_odds_service, "fetch_live_sports_odds_payload", side_effect=AssertionError("no live fetch")
        ):
            payload = sports_odds_service.get_sports_odds_snapshot(ctx, limit=8)
        self.assertEqual(current["generatedAt"], payload["generatedAt"])
        self.assertEqual(8, len(payload["items"]))
        self.assertEqual("0", payload["items"][0]["id"])

    def test_older_watcher_snapshot_does_not_replace_newer_request_cache(self):
        current = {"generatedAt": "2026-09-23T01:00:00Z", "items": [{"id": "new"}]}
        old = {"generatedAt": "2026-07-21T09:00:00Z", "items": [{"id": "old"}]}
        ctx = self.make_context()
        ctx["get_cached_json"] = lambda namespace, key: old if json.loads(key)["limit"] == 32 else current
        with patch.dict("os.environ", {"POLYDATA_SPORTS_ODDS_LIMIT": "32"}):
            payload = sports_odds_service.get_sports_odds_snapshot(ctx, limit=8)
        self.assertEqual("new", payload["items"][0]["id"])


class SportsOddsWatcherTestCase(unittest.TestCase):
    def make_watcher(self) -> tuple[sports_odds_watcher.SportsOddsWatcher, FakeRedis, tempfile.TemporaryDirectory]:
        snapshot_dir = tempfile.TemporaryDirectory()
        self.addCleanup(snapshot_dir.cleanup)
        fake_redis = FakeRedis()
        settings = make_settings(str(Path(snapshot_dir.name) / "snapshots.sqlite3"))
        redis_module = SimpleNamespace(from_url=lambda *args, **kwargs: fake_redis)
        with patch.object(sports_odds_watcher, "redis", redis_module):
            watcher = sports_odds_watcher.SportsOddsWatcher(
                redis_url=settings.redis_url,
                redis_prefix=settings.redis_prefix,
                snapshot_sqlite_path=settings.snapshot_sqlite_path,
                settings=settings,
                limit=8,
                interval_seconds=180,
            )
        return watcher, fake_redis, snapshot_dir

    def test_read_retries_timeout_with_full_budget_and_keeps_quota_denial(self):
        import requests
        from api.clients import source_transport
        watcher, _, _ = self.make_watcher()
        calls = []
        response = requests.Response()
        response.status_code = 200
        response._content = b"[]"
        response._content_consumed = True
        response.headers["x-requests-remaining"] = "490"
        def request(method, url, **kwargs):
            calls.append(kwargs["timeout"])
            if len(calls) == 1:
                raise requests.ReadTimeout()
            return response
        watcher.requests = SimpleNamespace(request=request)
        with patch.object(source_transport.time, "sleep", lambda _: None):
            self.assertEqual([], watcher.http_json_get("fixture", timeout=45))
        self.assertEqual([45, 45], calls)
        self.assertEqual(490, watcher.last_http_quota["remaining"])
        calls.clear()
        response.status_code = 429
        response.headers["x-requests-remaining"] = "0"
        watcher.requests = SimpleNamespace(request=lambda *a, **kw: (calls.append(1), response)[1])
        with self.assertRaises(requests.HTTPError):
            watcher.http_json_get("fixture", timeout=45)
        self.assertEqual([1], calls)
        self.assertEqual(0, watcher.last_http_quota["remaining"])
        self.assertEqual(86400, watcher.next_interval_seconds())

    def test_watcher_stores_payload_snapshot_and_seed_meta(self):
        watcher, fake_redis, _ = self.make_watcher()
        payload = {"generatedAt": "2026-05-12T18:00:00Z", "status": "ok", "sources": {"theOddsApi": "ok"}, "items": [{"id": "event-1"}]}
        with patch.object(sports_odds_service, "fetch_live_sports_odds_payload", return_value=payload):
            result = watcher.run_once()

        self.assertEqual("ok", result["status"])
        stored = json.loads(fake_redis.get(watcher.redis_key()) or "{}")
        self.assertEqual("seeded", stored["cacheMode"])
        meta = json.loads(fake_redis.get("polydata:seed-meta:sports:sports-odds") or "{}")
        self.assertEqual("ok", meta["status"])
        self.assertEqual("polydata-sports-odds-seed.service", meta["serviceName"])

    def test_watcher_injects_market_search_when_pm_matching_enabled(self):
        watcher, _, _ = self.make_watcher()
        seen_queries: list[str] = []

        def fake_search(query: str, limit: int = 10) -> dict:
            seen_queries.append(query)
            return {"items": [{"id": 9, "title": query, "latestPrice": "0.58"}]}

        def fake_fetch(ctx: dict, limit: int = 8) -> dict:
            self.assertIn("search_markets", ctx)
            result = ctx["search_markets"]("Knicks @ Celtics", limit=3)
            return {
                "generatedAt": "2026-05-12T18:00:00Z",
                "status": "ok",
                "sources": {"theOddsApi": "ok"},
                "items": [{"id": "event-1", "pm": result["items"][0]}],
            }

        with (
            patch.object(sports_odds_watcher, "build_market_search", return_value=fake_search),
            patch.object(sports_odds_service, "fetch_live_sports_odds_payload", side_effect=fake_fetch),
        ):
            result = watcher.run_once()

        self.assertEqual("ok", result["status"])
        self.assertEqual(["Knicks @ Celtics"], seen_queries)

    def test_watcher_preserves_previous_snapshot_when_new_payload_is_empty(self):
        watcher, fake_redis, _ = self.make_watcher()
        previous = {"generatedAt": "2026-05-12T18:00:00Z", "status": "ok", "items": [{"id": "old-event"}], "cacheMode": "seeded"}
        watcher.store_payload(previous)

        with patch.object(sports_odds_service, "fetch_live_sports_odds_payload", return_value={"generatedAt": "2026-05-12T18:01:00Z", "status": "empty", "items": []}):
            result = watcher.run_once()

        self.assertEqual("preserved", result["status"])
        stored = json.loads(fake_redis.get(watcher.redis_key()) or "{}")
        self.assertEqual("old-event", stored["items"][0]["id"])

    def test_successful_empty_refresh_retires_finished_events(self):
        watcher, fake_redis, _ = self.make_watcher()
        watcher.store_payload({"generatedAt": "2026-10-29T01:45:34Z", "status": "ok", "items": [{"id": "finished"}]})
        payload = {"generatedAt": "2026-11-03T08:00:00Z", "status": "empty",
                   "sources": {"theOddsApi": "ok"}, "items": []}
        with patch.object(sports_odds_service, "fetch_live_sports_odds_payload", return_value=payload):
            result = watcher.run_once()
        self.assertEqual("empty", result["status"])
        stored = json.loads(fake_redis.get(watcher.redis_key()))
        self.assertEqual([], stored["items"])
        self.assertEqual(payload["generatedAt"], stored["generatedAt"])
        meta = json.loads(fake_redis.get("polydata:seed-meta:sports:sports-odds"))
        self.assertEqual("empty", meta["status"])
        self.assertIsNone(meta["errorSummary"])
        self.assertEqual(meta["lastAttemptAt"], meta["lastSuccessAt"])

    def test_missing_key_does_not_erase_last_observation_or_advance_success(self):
        watcher, fake_redis, _ = self.make_watcher()
        previous = {"generatedAt": "2026-11-03T07:00:00Z", "status": "ok", "items": [{"id": "prior"}]}
        with patch.object(sports_odds_service, "fetch_live_sports_odds_payload", return_value=previous):
            watcher.run_once()
        before = json.loads(fake_redis.get("polydata:seed-meta:sports:sports-odds"))
        failed = {"generatedAt": "2026-11-03T08:00:00Z", "status": "degraded",
                  "sources": {"theOddsApi": "missing-key"}, "items": []}
        with patch.object(sports_odds_service, "fetch_live_sports_odds_payload", return_value=failed):
            result = watcher.run_once()
        self.assertEqual("preserved", result["status"])
        stored = json.loads(fake_redis.get(watcher.redis_key()))
        self.assertEqual(previous["generatedAt"], stored["generatedAt"])
        after = json.loads(fake_redis.get("polydata:seed-meta:sports:sports-odds"))
        self.assertEqual(before["lastSuccessAt"], after["lastSuccessAt"])
