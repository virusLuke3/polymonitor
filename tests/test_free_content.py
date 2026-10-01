"""Isolated fixtures only: none of these records enter the real content database."""

from __future__ import annotations
import json, sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from api.context import RuntimeResources
from api.services.free_content import normalize, store, public, collector, matching
from api.services.free_content.registry import source_map


@pytest.fixture
def storage(tmp_path):
    path = tmp_path / "fixture.db"

    def connection(*_):
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    def all_rows(sql, params=()):
        with connection() as conn:
            return [dict(r) for r in conn.execute(sql, params)]

    s = SimpleNamespace(
        database_path=str(path),
        get_connection=connection,
        get_backend=lambda: "sqlite",
        table_exists=lambda name: bool(
            all_rows("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
        ),
        query_all=all_rows,
        query_one=lambda sql, params=(): next(iter(all_rows(sql, params)), None),
        resources=RuntimeResources(),
        application=SimpleNamespace(logger=SimpleNamespace(exception=lambda *_: None)),
    )
    with patch.dict("os.environ", {"POLYDATA_API_READONLY": "0"}):
        store.ensure_schema(s)
    yield s
    s.resources.close()


@pytest.fixture
def source():
    return source_map()["fed-monetary"]


def article(source, **changes):
    return {
        "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm",
        "external_id": "fixture-official-id",
        "title": "Federal Reserve issues FOMC statement",
        "summary": "Fixture excerpt, never published.",
        "published_at": "2026-09-16T18:00:00Z",
        "source_kind": source["source_kind"],
        "topics": source["topics"],
        **changes,
    }


@pytest.mark.parametrize("atom", [False, True])
def test_feed_author_summary_time_and_unknown(source, atom):
    body = (
        b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A &amp; B</title><link href="https://www.federalreserve.gov/a"/><author><name>Alice</name></author><summary>&lt;p&gt;Excerpt&lt;/p&gt;</summary><published>2026-09-01T00:00:00Z</published></entry></feed>'
        if atom
        else b'<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item><title>A &amp; B</title><link>https://www.federalreserve.gov/a</link><dc:creator>Alice</dc:creator><description>&lt;p&gt;Excerpt&lt;/p&gt;</description><pubDate>Tue, 01 Sep 2026 00:00:00 GMT</pubDate></item></channel></rss>'
    )
    item = normalize.parse_feed(body, source)[0]
    assert (item["title"], item["author"], item["summary"], item["published_at"]) == (
        "A & B",
        "Alice",
        "Excerpt",
        "2026-09-01T00:00:00Z",
    )
    assert normalize.utc("missing") is None
    assert normalize.utc("2026-09-01") is None


def test_rss_html_doctype_inside_cdata_is_not_an_xml_entity(source):
    body = b'<rss><channel><item><title>Valid feed</title><link>https://www.federalreserve.gov/a</link><description><![CDATA[<!DOCTYPE html PUBLIC "fixture"><p>Public excerpt</p>]]></description></item></channel></rss>'
    assert normalize.parse_feed(body, source)[0]['summary'] == 'Public excerpt'
    for prefix in (b'<!-- harmless comment -->', b''):
        with pytest.raises(ValueError, match='xml-entities-forbidden'):
            normalize.parse_feed(prefix + b'<!DOCTYPE rss [<!ENTITY a "dangerous">]><rss/>', source)


def test_failed_source_fetches_body_again_instead_of_accepting_an_old_etag(storage, source):
    old = {'status': 'error', 'etag': 'unvalidated-etag', 'last_success_at': '2026-09-30T00:00:00Z'}
    with patch.object(collector, 'fetch', return_value=(b'<rss><channel/></rss>', {'http_status': 200, 'final_url': source['feed_url']})) as fetch:
        state = collector.collect_one(storage, None, source, old)
    assert fetch.call_args.args[3] == {}
    assert state['status'] == 'healthy_empty' and state['error'] is None


def test_unsafe_xml_html_and_links(source):
    with pytest.raises(ValueError):
        normalize.parse_feed(b'<!DOCTYPE rss [<!ENTITY a SYSTEM "file:///etc/passwd">]><rss/>', source)
    assert (
        normalize.plain("<script>alert(1)</script><p>Real text</p><blockquote>Third-party quote</blockquote>")
        == "Real text"
    )
    for url in (
        "javascript:alert(1)",
        "http://127.0.0.1/x",
        "https://www.federalreserve.gov.evil.test/x",
        "https://user@www.federalreserve.gov/x",
    ):
        assert normalize.canonical_url(url, source) is None
    assert normalize.canonical_url("https://www.federalreserve.gov/a?basin=atlc&utm_source=test", source).endswith(
        "?basin=atlc"
    )


def test_idempotency_cross_feed_versions_and_first_seen(storage, source):
    item = article(source)
    other = source_map()["fed-all"]
    assert store.persist(storage, source, [item], "2026-10-01T00:00:00Z")["new"] == 1
    assert store.persist(storage, source, [item], "2026-10-01T00:01:00Z")["duplicate"] == 1
    store.persist(storage, other, [{**item, "topics": other["topics"]}], "2026-10-01T00:02:00Z")
    assert len(storage.query_all("SELECT * FROM content_items")) == 1
    assert len(storage.query_all("SELECT * FROM content_discoveries")) == 2
    assert store.persist(storage, source, [item], "2026-10-01T00:03:00Z")["duplicate"] == 1
    updated = {**item, "summary": "Revised fixture excerpt"}
    assert store.persist(storage, source, [updated], "2026-10-01T00:04:00Z")["updated"] == 1
    raw = json.loads(storage.query_one("SELECT raw_payload FROM content_items")["raw_payload"])
    assert raw["first_seen_at"] == "2026-10-01T00:00:00Z"
    assert raw["published_at"] == "2026-09-16T18:00:00Z"
    assert len(storage.query_all("SELECT * FROM content_versions")) == 3


def test_unknown_and_required_attribution_never_public(storage, source):
    gv = source_map()["global-voices"]
    item = article(
        gv,
        url="https://globalvoices.org/2026/10/01/fixture/",
        author=None,
        article_rights_checked=True,
        published_at="2026-10-01T00:00:00Z",
    )
    store.persist(storage, gv, [item], "2026-10-01T00:00:00Z")
    assert public.payload(storage, now=datetime(2026, 10, 1, 1, tzinfo=timezone.utc))["items"] == []
    assert public.filter_payload({"items": [{"source": "Legacy outlet", "title": "Unknown rights"}]})["items"] == []


def test_no_market_match_no_global_fallback_and_old_article_window(storage, source):
    store.persist(storage, source, [article(source)], "2026-10-01T00:00:00Z")
    now = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
    assert public.payload(storage, now=now)["items"] == []
    assert len(public.payload(storage, days=30, now=now)["items"]) == 1
    result = public.payload(
        storage, market={"title": "Will a football club win this season?"}, market_id=2, days=30, now=now
    )
    assert result["scope"] == "market" and result["marketId"] == 2 and result["items"] == []


def test_expired_and_test_alerts(storage):
    source = source_map()["nws"]
    item = article(
        source,
        url="https://api.weather.gov/alerts/fixture",
        source_kind="alert",
        status="Actual",
        expires_at="2026-09-30T00:00:00Z",
    )
    store.persist(storage, source, [item], "2026-10-01T00:00:00Z")
    assert public.payload(storage, days=30)["items"] == []
    assert normalize.permission(source, {**item, "status": "Test"})[0] is False


def test_304_keeps_records_and_rate_limit_backoff(storage, source):
    old = {"last_success_at": "2026-09-30T00:00:00Z", "etag": "fixture-etag"}
    with patch.object(collector, "fetch", return_value=(b"", {"http_status": 304, "final_url": source["feed_url"]})):
        state = collector.collect_one(storage, None, source, old)
    assert state["status"] == "unchanged" and state["last_success_at"] >= old["last_success_at"]
    with patch.object(
        collector,
        "fetch",
        return_value=(b"", {"http_status": 429, "retry_after": "1800", "final_url": source["feed_url"]}),
    ):
        state = collector.collect_one(storage, None, source, old)
    assert state["status"] == "rate_limited"
    delta = datetime.fromisoformat(state["next_check_at"].replace("Z", "+00:00")) - datetime.fromisoformat(
        state["checked_at"].replace("Z", "+00:00")
    )
    assert delta.total_seconds() >= 1800


@pytest.mark.parametrize("error", [TimeoutError("fixture timeout"), ValueError("invalid XML")])
def test_single_source_failure_does_not_stop_others(storage, source, error):
    with patch.object(collector, "fetch", side_effect=error):
        state = collector.collect_one(storage, None, source, {})
    assert state["status"] == "error"
    with patch.object(
        collector,
        "fetch",
        return_value=(b"<rss><channel/></rss>", {"http_status": 200, "final_url": source["feed_url"]}),
    ):
        healthy = collector.collect_one(storage, None, source, {})
    assert healthy["status"] == "healthy_empty"


def test_metric_month_year_and_specific_entity_boundaries(source):
    item = article(source, title="Headline CPI year-over-year August 2026", topics=["cpi"])
    assert matching.relate({"title": "Core CPI month-over-month August 2026"}, item)[0] == "unmatched"
    assert matching.relate({"title": "Headline CPI year-over-year July 2026"}, item)[0] == "unmatched"
    assert matching.relate({"title": "Headline CPI year-over-year August 2025"}, item)[0] == "unmatched"
    assert matching.relate({"title": "Headline CPI year-over-year August 2026"}, item)[0] == "context"
    item["publisher_id"] = "bls"
    assert matching.relate({"title": "US Headline CPI year-over-year August 2026"}, item)[0] == "direct"
    for country in ("Canada", "Japan", "Australia", "India"):
        assert matching.relate({"title": f"{country} Headline CPI year-over-year August 2026"}, item)[0] == "unmatched"
    assert (
        matching.relate({"title": "Will SpaceX launch a rocket?"}, article(source, title="SpaceX company news"))[0]
        == "unmatched"
    )


def test_snapshot_reuse_does_not_request_provider():
    source = source_map()["usgs"]
    snapshot = {"fetchedAt": "2026-10-01T00:00:00Z", "events": []}
    items, _ = collector.snapshot_items(SimpleNamespace(get_stale=lambda *_: snapshot), source)
    assert items == []


def test_high_frequency_weather_cannot_fill_default_list(storage):
    source = source_map()["usgs"]
    articles = [
        article(
            source,
            title=f"Fixture earthquake {i}",
            url=f"https://earthquake.usgs.gov/earthquakes/eventpage/fixture{i}",
            event_id=str(i),
            magnitude=5,
            source_kind="observation",
            published_at="2026-10-01T00:00:00Z",
        )
        for i in range(20)
    ]
    store.persist(storage, source, articles, "2026-10-01T00:00:00Z")
    assert len(public.payload(storage, now=datetime(2026, 10, 1, 1, tzinfo=timezone.utc))["items"]) == 4


def test_jurisdiction_and_healthy_empty_are_distinct(source):
    item = article(source, publisher_id="fed")
    assert matching.relate({"title": "Will the ECB cut eurozone rates?"}, item)[0] == "unmatched"


def test_public_routes_cannot_bypass_legacy_permissions_or_trigger_acquisition():
    from flask import Flask
    from api.routes.content import create_content_blueprint, ContentRouteDependencies

    def unavailable(*args, **kwargs):
        raise TimeoutError("Fixture database unavailable")

    def forbidden(*args, **kwargs):
        raise AssertionError("A public read triggered collection")

    app = Flask(__name__)
    app.register_blueprint(
        create_content_blueprint(
            ContentRouteDependencies(
                get_market_by_id=lambda _: {"title": "Fixture market"},
                get_related_content_payload=unavailable,
                get_latest_content_payload=lambda **_: {"scope": "global", "items": [{"title": "Legacy unreviewed"}]},
                get_runtime_content_latest=forbidden,
            )
        )
    )
    client = app.test_client()
    assert client.get("/content/latest").json["items"] == []
    response = client.get("/content/market/7?days=30")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30" and response.headers["Cache-Control"] == "no-store"
    result = response.json
    assert result["items"] == [] and result["marketId"] == 7 and result["scope"] == "market"
    assert result["window"]["days"] == 30


def test_global_outage_is_retryable_and_healthy_empty_is_not_an_error():
    from flask import Flask
    from api.routes.content import create_content_blueprint, ContentRouteDependencies
    data = {"scope": "global", "marketId": None, "items": [], "status": "unavailable"}
    app = Flask(__name__)
    app.register_blueprint(create_content_blueprint(ContentRouteDependencies(
        get_market_by_id=lambda _: None, get_related_content_payload=lambda **_: None,
        get_latest_content_payload=lambda **_: data, get_runtime_content_latest=lambda **_: pytest.fail("Unexpected collector"))))
    client = app.test_client()
    assert client.get("/content/latest").status_code == 503
    data["status"] = "ready"
    response = client.get("/content/latest")
    assert response.status_code == 200 and response.json["items"] == []
    assert response.headers["Cache-Control"] == "no-store"


def test_public_read_uses_one_database_query_and_reuses_route_market(storage, source):
    from dataclasses import replace
    from api.services.query_service import ContentStorageDependencies, get_related_content_by_market_id
    from api.services.content_service import get_related_content_payload

    store.persist(storage, source, [article(source)], "2026-10-01T00:00:00Z")
    store.save_state(storage, source["source_id"], {"status": "ok"})
    calls = []
    dependency = ContentStorageDependencies(
        resources=storage.resources, application=storage.application,
        database_path=storage.database_path, get_backend=storage.get_backend,
        table_exists=lambda *_: pytest.fail("A public read checked schema separately"),
        get_connection=storage.get_connection,
        query_all=lambda sql, params=(): calls.append(sql) or storage.query_all(sql, params),
        query_one=lambda *_: pytest.fail("The route's market was queried twice"),
    )
    market = {"id": 7, "title": "Will the Fed cut interest rates after the September 2026 meeting?"}
    result = get_related_content_by_market_id(dependency, 7, days=30, market=market)
    assert len(calls) == 1
    assert result["scope"] == "market" and result["marketId"] == 7
    assert result["items"] and result["items"][0]["relation"] == "context"
    forwarded = []
    result = get_related_content_payload(
        {"get_related_content_by_market_id": lambda mid, **kwargs: forwarded.append(kwargs) or result,
         "query_one": storage.query_one}, 7, days=30, market=market,
    )
    assert forwarded[0]["market"] is market
    from api.services.query_service import get_content_market_by_id
    with storage.get_connection() as conn:
        conn.execute("CREATE TABLE markets (id INTEGER PRIMARY KEY, title TEXT, description TEXT)")
        conn.execute("INSERT INTO markets VALUES (7, 'Fixture question', 'Fixture rules')")
    lookup = replace(dependency, query_one=storage.query_one)
    assert get_content_market_by_id(lookup, 7)["description"] == "Fixture rules"


def test_bls_atom_content_and_fractional_dates():
    source = source_map()["bls-cpi"]
    body = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Fixture CPI August</title><link href="https://www.bls.gov/news.release/archives/fixture.htm"/><content>Actual feed content fixture.</content><published>2026-08-12T07:51:16.21-04:00</published></entry></feed>'
    item = normalize.parse_feed(body, source)[0]
    assert item["published_at"] == "2026-08-12T11:51:16.210000Z"
    assert item["summary"] == "Actual feed content fixture."


def test_nhc_timestamp_urls_and_summary_do_not_duplicate_advisories(storage):
    source = source_map()["nhc-ep"]

    def feed(timestamp):
        return f"<rss><channel><item><title>Summary (EP182026)</title><link>https://www.nhc.noaa.gov/text/refresh/MIATCPEP3+shtml/{timestamp}.shtml</link><description>Summary</description></item><item><title>Rachel Advisory</title><link>https://www.nhc.noaa.gov/text/refresh/MIATCPEP3+shtml/{timestamp}.shtml</link><description>EP182026 Official full feed excerpt {timestamp}</description></item></channel></rss>".encode()

    first = normalize.parse_feed(feed("010234"), source)
    assert len(first) == 1 and first[0]["storm_id"] == "EP182026"
    store.persist(storage, source, first, "2026-10-01T03:00:00Z")
    second = normalize.parse_feed(feed("010834"), source)
    result = store.persist(storage, source, second, "2026-10-01T09:00:00Z")
    assert result["new"] == 0 and result["updated"] == 1
    row = storage.query_one("SELECT url,raw_payload FROM content_items")
    assert row["url"] == json.loads(row["raw_payload"])["url"] == second[0]["url"]
    assert len(storage.query_all("SELECT * FROM content_versions")) == 2


def test_batch_persistence_keeps_identity_and_304_counts_are_current(storage, source):
    items = [article(source, event_id=str(i), url=f"https://www.federalreserve.gov/fixture/{i}") for i in range(401)]
    assert store.persist(storage, source, items, "2026-10-01T00:00:00Z")["new"] == 401
    assert store.persist(storage, source, items, "2026-10-01T00:01:00Z")["duplicate"] == 401
    assert len(storage.query_all("SELECT * FROM content_items")) == 401
    with patch.object(collector, "fetch", return_value=(b"", {"http_status": 304, "final_url": source["feed_url"]})):
        state = collector.collect_one(storage, None, source, {"new": 401, "public": 401, "parsed_count": 401})
    assert state["new"] == state["public"] == state["parsed_count"] == 0


def test_no_service_keys_required_and_http_checks_redirect_and_size(storage, source):
    from api.services.free_content import http

    class Response:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def iter_content(self, _):
            yield b"<rss><channel/></rss>"

    class Session:
        def get(self, url, **kwargs):
            assert set(kwargs["headers"]) <= {"User-Agent", "Accept", "If-None-Match", "If-Modified-Since"}
            return Response()

    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(http.socket, "getaddrinfo", return_value=[(None, None, None, None, ("8.8.8.8", 443))]),
    ):
        body, meta = http.fetch(Session(), source["feed_url"], source)
        assert normalize.parse_feed(body, source) == [] and meta["http_status"] == 200
        with patch.object(collector, "fetch", return_value=(body, meta)):
            assert collector.collect_one(storage, None, source, {})["status"] == "healthy_empty"
        with patch.object(Response, "iter_content", return_value=iter([b"x" * (http.MAX_BYTES + 1)])):
            with pytest.raises(ValueError, match="response-too-large"):
                http.fetch(Session(), source["feed_url"], source)
        with (
            patch.object(Response, "status_code", 302),
            patch.object(Response, "headers", {"Location": "https://127.0.0.1/internal"}),
        ):
            with pytest.raises(ValueError, match="unapproved-host"):
                http.fetch(Session(), source["feed_url"], source)
    with pytest.raises(ValueError, match="not-rss-or-atom"):
        normalize.parse_feed(b"<html><body>Error</body></html>", source)


