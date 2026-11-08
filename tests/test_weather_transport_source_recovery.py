from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from api.clients import source_transport
from api.services import weather_news_service
from api.services import global_transport_shipping_service as transport_service
from runtime import global_transport_shipping_watcher as transport
from runtime import weather_news_watcher as weather


@pytest.mark.parametrize("module,host,method,legacy_timeout", [
    (weather, "news.google.com", "_http_text_get", 14),
    (transport, "raw.githubusercontent.com", "http_text_get", 18),
])
def test_source_reads_retry_body_on_existing_routes_with_full_budget(monkeypatch, module, host, method, legacy_timeout):
    monkeypatch.setattr(source_transport, "_routes", lambda: {
        host: ["socks5h://primary.invalid:1", "socks5h://backup.invalid:2"]})
    monkeypatch.delenv("POLYDATA_SNAPSHOT_SQLITE_PATH", raising=False)
    monkeypatch.setattr(module, "source_session", lambda **kw: source_transport.SourceSession())
    monkeypatch.setattr(source_transport.time, "sleep", lambda seconds: None)
    source_transport._COOLDOWNS.clear()
    source_transport._FAILURES.clear()
    calls, responses = [], []

    def request(session, verb, url, **kwargs):
        calls.append(kwargs)
        response = requests.Response()
        response.status_code = 200
        response.encoding = "utf-8"
        response.close = Mock()
        if len(calls) == 1:
            def stalled_body(**kwargs):
                raise requests.exceptions.ReadTimeout("body stalled")
            response.iter_content = stalled_body
        else:
            response.iter_content = lambda **kw: [b"<rss><channel/></rss>"]
        responses.append(response)
        return response

    monkeypatch.setattr(requests.Session, "request", request)
    cls = weather.WeatherNewsWatcher if module is weather else transport.GlobalTransportShippingWatcher
    watcher = cls.__new__(cls)
    if module is transport:
        watcher.requests = source_transport.SourceSession()
        watcher.requests.trust_env = False
    assert getattr(watcher, method)("https://" + host + "/fixture", timeout=legacy_timeout) == "<rss><channel/></rss>"
    assert len(calls) == 2
    assert [call["timeout"] for call in calls] == [45, 45]
    assert all(call["stream"] for call in calls)
    assert [call["proxies"]["https"] for call in calls] == ["socks5h://primary.invalid:1", "socks5h://backup.invalid:2"]
    assert all(response.close.called for response in responses)
    if module is transport:
        watcher.requests.close()


@pytest.mark.parametrize("module,cls,method", [
    (weather, weather.WeatherNewsWatcher, "_http_text_get"),
    (transport, transport.GlobalTransportShippingWatcher, "http_text_get"),
])
def test_owner_budget_does_not_start_a_shortened_request(monkeypatch, module, cls, method):
    monkeypatch.setattr(module.time, "monotonic", lambda: 100)
    request = Mock()
    monkeypatch.setattr(module, "read_with_retry", request)
    watcher = cls.__new__(cls)
    watcher._collection_deadline = 144
    with pytest.raises(requests.exceptions.Timeout, match="collection budget exhausted"):
        getattr(watcher, method)("https://source.invalid/feed")
    request.assert_not_called()


def make_watcher(monkeypatch, tmp_path, module):
    monkeypatch.setattr(module, "redis", None)
    monkeypatch.setattr(module, "source_session", lambda **kw: Mock())
    monkeypatch.setattr(module, "publish_cached_panel_snapshot", Mock(return_value=0))
    args = dict(redis_url="", redis_prefix="test:", snapshot_sqlite_path=str(tmp_path / "snapshot.sqlite"),
                settings=SimpleNamespace(weather_news_limit=40), interval_seconds=300)
    if module is weather:
        return weather.WeatherNewsWatcher(**args)
    return transport.GlobalTransportShippingWatcher(**args, limit=14)


