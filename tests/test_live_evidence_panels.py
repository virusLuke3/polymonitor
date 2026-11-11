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
        assert kwargs['headers']['User-Agent'] == 'PolymonitorBot/1.0 (https://polymonitor.club)'
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


def test_daily_cache_reuses_completed_day_without_renewing_acquisition(tmp_path):
    from runtime.breaking_event_radar_watcher import BreakingEventRadarWatcher
    from runtime.snapshot_store import SnapshotStore
    from unittest.mock import Mock
    watcher = object.__new__(BreakingEventRadarWatcher)
    watcher.snapshot_store = SnapshotStore(str(tmp_path / 'cache.sqlite'))
    watcher.requests = Mock()
    watcher.requests.get.return_value.json.return_value = {'items': [{'views': 12, 'timestamp': '2026110900'}]}
    url = 'https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia.org/all-access/user/Iran/daily/20261102/20261109'
    first = watcher.http_json_get(url)
    second = watcher.http_json_get(url)
    assert second['acquiredAt'] == first['acquiredAt']
    assert watcher.requests.get.call_count == 1


def test_current_pageviews_replace_expired_headline_without_impersonating_news():
    dependencies = breaking_event_radar_service.BreakingEventRadarDependencies.from_context({
        'utc_now_iso': lambda: '2026-11-10T08:00:00Z', 'SETTINGS': object()})
    item = breaking_event_radar_service._build_event_item(dependencies,
        {'id': 'iran-geopolitics', 'entity': 'Iran'}, [],
        [{'sourceDay': '2026110900', 'fetchedAt': '2026-11-10T07:00:00Z', 'deltaPct': 10,
          'sourceUrl': 'https://wikimedia.org/fixture'}])
    old = {'generatedAt': '2026-11-08T03:00:00Z', 'items': [{'topicId': 'iran-geopolitics',
        'title': 'old headline', 'evidence': {'articles': [{'title': 'old headline'}]}}]}
    merged = breaking_event_radar_service.merge_breaking_event_radar_payloads(old,
        {'generatedAt': item['acquiredAt'], 'items': [item], 'errors': ['gdelt:rate-limited']})
    assert merged['items'][0]['source'] == 'Wikimedia Pageviews'
    assert merged['items'][0]['evidenceType'] == 'PAGEVIEWS'
    assert merged['items'][0]['eventTime'].startswith('2026-11-09T00:00:00')
    assert merged['generatedAt'] == '2026-11-10T07:00:00Z'
    assert 'old headline' not in str(merged)


def test_public_reports_take_priority_while_previous_gdelt_failure_remains_explicit(monkeypatch):
    monkeypatch.setenv('POLYDATA_BREAKING_EVENT_WIKIMEDIA_ENABLED', '0')
    def fail(*args, **kwargs):
        raise TimeoutError()
    articles = [{'title': 'Iran talks', 'url': 'https://example.test/news', 'domain': 'Approved publisher',
                 'datetime': '2026-11-10T07:50:00Z', 'acquiredAt': '2026-11-10T07:55:00Z', 'publicFeed': True},
                {'title': 'Iran report', 'datetime': '2026-11-10T06:00:00Z', 'domain': 'Approved publisher'}]
    result = breaking_event_radar_service.build_breaking_event_radar_payload({
        'SETTINGS': object(), 'http_json_get': fail, 'public_articles': lambda *a, **k: articles,
        'gdelt_state': lambda: {'status': 'timeout', 'nextAttemptAt': '2099-01-01T00:00:00Z'},
        'search_markets': lambda *a, **k: {'items': [{'id': 42, 'title': 'Iran talks?'}]},
        'utc_now_iso': lambda: '2026-11-10T08:00:00Z'}, topic_ids=['iran-geopolitics'])
    row = result['items'][0]
    assert (row['mentionCount15m'], row['mentionCount1h'], row['mentionCount24h']) == (1, 1, 2)
    assert result['status'] == 'degraded' and result['sources']['gdelt']['status'] == 'timeout'
    assert result['sources']['publicFeeds']['count'] == 2
    assert row['markets'][0]['marketId'] == 42
    assert result['generatedAt'] == '2026-11-10T07:55:00Z'