def test_shared_seed_separates_windows_and_markets_without_more_database_reads(storage, source, tmp_path):
    from api.services.free_content.snapshots import read_payload
    from runtime.snapshot_store import SnapshotStore

    store.persist(storage, source, [article(source)], "2026-10-01T00:00:00Z")
    now = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
    cache = {"store": SnapshotStore(str(tmp_path / "snapshots.db"))}
    first = read_payload(storage, cache, days=30, now=now)
    assert first["cacheMode"] == "database" and len(first["items"]) == 1
    storage.query_all = lambda *_: pytest.fail("Warm content read queried the database")
    assert read_payload(storage, cache, days=7, now=now)["items"] == []
    other = read_payload(storage, cache, days=30, now=now, market_id=2,
                         market={"title": "Will a football club win this season?"})
    assert other["marketId"] == 2 and other["items"] == [] and other["cacheMode"] == "sqlite"


def test_seed_rechecks_expiry_policy_and_reports_staleness(storage, source, tmp_path):
    from api.services.free_content.snapshots import read_payload, refresh_candidates
    from runtime.snapshot_store import SnapshotStore
    from datetime import timedelta

    store.persist(storage, source, [article(source)], "2026-10-01T00:00:00Z")
    now = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
    cache = {"store": SnapshotStore(str(tmp_path / "snapshots.db"))}
    seed = refresh_candidates(storage, cache, now=now)
    storage.query_all = lambda *_: pytest.fail("Bounded stale read queried the database")
    result = read_payload(storage, cache, days=30, now=now + timedelta(seconds=100))
    assert result["stale"] and result["cacheMode"] == "sqlite-stale"
    assert result["generatedAt"] == seed["generatedAt"]
    with patch("api.services.free_content.public.permission", return_value=(False, "revoked")):
        assert read_payload(storage, cache, days=30, now=now)["items"] == []
    with patch("api.services.free_content.public.permitted_item", return_value=False):
        assert read_payload(storage, cache, days=30, now=now)["items"] == []