@pytest.mark.parametrize("has_previous", [False, True])
def test_weather_all_source_failures_are_not_legal_empty(monkeypatch, tmp_path, has_previous):
    watcher = make_watcher(monkeypatch, tmp_path, weather)
    old = {"status": "ok", "generatedAt": "2026-11-06T14:00:00Z", "items": [{"id": "old"}]}
    if has_previous:
        watcher.store_payload(old)
        watcher.store_meta(status="ok", record_count=1)
    before = watcher.seed_meta_store.load(weather.SEED_META_NAMESPACE, weather.SEED_META_CACHE_KEY) or {}
    failed = {"status": "degraded", "generatedAt": "new-attempt", "items": [],
              "sources": {"city": "error"}, "sourceErrors": {"city": "ConnectionError"}}
    monkeypatch.setattr(weather_news_service, "build_weather_news_payload", lambda *a, **kw: failed)
    result = watcher.run_once()
    meta = watcher.seed_meta_store.load(weather.SEED_META_NAMESPACE, weather.SEED_META_CACHE_KEY)
    assert meta["status"] == ("preserved" if has_previous else "error")
    assert meta["lastSuccessAt"] == before.get("lastSuccessAt")
    assert meta["sourceStates"] == {"city": "error"}
    assert "failed for 1/1 queries" in meta["errorSummary"]
    weather.publish_cached_panel_snapshot.assert_not_called()
    if has_previous:
        assert result["payload"]["generatedAt"] == old["generatedAt"]
        assert result["payload"]["status"] == "stale"
        assert result["payload"]["sourceErrors"] == failed["sourceErrors"]
        assert watcher.previous()["items"] == old["items"]
    else:
        assert watcher.previous() == {}
    watcher.close()


def test_weather_legal_empty_replaces_old_news(monkeypatch, tmp_path):
    watcher = make_watcher(monkeypatch, tmp_path, weather)
    watcher.store_payload({"generatedAt": "old", "items": [{"id": "old"}]})
    empty = {"status": "empty", "generatedAt": "new", "items": [], "sources": {"city": "empty"}}
    monkeypatch.setattr(weather_news_service, "build_weather_news_payload", lambda *a, **kw: empty)
    assert watcher.run_once()["status"] == "stored"
    assert watcher.previous()["items"] == []
    meta = watcher.seed_meta_store.load(weather.SEED_META_NAMESPACE, weather.SEED_META_CACHE_KEY)
    assert meta["status"] == "empty" and meta["lastSuccessAt"]
    assert meta["errorSummary"] is None
    watcher.close()


@pytest.mark.parametrize("has_previous", [False, True])
def test_transport_failure_keeps_clock_and_marks_retained_sources_stale(monkeypatch, tmp_path, has_previous):
    watcher = make_watcher(monkeypatch, tmp_path, transport)
    old = {"status": "ok", "generatedAt": "old", "items": [{"id": "old"}],
           "freshness": "seeded", "sourceHealth": {"openflights": "fresh", "adsb": "skipped"}}
    if has_previous:
        watcher.store_payload(old)
        watcher.store_meta(status="ok", record_count=1)
    before = watcher.seed_meta_store.load(transport.SEED_META_NAMESPACE, transport.SEED_META_CACHE_KEY) or {}
    monkeypatch.setattr(transport.global_transport_shipping_service, "build_global_transport_shipping_payload",
                        Mock(side_effect=requests.exceptions.ReadTimeout("body stalled")))
    result = watcher.run_once()
    meta = watcher.seed_meta_store.load(transport.SEED_META_NAMESPACE, transport.SEED_META_CACHE_KEY)
    assert meta["lastSuccessAt"] == before.get("lastSuccessAt")
    assert meta["status"] == ("preserved" if has_previous else "error")
    assert meta["sourceStates"] == {"transport": "error"}
    transport.publish_cached_panel_snapshot.assert_not_called()
    if has_previous:
        payload = result["payload"]
        assert payload["generatedAt"] == "old"
        assert payload["status"] == payload["freshness"] == "stale"
        assert payload["sourceHealth"] == {"openflights": "stale", "adsb": "skipped"}
    else:
        assert watcher.previous() == {}
    watcher.close()


