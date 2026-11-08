from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from api.runtime_panels import get_panel_by_id
from api.services import breaking_event_radar_service, world_cup_match_ops_service


def test_breaking_event_radar_builds_from_gdelt_and_wikimedia() -> None:
    def http_json_get(url, params=None, timeout=12, headers=None):
        if "gdeltproject" in url:
            return {
                "articles": [
                    {
                        "title": "Iran talks intensify as sanctions risk returns",
                        "url": "https://example.com/iran-talks",
                        "domain": "example.com",
                        "sourcecountry": "US",
                        "seendate": "20260616093000",
                        "tone": "-2.4",
                    },
                    {
                        "title": "Tehran says nuclear deal remains possible",
                        "url": "https://example.org/tehran",
                        "domain": "example.org",
                        "sourcecountry": "GB",
                        "seendate": "20260616090000",
                    },
                ]
            }
        if "wikimedia" in url:
            return {"items": [{"views": 100}, {"views": 110}, {"views": 170}]}
        raise AssertionError(url)

    def search_markets(query, limit=4):
        return [{"id": "pm-1", "slug": "iran-sanctions", "question": "Will Iran sanctions return?"}]

    ctx = {
        "http_json_get": http_json_get,
        "search_markets": search_markets,
        "utc_now_iso": lambda: "2026-06-16T10:00:00Z",
        "SETTINGS": object(),
    }

    payload = breaking_event_radar_service.build_breaking_event_radar_payload(ctx, limit=3)

    assert payload["status"] == "ok"
    assert payload["items"]
    first = payload["items"][0]
    assert first["velocityScore"] > 0
    assert first["sourceDiversity"] == 2
    assert first["countrySpread"] == 2
    assert first["relatedPolymarketMarketIds"] == ["pm-1"]
    assert first["markets"][0]["matchReasons"] == ["entity", "topic"]


def test_breaking_event_radar_seed_miss_does_not_live_build_when_disabled() -> None:
    payload = breaking_event_radar_service.get_breaking_event_radar_snapshot(
        {"utc_now_iso": lambda: "2026-06-16T10:00:00Z", "SETTINGS": object()},
        limit=4,
        allow_live_build=False,
    )

    assert payload["status"] == "warming"
    assert payload["cacheMode"] == "seed-miss"
    assert payload["items"] == []


@pytest.mark.parametrize("payload", [{}, {"items": []}, {"items": [{"views": None}]}, {"items": [{"views": -1}]}])
def test_breaking_radar_missing_wikimedia_observation_is_failure_not_zero(payload):
    dependencies = breaking_event_radar_service.BreakingEventRadarDependencies.from_context(
        {"SETTINGS": object(), "http_json_get": lambda *a, **kw: payload})
    with pytest.raises(ValueError):
        breaking_event_radar_service._fetch_pageviews(dependencies, "Iran")


def test_breaking_radar_daily_pageviews_keep_provider_day_and_completed_day_bound():
    calls = []
    day = (datetime.now(timezone.utc).date() - timedelta(days=1)).strftime("%Y%m%d")
    def get(url, **kwargs):
        calls.append(url)
        return {"items": [{"views": 0, "timestamp": day + "00"}]}
    dependencies = breaking_event_radar_service.BreakingEventRadarDependencies.from_context(
        {"SETTINGS": object(), "http_json_get": get})
    result = breaking_event_radar_service._fetch_pageviews(dependencies, "Iran")
    assert calls[0].endswith("/" + day)
    assert result["latestViews"] == 0 and result["sourceDay"] == day + "00"
    assert result["fetchedAt"]


def test_breaking_radar_bad_gdelt_payload_is_failure_not_empty():
    dependencies = breaking_event_radar_service.BreakingEventRadarDependencies.from_context(
        {"SETTINGS": object(), "http_json_get": lambda *a, **kw: {"error": "bad query"}})
    with pytest.raises(ValueError):
        breaking_event_radar_service._fetch_gdelt_articles(dependencies, {"query": "fixture"}, max_records=5)


def test_breaking_radar_watcher_uses_approved_source_session(monkeypatch, tmp_path):
    from api.clients import source_transport
    from runtime import breaking_event_radar_watcher as module
    from unittest.mock import Mock
    session = Mock()
    factory = Mock(return_value=session)
    monkeypatch.setattr(source_transport, "source_session", factory)
    monkeypatch.setattr(module, "redis", SimpleNamespace(from_url=lambda *a, **kw: Mock()))
    watcher = module.BreakingEventRadarWatcher(redis_url="redis://fixture", redis_prefix="fixture:",
        snapshot_sqlite_path=str(tmp_path / "snapshot.sqlite"), settings=object(), limit=12, interval_seconds=300)
    assert watcher.requests is session
    factory.assert_called_once_with(module.requests)