def test_failed_refresh_retains_last_seed_and_old_seed_cannot_serve_forever(storage, tmp_path):
    from api.services.free_content.snapshots import read_payload, refresh_candidates, NAMESPACE, CACHE_KEY
    from runtime.snapshot_store import SnapshotStore
    from datetime import timedelta

    now = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
    cache = {"store": SnapshotStore(str(tmp_path / "snapshots.db"))}
    seed = refresh_candidates(storage, cache, now=now)
    def failed(*_):
        raise RuntimeError("Fixture database unavailable")
    storage.query_all = failed
    with pytest.raises(RuntimeError):
        refresh_candidates(storage, cache, now=now)
    assert cache["store"].get_stale(NAMESPACE, CACHE_KEY) == seed
    with pytest.raises(RuntimeError):
        read_payload(storage, cache, now=now + timedelta(seconds=301))


def test_overdue_source_is_partial_even_with_successful_previous_response(storage):
    for source_id in source_map():
        store.save_state(storage, source_id, {"status": "ok", "last_success_at": "2026-10-01T00:00:00Z",
                                            "next_check_at": "2026-10-01T00:01:00Z"})
    result = public.payload(storage, now=datetime(2026, 10, 1, 1, tzinfo=timezone.utc))
    assert result["status"] == "partial" and all(s["stale"] for s in result["sources"])