def test_news_rss_recovers_topic_without_hiding_gdelt_failure(monkeypatch):
    from unittest.mock import Mock
    import requests
    monkeypatch.setenv('POLYDATA_BREAKING_EVENT_WIKIMEDIA_ENABLED', '0')
    response = requests.Response()
    response.status_code = 429
    fetch = Mock(side_effect=requests.HTTPError(response=response))
    rss = Mock(return_value=[{'title': 'New Iran report', 'url': 'https://example.test/report',
        'domain': 'Publisher', 'datetime': '2026-11-10T07:50:00Z',
        'acquiredAt': '2026-11-10T07:55:00Z', 'newsRss': True}])
    result = breaking_event_radar_service.build_breaking_event_radar_payload({
        'SETTINGS': object(), 'http_json_get': fetch, 'public_articles': lambda *a, **k: [],
        'gdelt_state': lambda: {'status': 'rate-limited', 'nextAttemptAt': '2099-01-01T00:00:00Z'},
        'news_articles': rss, 'utc_now_iso': lambda: '2026-11-10T08:00:00Z'},
        topic_ids=['iran-geopolitics'])
    assert result['sources']['gdelt']['status'] == 'rate-limited'
    assert result['sources']['newsRss'] == {'status': 'ok', 'count': 1}
    assert result['status'] == 'degraded'
    assert result['items'][0]['tags'][-1] == 'news-rss'
    assert result['items'][0]['eventTime'] == '2026-11-10T07:50:00Z'
    assert result['generatedAt'] == '2026-11-10T07:55:00Z'
    fetch.assert_not_called()
    rss.assert_called_once()