def test_breaking_radar_all_sources_failed_does_not_renew_previous_success(monkeypatch):
    from runtime import breaking_event_radar_watcher as module
    from unittest.mock import Mock
    watcher = object.__new__(module.BreakingEventRadarWatcher)
    watcher.limit = 12
    previous = {"items": [{"topicId": "iran-geopolitics", "entity": "Iran", "velocityScore": 10}],
                "generatedAt": "2026-01-01T00:00:00Z", "rotation": {"index": -1}}
    watcher.load_previous_payload = lambda: previous
    watcher.service_context = lambda: {}
    watcher.store_payload = Mock()
    watcher.store_seed_meta = Mock()
    monkeypatch.setattr(breaking_event_radar_service, "build_breaking_event_radar_payload", lambda *a, **kw: {
        "items": [], "status": "degraded", "generatedAt": "2026-01-02T00:00:00Z",
        "sources": {"gdelt": {"status": "rate-limited", "count": 0},
                                                     "wikimedia": {"status": "error", "count": 0}},
        "errors": ["gdelt:rate-limited", "wikimedia:timeout"]})
    watcher.run_once()
    assert watcher.store_seed_meta.call_args.kwargs["preserve_last_success"] is True
    stored = watcher.store_payload.call_args.args[0]
    assert stored["generatedAt"] == previous["generatedAt"]
    assert stored["lastAttemptAt"] == "2026-01-02T00:00:00Z"
    assert stored["status"] == "stale" and stored["freshness"] == "stale"
    assert stored["rotation"]["index"] == 0


def test_breaking_radar_failed_first_attempt_has_no_success_clock():
    from runtime import breaking_event_radar_watcher as module
    from unittest.mock import Mock
    watcher = object.__new__(module.BreakingEventRadarWatcher)
    watcher.interval_seconds = 300
    watcher.limit = 12
    watcher.seed_meta_store = Mock()
    watcher.seed_meta_store.load.return_value = {}
    watcher.store_seed_meta(status="degraded", record_count=0, source_states={"gdelt": "error"},
                            error_summary="failed", preserve_last_success=True)
    assert watcher.seed_meta_store.store.call_args.args[2]["lastSuccessAt"] is None


def test_world_cup_match_ops_transforms_dashboard_payload() -> None:
    dashboard = {
        "generatedAt": "2026-06-16T10:00:00Z",
        "providerStates": {"schedule": "ok", "weather": "ok", "odds": "ok"},
        "matches": [
            {
                "id": "wc2026-002",
                "homeTeam": "USA",
                "awayTeam": "Paraguay",
                "kickoffUtc": "2026-06-13T20:00:00Z",
                "kickoffLocal": "Sat, 13 Jun, 15:00",
                "cityId": "los-angeles",
                "city": "Los Angeles / Inglewood",
                "venue": "SoFi Stadium",
                "status": "scheduled",
                "stage": "group",
                "group": "Group D",
            },
            {
                "id": "wc2026-001",
                "homeTeam": "Mexico",
                "awayTeam": "South Africa",
                "kickoffUtc": "2026-06-11T19:00:00Z",
                "kickoffLocal": "Thu, 11 Jun, 13:00",
                "cityId": "mexico-city",
                "city": "Mexico City",
                "venue": "Estadio Azteca",
                "status": "scheduled",
                "stage": "group",
                "group": "Group A",
                "marketLinked": True,
            },
        ],
        "weather": [
            {"cityId": "mexico-city", "temperature": 30, "precipitationProbability": 40, "windSpeed": 15, "source": "Open-Meteo"},
            {"cityId": "los-angeles", "temperature": 22, "precipitationProbability": 0, "windSpeed": 5, "source": "Open-Meteo"},
        ],
        "odds": [
            {
                "matchId": "wc2026-001",
                "marketId": "m1",
                "marketTitle": "Mexico vs South Africa winner",
                "marketUrl": "https://polymarket.com/event/mexico-south-africa",
            }
        ],
    }
    ctx = {"get_worldcup_dashboard_snapshot": lambda: dashboard, "utc_now_iso": lambda: "2026-06-10T10:00:00Z", "SETTINGS": object()}

    payload = world_cup_match_ops_service.build_world_cup_match_ops_payload(ctx, limit=2)

    assert payload["items"][0]["id"] == "wc2026-001"
    assert payload["items"][0]["marketLinked"] is True
    assert payload["items"][0]["relatedPolymarketMarketIds"] == ["m1"]
    assert payload["items"][0]["weatherRisk"]["level"] in {"watch", "high"}
    assert payload["summary"]["linkedMarkets"] == 1


def test_world_cup_match_ops_seed_miss_does_not_live_build_when_disabled() -> None:
    payload = world_cup_match_ops_service.get_world_cup_match_ops_snapshot(
        {"utc_now_iso": lambda: "2026-06-16T10:00:00Z", "SETTINGS": object()},
        limit=4,
        allow_live_build=False,
    )

    assert payload["status"] == "warming"
    assert payload["cacheMode"] == "seed-miss"
    assert payload["items"] == []


def test_live_evidence_runtime_panels_are_registered() -> None:
    breaking = get_panel_by_id("breaking-event-radar")
    match_ops = get_panel_by_id("world-cup-match-ops")

    assert breaking is not None
    assert breaking.route == "/runtime/evidence/breaking-event-radar"
    assert match_ops is not None
    assert match_ops.route == "/runtime/sports/world-cup-match-ops"