def test_alert_expiry_is_rechecked_inside_fresh_seed(storage, tmp_path):
    from api.services.free_content.snapshots import read_payload, refresh_candidates
    from runtime.snapshot_store import SnapshotStore
    from datetime import timedelta

    source = source_map()["nws"]
    now = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
    store.persist(storage, source, [article(source, url="https://api.weather.gov/alerts/fixture",
        status="Actual", message_type="Alert", published_at="2026-10-01T00:59:00Z",
        expires_at="2026-10-01T01:00:30Z")], now.isoformat())
    cache = {"store": SnapshotStore(str(tmp_path / "snapshots.db"))}
    refresh_candidates(storage, cache, now=now)
    assert len(read_payload(storage, cache, now=now)["items"]) == 1
    storage.query_all = lambda *_: pytest.fail("Expiry check queried the database")
    assert read_payload(storage, cache, now=now + timedelta(seconds=31))["items"] == []


def test_optional_redis_hit_and_failure_fall_back_to_sqlite(storage, tmp_path):
    from api.services.free_content.snapshots import read_payload, refresh_candidates
    from runtime.snapshot_store import SnapshotStore

    now = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
    cache = {"store": SnapshotStore(str(tmp_path / "snapshots.db"))}
    seed = refresh_candidates(storage, cache, now=now)
    storage.query_all = lambda *_: pytest.fail("A warm read queried the database")
    cache["get_json"] = lambda *_: pytest.fail("Fresh local seed waited for optional Redis")
    assert read_payload(storage, cache, now=now)["cacheMode"] == "sqlite"
    local = cache["store"]
    cache["store"] = SimpleNamespace(get_stale=lambda *_: None)
    cache["get_json"] = lambda *_: seed
    assert read_payload(storage, cache, now=now)["cacheMode"] == "redis"
    cache["store"] = local
    def failed(*_):
        raise ConnectionError("Fixture optional cache unavailable")
    cache["get_json"] = failed
    assert read_payload(storage, cache, now=now)["cacheMode"] == "sqlite"