@pytest.mark.parametrize("xml,expected", [("<rss><channel/></rss>", "empty"), ("<html><body/></html>", "degraded")])
def test_weather_rss_schema_distinguishes_empty_from_non_feed(monkeypatch, xml, expected):
    monkeypatch.setattr(weather_news_service, "load_weather_cities", lambda: [{"city_id": "city", "city": "City"}])
    monkeypatch.setattr(weather_news_service, "WEATHER_TOPIC_QUERIES", [])
    payload = weather_news_service.build_weather_news_payload({
        "SETTINGS": SimpleNamespace(google_news_rss_url="https://news.invalid/rss", weather_news_fetch_workers=1),
        "http_text_get": lambda *a, **kw: xml,
    })
    assert payload["status"] == expected
    assert payload["items"] == []
    assert payload["sourceErrors"] == ({} if expected == "empty" else {"city": "ValueError"})


@pytest.mark.parametrize("age,extra,expected", [
    (9480, {}, "fresh"),
    (21600, {}, "fresh"),
    (21601, {}, "stale"),
    (9480, {"cacheTtlSeconds": 900}, "stale"),
    (9480, {"stale": True}, "stale"),
    (9480, {"status": "error"}, "degraded"),
    (None, {}, "unknown"),
    (-120, {}, "unknown"),
])
def test_ais_health_uses_original_sample_clock_and_cadence(monkeypatch, age, extra, expected):
    monkeypatch.setenv("POLYDATA_AISSTREAM_MIN_SAMPLE_INTERVAL_SECONDS", "21600")
    monkeypatch.setattr(transport_service, "_age_seconds", lambda timestamp: age)
    payload = {"status": "ok", "sampledAt": "original-source-clock", "cacheMode": "ais-cache",
               "cacheTtlSeconds": 21600, **extra}
    before = dict(payload)
    assert transport_service._transport_sample_health(payload, "aisstream") == expected
    assert payload == before


@pytest.mark.parametrize("source,interval", [("opensky", 900), ("adsb", 1800)])
@pytest.mark.parametrize("offset,extra,expected", [
    (-1, {}, "fresh"),
    (0, {}, "fresh"),
    (1, {}, "stale"),
    (-1, {"status": "empty"}, "fresh"),
    (-1, {"status": "partial"}, "degraded"),
    (-1, {"status": "auth-error"}, "degraded"),
    (-1, {"errors": [{"region": "one", "error": "Timeout"}]}, "degraded"),
    (-1, {"freshness": "stale"}, "stale"),
    (-1, {"status": "skipped"}, "skipped"),
])
def test_aircraft_health_uses_each_providers_own_interval(monkeypatch, source, interval, offset, extra, expected):
    monkeypatch.setenv(f"POLYDATA_{source.upper()}_MIN_SAMPLE_INTERVAL_SECONDS", str(interval))
    monkeypatch.setattr(transport_service, "_age_seconds", lambda timestamp: interval + offset)
    payload = {"status": "ok", "sampledAt": "original", "cacheMode": "cache", "cacheTtlSeconds": 21600, **extra}
    before = dict(payload)
    assert transport_service._transport_sample_health(payload, source) == expected
    assert payload == before


@pytest.mark.parametrize("source", ["opensky", "adsb"])
def test_aircraft_cache_ttl_can_be_shorter_than_configured_interval(monkeypatch, source):
    monkeypatch.setenv(f"POLYDATA_{source.upper()}_MIN_SAMPLE_INTERVAL_SECONDS", "1800")
    monkeypatch.setattr(transport_service, "_age_seconds", lambda timestamp: 901)
    payload = {"status": "ok", "sampledAt": "original", "cacheTtlSeconds": 900, "cacheMode": "cache"}
    assert transport_service._transport_sample_health(payload, source) == "stale"


def test_eight_minute_opensky_cache_is_valid_without_resampling(monkeypatch):
    monkeypatch.setenv("POLYDATA_OPENSKY_MIN_SAMPLE_INTERVAL_SECONDS", "900")
    monkeypatch.setattr(transport_service, "_age_seconds", lambda timestamp: 480)
    payload = {"status": "ok", "sampledAt": "original", "cacheTtlSeconds": 900, "errors": [], "cacheMode": "cache"}
    assert transport_service._transport_sample_health(payload, "opensky") == "fresh"