def test_radar_public_snapshot_skips_all_news_network_reads(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setenv('POLYDATA_BREAKING_EVENT_WIKIMEDIA_ENABLED', '0')
    fetch, rss = Mock(side_effect=AssertionError('Unexpected HTTP')), Mock(side_effect=AssertionError('Unexpected RSS'))
    reports = [{'title': 'Iran talks', 'url': 'https://example.test/report', 'domain': 'Publisher',
                'datetime': '2026-11-10T07:50:00Z', 'acquiredAt': '2026-11-10T07:55:00Z', 'publicFeed': True}]
    result = breaking_event_radar_service.build_breaking_event_radar_payload({
        'SETTINGS': object(), 'http_json_get': fetch, 'public_articles': lambda *a, **k: reports,
        'news_articles': rss, 'utc_now_iso': lambda: '2026-11-10T08:00:00Z'}, topic_ids=['iran-geopolitics'])
    assert result['status'] == 'ok'
    assert result['sources']['gdelt']['status'] == 'not-needed'
    fetch.assert_not_called()
    rss.assert_not_called()


def test_radar_falls_back_to_gdelt_only_when_primary_reports_are_empty(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setenv('POLYDATA_BREAKING_EVENT_WIKIMEDIA_ENABLED', '0')
    fetch = Mock(return_value={'articles': [{'title': 'Iran report', 'url': 'https://example.test/report',
                                           'domain': 'Publisher', 'seendate': '20261110075000'}]})
    result = breaking_event_radar_service.build_breaking_event_radar_payload({
        'SETTINGS': object(), 'http_json_get': fetch, 'public_articles': lambda *a, **k: [],
        'news_articles': lambda *a, **k: [], 'utc_now_iso': lambda: '2026-11-10T08:00:00Z'},
        topic_ids=['iran-geopolitics'])
    assert result['sources']['gdelt']['count'] == 1
    fetch.assert_called_once()


def test_radar_empty_primary_respects_gdelt_cooldown_without_http(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setenv('POLYDATA_BREAKING_EVENT_WIKIMEDIA_ENABLED', '0')
    fetch = Mock(side_effect=AssertionError('Unexpected HTTP'))
    result = breaking_event_radar_service.build_breaking_event_radar_payload({
        'SETTINGS': object(), 'http_json_get': fetch, 'public_articles': lambda *a, **k: [],
        'news_articles': lambda *a, **k: [],
        'gdelt_state': lambda: {'status': 'rate-limited', 'lastAttemptAt': '2026-11-10T07:00:00Z',
                               'nextAttemptAt': '2099-01-01T00:00:00Z'},
        'utc_now_iso': lambda: '2026-11-10T08:00:00Z'}, topic_ids=['iran-geopolitics'])
    assert result['status'] == 'degraded' and not result['items']
    assert result['sources']['gdelt']['lastAttemptAt'] == '2026-11-10T07:00:00Z'
    assert 'errorCount' not in result['sources']['gdelt']
    fetch.assert_not_called()


def test_radar_rss_keeps_dated_public_metadata_and_bounded_transport():
    from email.utils import format_datetime
    from unittest.mock import Mock
    from runtime.breaking_event_radar_watcher import BreakingEventRadarWatcher
    now = datetime.now(timezone.utc)
    def item(title, url, at):
        return f'<item><title>{title}</title><link>{url}</link><source>Publisher</source><pubDate>{format_datetime(at)}</pubDate><description>Not an article body</description></item>'
    text = '<rss><channel>' + ''.join([
        item('Current', 'https://example.test/current', now - timedelta(minutes=5)),
        item('Duplicate', 'https://example.test/current', now - timedelta(minutes=5)),
        item('Old', 'https://example.test/old', now - timedelta(days=2)),
        item('Future', 'https://example.test/future', now + timedelta(hours=1)),
        item('Unsafe', 'javascript:alert(1)', now - timedelta(minutes=1)),
    ]) + '</channel></rss>'
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [text.encode()]
    watcher = object.__new__(BreakingEventRadarWatcher)
    watcher.settings = SimpleNamespace(google_news_rss_url='https://feed.test/search')
    watcher.requests = Mock()
    watcher.requests.get.return_value = response
    rows = watcher.news_articles({'newsQuery': 'Iran'}, max_records=20)
    assert len(rows) == 1 and rows[0]['title'] == 'Current'
    assert rows[0]['datetime'] != rows[0]['acquiredAt']
    assert 'description' not in rows[0]
    kwargs = watcher.requests.get.call_args.kwargs
    assert kwargs['params']['q'] == 'Iran when:1d' and kwargs['stream']
    assert kwargs['timeout'] == 12 and kwargs['source_deadline'] > 0
    response.__exit__.assert_called_once()
    response.iter_content.return_value = [b'<html>Unavailable</html>']
    with pytest.raises(ValueError, match='RSS'):
        watcher.news_articles({'newsQuery': 'Iran'}, max_records=20)


def test_breaking_public_reports_require_fresh_owner_and_current_public_permission(tmp_path):
    import json
    from runtime.breaking_event_radar_watcher import BreakingEventRadarWatcher
    from runtime.snapshot_store import SnapshotStore
    from api.services.free_content import snapshots
    watcher = BreakingEventRadarWatcher.__new__(BreakingEventRadarWatcher)
    watcher.snapshot_store = SnapshotStore(str(tmp_path / 'radar.sqlite'))
    now = datetime.now(timezone.utc)
    stamp = now.isoformat().replace('+00:00', 'Z')
    base = {'title': 'United States monetary policy', 'url': 'https://www.federalreserve.gov/newsevents/pressreleases/monetary20261110a.htm',
            'summary': 'Public release', 'source_id': 'fed-monetary', 'publisher_id': 'fed',
            'source_kind': 'official_release', 'display_allowed': True, 'published_at': stamp}
    state = {'status': 'ok', 'last_success_at': stamp, 'next_check_at': (now + timedelta(minutes=10)).isoformat()}
    rows = [{'record_kind': 'source', 'id': 'fed-monetary', 'payload': json.dumps(state)}]
    for index, patch in enumerate([{}, {'display_allowed': False}, {'url': 'https://unapproved.test/report'},
                                   {'published_at': (now - timedelta(days=2)).isoformat()},
                                   {'published_at': (now + timedelta(days=1)).isoformat()}]):
        rows.append({'record_kind': 'item', 'id': str(index), 'payload': json.dumps({**base, **patch})})
    snapshot = {'schemaVersion': 1, 'generatedAt': stamp, 'records': rows}
    watcher.snapshot_store.set(snapshots.NAMESPACE, snapshots.CACHE_KEY, snapshot, 90)
    actual = watcher.public_articles({'publicTerms': ['united states']}, max_records=20)
    assert len(actual) == 1 and actual[0]['contentId'] == '0'
    assert actual[0]['acquiredAt'] == stamp and actual[0]['datetime'] == stamp
    assert watcher.public_articles({}, max_records=20) == []
    snapshot['generatedAt'] = (now - timedelta(minutes=6)).isoformat()
    watcher.snapshot_store.set(snapshots.NAMESPACE, snapshots.CACHE_KEY, snapshot, 90)
    with pytest.raises(RuntimeError, match='owner unavailable'):
        watcher.public_articles({'publicTerms': ['united states']}, max_records=20)


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