def test_optional_cache_writes_do_not_discard_successful_query_and_worker_requires_persistence(storage):
    from api.services.free_content.snapshots import refresh_candidates
    now = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
    def failed(*_):
        raise OSError("Fixture cache unavailable")
    cache = {"store": SimpleNamespace(set=failed), "set_json": failed}
    assert refresh_candidates(storage, cache, now=now)["records"] == []
    with pytest.raises(RuntimeError, match="could not be persisted"):
        refresh_candidates(storage, cache, now=now, require_cache=True)
    redis = {}
    def write(*args):
        redis["snapshot"] = args[2]  # Existing setter returns None.
    cache.update(set_json=write, get_json=lambda *_: redis.get("snapshot"))
    assert refresh_candidates(storage, cache, now=now, require_cache=True) == redis["snapshot"]


def test_cache_lock_failure_can_use_database_but_lock_contention_cannot_duplicate_queries(storage):
    from api.services.free_content.snapshots import read_payload
    from contextlib import contextmanager
    now = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
    @contextmanager
    def unavailable(*_, **kwargs):
        assert kwargs["timeout"] == 1
        raise PermissionError("Fixture cache filesystem unavailable")
        yield
    cache = {"store": SimpleNamespace(get_stale=lambda *_: None, fetch_lock=unavailable, set=lambda *_: False)}
    assert read_payload(storage, cache, now=now)["cacheMode"] == "database"
    @contextmanager
    def busy(*_, **kwargs):
        raise TimeoutError("Fixture another process owns cold query")
        yield
    cache["store"].fetch_lock = busy
    storage.query_all = lambda *_: pytest.fail("Contended read duplicated the cold query")
    with pytest.raises(TimeoutError):
        read_payload(storage, cache, now=now)


