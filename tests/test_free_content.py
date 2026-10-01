"""Isolated fixtures only: none of these records enter the real content database."""

from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone
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
    assert matching.relate({"title": "Headline CPI year-over-year August 2026"}, item)[0] == "direct"
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
    result = client.get("/content/market/7").json
    assert result["items"] == [] and result["marketId"] == 7 and result["scope"] == "market"


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