def test_future_seed_cannot_extend_public_cache_lifetime(storage):
    from api.services.free_content.snapshots import read_payload
    now = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
    future = {"schemaVersion": 1, "records": [], "generatedAt": "2026-10-02T01:00:00Z"}
    result = read_payload(storage, {"get_json": lambda *_: future}, now=now)
    assert result["cacheMode"] == "database" and result["generatedAt"] != future["generatedAt"]


def test_source_balanced_candidates_do_not_hide_low_frequency_release(storage, source):
    now = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)
    usgs = source_map()["usgs"]
    records = [article(usgs, external_id=f"quake-{i}", url=f"https://earthquake.usgs.gov/earthquakes/eventpage/fixture{i}",
                       published_at="2026-10-01T12:00:00Z", magnitude=1)
               for i in range(2000)]
    store.persist(storage, usgs, records, "2026-10-01T13:00:00Z")
    store.persist(storage, source, [article(source, published_at="2026-09-30T18:00:00Z")], "2026-10-01T13:00:00Z")
    for sid in source_map():
        store.save_state(storage, sid, {"status": "ok", "last_success_at": "2026-10-01T13:00:00Z"})
    result = public.payload(storage, now=now)
    assert [item["sourceId"] for item in result["items"]] == ["fed-monetary"]
    assert result["coverage"]["truncated"] is False
    assert result["status"] == "ready"
    assert result["coverage"]["candidatesScanned"] == 1
    assert result["coverage"]["rawCandidatesScanned"] == 2001
    assert result["coverage"]["filteredByReason"]["low_magnitude"] == 2000


def test_actual_eligible_quota_still_reports_partial(storage, source):
    now = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)
    records = [article(source, url=f"https://www.federalreserve.gov/newsevents/pressreleases/monetary{i}.htm",
                       published_at="2026-10-01T12:00:00Z") for i in range(public.CANDIDATES_PER_PUBLISHER + 1)]
    store.persist(storage, source, records, "2026-10-01T13:00:00Z")
    for sid in source_map():
        store.save_state(storage, sid, {"status": "ok"})
    result = public.payload(storage, now=now)
    assert result["coverage"]["truncated"] and result["status"] == "partial"
    assert result["coverage"]["candidateTotals"][source["publisher_name"]] == public.CANDIDATES_PER_PUBLISHER + 1
    assert result["coverage"]["candidatesScanned"] == public.CANDIDATES_PER_PUBLISHER


def test_raw_scan_ceiling_is_explicit_and_does_not_hide_other_publisher(storage, source):
    now = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)
    usgs = source_map()["usgs"]
    records = [article(usgs, url=f"https://earthquake.usgs.gov/earthquakes/eventpage/bound{i}",
                       published_at="2026-10-01T12:00:00Z", magnitude=1)
               for i in range(public.RAW_CANDIDATES_PER_PUBLISHER + 1)]
    store.persist(storage, usgs, records, "2026-10-01T13:00:00Z")
    store.persist(storage, source, [article(source, published_at="2026-09-30T18:00:00Z")], "2026-10-01T13:00:00Z")
    for sid in source_map():
        store.save_state(storage, sid, {"status": "ok"})
    result = public.payload(storage, now=now)
    assert result["items"][0]["sourceId"] == source["source_id"]
    assert result["coverage"]["truncated"] and result["status"] == "partial"


def test_sports_gap_is_not_a_broken_feed_or_global_fallback(storage, source):
    now = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)
    store.persist(storage, source, [article(source, published_at="2026-09-30T18:00:00Z")], "2026-10-01T13:00:00Z")
    for sid in source_map():
        store.save_state(storage, sid, {"status": "ok"})
    store.save_state(storage, "nws", {"status": "stale", "snapshot_stale": True})
    result = public.payload(storage, market={"title": "Eagles vs. Bears: O/U 57.5", "category": "sports", "tags": ["NFL"]},
                            market_id=99, now=now)
    assert result["items"] == [] and result["count"] == 0
    assert result["status"] == "ready" and result["empty_reason"] == "market_not_covered"
    assert result["marketCoverage"] == {"status": "unsupported", "topic": "sports", "sourceIds": []}
    assert len(public.payload(storage, now=now)["items"]) == 1
    assert matching.market_coverage({"title": "Eagles vs. Bears: O/U 57.5", "category": "combo"}, source_map().values(), [])["status"] == "unsupported"
    assert matching.market_coverage({"title": "Trump vs. Biden", "category": "politics"}, source_map().values(), [])["status"] == "unknown"


def test_one_bad_source_state_is_isolated(storage, source):
    now = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)
    store.persist(storage, source, [article(source, published_at="2026-09-30T18:00:00Z")], "2026-10-01T13:00:00Z")
    store.save_state(storage, source["source_id"], {"status": "ok"})
    with storage.get_connection() as conn:
        conn.execute("INSERT INTO content_source_state VALUES (?,?)", ("bls-cpi", "broken-json"))
    result = public.payload(storage, now=now)
    assert len(result["items"]) == 1 and result["status"] == "partial"
    assert store.source_states(storage)["bls-cpi"]["error"] == "invalid-source-state"


def test_policy_deadline_is_not_reference_month(source):
    item = {**article(source, published_at="2026-09-16T18:00:00Z"), "publisher_id": "fed"}
    assert matching.relate({"title": "Will the Fed cut rates by December 2026?"}, item)[0] == "context"
    assert matching.relate({"title": "Will the Fed cut rates in December 2026?"}, item)[0] == "unmatched"


def test_http_total_budget_stops_before_request(source):
    from api.services.free_content.http import fetch
    session = SimpleNamespace(get=lambda *a, **k: pytest.fail("Expired budget initiated HTTP"))
    with pytest.raises(TimeoutError, match="budget-exhausted"):
        fetch(session, source["feed_url"], source, deadline=0)


def test_related_seed_is_in_unified_health_registry():
    from api.services.system_service import SEED_META_SPECS
    spec = next(spec for spec in SEED_META_SPECS if spec["panelId"] == "related-news")
    assert (spec["namespace"], spec["cacheKey"]) == ("seed-meta:content", "related-news")


def test_source_refresh_schedule_has_bounded_cycle_grace_without_masking_snapshot_expiry():
    now = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    state = {'last_success_at': '2026-09-30T23:50:00Z', 'next_check_at': '2026-10-01T00:00:00Z'}
    assert not public.source_is_stale(state, now + timedelta(seconds=150))
    assert public.source_is_stale(state, now + timedelta(seconds=151))
    assert public.source_is_stale({**state, 'snapshot_stale': True}, now)


def test_stale_shared_snapshot_retries_next_cycle_without_bypassing_external_feed_backoff():
    stamp = '2026-10-01T00:00:00Z'
    later = '2026-10-01T00:05:00Z'
    states = {s['source_id']: {'status': 'ok', 'next_check_at': later} for s in source_map().values()}
    states['nws']['status'] = 'stale'
    states['nasa-release']['status'] = 'error'
    assert [s['source_id'] for s in collector.due_sources(states, stamp=stamp)] == ['nws']
    states['nws']['status'] = 'rate_limited'
    assert collector.due_sources(states, force=True, selected={'nws'}, stamp=stamp) == []


def test_article_rights_replay_uses_one_batch_read_instead_of_per_article_round_trips(storage):
    source = source_map()['global-voices']
    items = [article(source, url=f'https://globalvoices.org/2026/10/01/fixture-{i}/',
                     author='Alice', article_rights_checked=True) for i in range(20)]
    store.persist(storage, source, items, '2026-10-01T00:00:00Z')
    fresh = [{k:v for k,v in item.items() if k != 'article_rights_checked'} for item in items]
    with patch.object(storage, 'query_all', wraps=storage.query_all) as read, patch.object(collector, 'parse_feed', return_value=fresh), patch.object(collector, 'fetch', return_value=(b'fixture', {'http_status':200,'final_url':source['feed_url']})) as fetch:
        state = collector.collect_one(storage, None, source, {})
    assert read.call_count == 1 and len(read.call_args.args[1]) == 20
    assert fetch.call_count == 1  # unchanged verified rights need no article requests
    assert state['status'] == 'ok' and state['duplicate'] == 20 and state['public'] == 20


def test_failed_ingest_keeps_last_success_and_actual_parsed_denominator(storage, source):
    old = {'status':'ok', 'last_success_at':'2026-09-30T00:00:00Z'}
    with patch.object(collector,'fetch',return_value=(b'fixture',{'http_status':200,'final_url':source['feed_url']})), patch.object(collector,'parse_feed',return_value=[article(source)]), patch.object(collector,'persist',side_effect=TimeoutError('fixture DB deadline')):
        state = collector.collect_one(storage,None,source,old)
    assert state['status'] == 'error' and state['last_success_at'] == old['last_success_at']
    assert state['parsed_count'] == 1
