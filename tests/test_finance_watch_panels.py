from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

from api.services import finance_watch_panels_service as service
from api.services.finance_watch import news, sentiment


def test_partial_index_collection_keeps_failed_row_without_renewing_clock(context, monkeypatch):
    from api.services.finance_watch import markets
    from api.services import seed_recovery
    now = '2026-11-04T09:00:00Z'
    old = {'generatedAt': '2026-11-04T08:50:00Z', 'items': [
        {'id': '^IXIC', 'metric': 20000, 'change': 90, 'tags': ['US'], 'fetchedAt': '2026-11-04T08:40:00Z'},
        {'id': 'removed', 'metric': 5},
    ]}
    context['SNAPSHOT_STORE'] = SimpleNamespace(get_stale=lambda *a: old)
    def quote(symbol, **kwargs):
        if symbol == '^IXIC':
            raise TimeoutError('source')
        return {'price': 6000, 'changePercent': 1, 'fetchedAt': now}
    context['get_yahoo_market_snapshot'] = quote
    monkeypatch.setattr(markets, 'utc_now_iso', lambda: now)
    result = markets.build_global_indices_payload(context, 2)
    assert result['status'] == 'partial'
    assert result['summary']['fetchedCount'] == 1
    assert result['summary']['avgChange'] == 1  # Old rows do not enter current breadth.
    assert [row['id'] for row in result['items']] == ['^GSPC', '^IXIC']
    retained = result['items'][1]
    assert retained['fetchedAt'] == '2026-11-04T08:40:00Z'
    assert retained['retained'] and 'STALE' in retained['tags']
    assert old['items'][0]['tags'] == ['US']
    assert not seed_recovery.retain_failed_rows(result, ['^IXIC'], '2026-11-04T09:11:00Z')


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setattr(sentiment, "requests", None)
    return {
        "SETTINGS": SimpleNamespace(),
        "http_json_get": lambda *args, **kwargs: {},
        "http_text_get": lambda *args, **kwargs: "<rss><channel/></rss>",
        "get_yahoo_market_snapshot": lambda *args, **kwargs: {},
        "get_crypto_funding_watch_snapshot": lambda **kwargs: {"assets": []},
    }


@pytest.mark.parametrize("panel_id", service.FINANCE_WATCH_PANEL_IDS)
def test_empty_sources_remain_explicit_for_every_finance_panel(context, panel_id):
    payload = service.build_finance_watch_panel_payload(
        context, panel_id, external={"fixture": True}
    )
    assert payload["panelId"] == panel_id
    assert payload["status"] == ({"global-index-monitor": "error", "crypto-fear-greed": "error", "broker-research-watch": "error", "tradfi-perp-radar": "warming", "crypto-etf-flow": "warming", "stablecoin-monitor": "warming"}.get(panel_id, "empty"))
    if panel_id == "crypto-fear-greed":
        assert payload["summary"]["score"] is None
        assert all(row["metricLabel"] == "--" for row in payload["items"])
        assert all(row["degraded"] for row in payload["summary"]["categories"])
    else:
        assert payload["items"] == []
        assert payload["summary"]["count"] == 0


def test_news_preserves_source_link_and_publication_time(context, monkeypatch):
    monkeypatch.setattr(news, "utc_now_iso", lambda: "2026-09-29T01:00:00Z")
    context["http_text_get"] = lambda *args, **kwargs: """
        <rss><channel><item>
          <title>Protocol exploit reported</title>
          <link>https://example.com/source</link>
          <source>Source Wire</source>
          <pubDate>Tue, 29 Sep 2026 00:00:00 GMT</pubDate>
          <description>Investigators examine the incident.</description>
        </item></channel></rss>
    """
    payload = service.build_finance_watch_panel_payload(context, "defi-security-watch")
    assert payload["status"] == "ok"
    assert payload["items"][0]["url"] == "https://example.com/source"
    assert payload["items"][0]["publishedAt"] == "2026-09-29T00:00:00Z"


def test_news_refresh_uses_recent_window_and_sorts_before_limiting(context, monkeypatch):
    monkeypatch.setattr(news, "utc_now_iso", lambda: "2026-11-03T08:00:00Z")
    urls = []
    def fetch(url, **kwargs):
        urls.append(url)
        return """<rss><channel>
          <item><title>Old high relevance</title><pubDate>Tue, 29 Sep 2026 00:00:00 GMT</pubDate></item>
          <item><title>Yesterday</title><pubDate>Mon, 02 Nov 2026 00:00:00 GMT</pubDate></item>
          <item><title>Time unknown</title></item>
          <item><title>Future</title><pubDate>Wed, 04 Nov 2026 00:00:00 GMT</pubDate></item>
          <item><title>Latest</title><pubDate>Tue, 03 Nov 2026 07:00:00 GMT</pubDate></item>
        </channel></rss>"""
    context["http_text_get"] = fetch
    payload = news.build_news_payload(context, "defi-security-watch", "Security", limit=1)
    assert [row["title"] for row in payload["items"]] == ["Latest"]
    assert "when%3A7d" in urls[0]


def test_news_invalid_transport_is_not_a_healthy_empty_result(context):
    context["http_text_get"] = lambda *args, **kwargs: "<html>Service unavailable</html>"
    with pytest.raises(ValueError, match="RSS channel"):
        news.build_news_payload(context, "defi-security-watch", "Security", limit=1)


def test_news_identity_survives_feed_reordering(monkeypatch):
    monkeypatch.setattr(news, "utc_now_iso", lambda: "2026-11-06T12:00:00Z")
    first = '<item><title>Protocol report</title><link>https://example.com/report</link><pubDate>Fri, 06 Nov 2026 10:00:00 GMT</pubDate></item>'
    other = '<item><title>Second report</title><link>https://example.com/second</link><pubDate>Fri, 06 Nov 2026 09:00:00 GMT</pubDate></item>'
    def parse(items):
        return news._parse_rss_items('<rss><channel>' + items + '</channel></rss>', panel_id='defi-security-watch', limit=12)
    assert parse(first)[0]['id'] == parse(other + first)[0]['id']
    assert parse(other + first)[0]['id'] != parse(other + first)[1]['id']


def test_original_research_feed_does_not_inherit_parent_news_exclusion(context):
    from api.services.finance_watch import research
    context['SETTINGS'] = SimpleNamespace(finance_broker_research_feed_urls=('https://scr.zacks.com/rss/pressrelease.aspx',))
    context['http_text_get'] = lambda *args, **kwargs: '<rss><channel><item><title>MTVA: Research update</title><description>MetALD trial updates; unrelated sector comparison mentions Meta.</description><link>https://scr.zacks.com/news/news-details/2026/report/default.aspx</link><pubDate>Thu, 05 Nov 2026 12:00:00 -0500</pubDate></item></channel></rss>'
    payload = research.build_broker_research_payload(context, 12)
    assert payload['status'] == 'ok'
    assert payload['items'][0]['label'] == 'MTVA'
    assert payload['items'][0]['publishedAt'] == '2026-11-05T17:00:00Z'
    assert not research._is_original_research_url('https://www.zacks.com/commentary/research-summary')


@pytest.mark.parametrize("panel_id", ["defi-security-watch", "ipo-news-watch", "blockchain-policy-news"])
@pytest.mark.parametrize("failed", [False, True])
def test_news_worker_replaces_old_window_only_after_success(monkeypatch, panel_id, failed):
    from unittest.mock import Mock
    from runtime.finance_watch_panels_watcher import FinanceWatchPanelsWatcher
    worker = object.__new__(FinanceWatchPanelsWatcher)
    worker.limit = 24
    worker.service_context = lambda: {}
    from datetime import datetime, timedelta, timezone
    previous = {"generatedAt": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(), "status": "ok", "items": [{"title": "Old news"}]}
    fresh = {"generatedAt": "2026-11-03T08:00:00Z", "status": "error" if failed else "empty",
             "sources": {"googleNewsRss": "error" if failed else "empty"}, "items": []}
    worker.load_previous_payload = lambda _: previous
    worker.store_payload = Mock()
    worker.store_seed_meta = Mock()
    monkeypatch.setattr(service, "FINANCE_WATCH_PANEL_IDS", [panel_id])
    monkeypatch.setattr(service, "build_finance_watch_panel_payload", lambda *a, **k: fresh)
    worker.run_once()
    worker.store_payload.assert_called_once()
    stored_panel, stored = worker.store_payload.call_args.args
    assert stored_panel == panel_id
    if failed:
        assert stored["generatedAt"] == previous["generatedAt"]
        assert stored["items"] == previous["items"]
        assert stored["status"] == "stale"
        assert stored["sources"] == fresh["sources"]
    else:
        assert stored == fresh
    assert worker.store_seed_meta.call_args.kwargs.get("preserve_last_success", False) == failed


def test_funding_keeps_asset_order_and_shorts_pay_sign(context):
    context["get_crypto_funding_watch_snapshot"] = lambda **kwargs: {
        "assets": [
            {"asset": "ETH", "consensusFundingPercent": 0.02, "bias": "longs-pay"},
            {"asset": "BTC", "consensusFundingPercent": 0.01, "bias": "shorts-pay"},
        ],
        "sources": {"funding": "degraded"},
    }
    payload = service.build_finance_watch_panel_payload(context, "crypto-perp-funding")
    assert [row["label"] for row in payload["items"]] == ["BTC", "ETH"]
    assert [row["metric"] for row in payload["items"]] == [-0.01, 0.02]
    assert payload["sources"] == {"funding": "degraded"}


def test_stale_snapshot_retains_evidence_and_trims_without_mutating_cache(context, monkeypatch):
    cached = {
        "generatedAt": (datetime.now(timezone.utc) - timedelta(seconds=1000)).isoformat(),
        "stablecoin": {"status": "stale", "items": [{"symbol": str(index)} for index in range(8)]},
    }
    context["SNAPSHOT_STORE"] = SimpleNamespace(
        get=lambda *args: None, get_stale=lambda *args: cached
    )
    payload = service.get_finance_watch_panel_snapshot(context, "stablecoin-monitor", 3)
    assert payload["cacheMode"] == "stale-seed"
    assert payload["generatedAt"] == cached["generatedAt"]
    assert payload["status"] == "stale"
    assert payload["sources"] == {"financeExternal": "stale"}
    assert payload["summary"]["count"] == 3
    assert payload["summary"]["totalCount"] == 8
    assert len(cached["stablecoin"]["items"]) == 8


EXTERNAL_VIEWS = [("tradfi-perp-radar", "tradfiPerps"), ("crypto-etf-flow", "etfFlow"),
                  ("stablecoin-monitor", "stablecoin")]


@pytest.fixture
def external_projection_context(context, monkeypatch):
    from api.services import finance_external_sources_service as external_service
    now = "2026-11-06T15:00:00Z"
    monkeypatch.setattr(service, "utc_now_iso", lambda: now)
    monkeypatch.setattr(external_service, "utc_now_iso", lambda: now)
    stored = {}
    reads = []

    def read(namespace, key):
        reads.append((namespace, key))
        assert (namespace, key) == (external_service.FINANCE_EXTERNAL_NAMESPACE, "v1")
        return stored.get("external")

    def forbidden(*args, **kwargs):
        pytest.fail("A pure projection must not acquire data or write a derived snapshot")

    context["SNAPSHOT_STORE"] = SimpleNamespace(get_stale=read, get=forbidden, set=forbidden)
    for name in ("http_json_get", "http_json_post", "http_text_get", "get_yahoo_market_snapshot",
                 "set_cached_json", "get_snapshot_payload"):
        context[name] = forbidden
    context["get_cached_json"] = lambda *args: None
    monkeypatch.setattr(service.seed_recovery, "recover_seed", forbidden)
    return context, stored, reads


@pytest.mark.parametrize("panel_id,branch", EXTERNAL_VIEWS)
def test_external_projection_reads_each_new_durable_source_without_waiting_for_finance_owner(
    external_projection_context, panel_id, branch,
):
    context, stored, reads = external_projection_context
    for generated, symbol in [("2026-11-06T14:50:00Z", "OLD"), ("2026-11-06T14:59:00Z", "NEW")]:
        stored["external"] = {"generatedAt": generated, branch: {"status": "ok", "items": [
            {"symbol": symbol, "lastPx": 100, "price": 1, "fetchedAt": generated},
        ]}}
        payload = service.get_finance_watch_panel_snapshot(context, panel_id, 3)
        assert payload["generatedAt"] == generated
        assert payload["items"][0]["id"] == symbol
        assert payload["items"][0]["fetchedAt"] == generated
        assert payload["status"] == "ok"
        assert payload["cacheMode"] == "external-seed"
    assert len(reads) == 2


@pytest.mark.parametrize("panel_id,branch", EXTERNAL_VIEWS)
def test_external_projection_does_not_renew_retained_or_expired_rows(external_projection_context, panel_id, branch):
    context, stored, _ = external_projection_context
    stored["external"] = {"generatedAt": "2026-11-06T14:59:00Z", branch: {"status": "partial", "items": [
        {"symbol": "RETAINED", "fetchedAt": "2026-11-06T14:40:00Z", "retained": True, "sourceStatus": "stale"},
        {"symbol": "EXPIRED", "fetchedAt": "2026-11-06T14:30:00Z"},
    ]}}
    payload = service.get_finance_watch_panel_snapshot(context, panel_id, 3)
    assert payload["generatedAt"] == stored["external"]["generatedAt"]
    assert payload["status"] == "partial"
    assert len(payload["items"]) == 1
    row = payload["items"][0]
    assert row["id"] == "RETAINED" and row["retained"] and row["sourceStatus"] == "stale"
    assert row["fetchedAt"] == "2026-11-06T14:40:00Z"
    assert len(stored["external"][branch]["items"]) == 2


@pytest.mark.parametrize("panel_id,branch", EXTERNAL_VIEWS)
@pytest.mark.parametrize("generated,status", [("2026-11-06T14:45:00Z", "stale"),
    ("2026-11-06T14:30:00Z", "warming"), (None, "warming"), ("invalid", "warming")])
def test_external_projection_keeps_original_freshness_and_missing_clock_boundary(
    external_projection_context, panel_id, branch, generated, status,
):
    context, stored, _ = external_projection_context
    stored["external"] = {"generatedAt": generated, branch: {"status": "ok", "items": [{"symbol": "SOURCE"}]}}
    payload = service.get_finance_watch_panel_snapshot(context, panel_id)
    assert payload["status"] == status
    assert payload["generatedAt"] == (generated if status == "stale" else "")
    assert bool(payload["items"]) == (status == "stale")


def test_unknown_finance_panel_is_rejected(context):
    with pytest.raises(KeyError, match="unknown finance watch panel"):
        service.build_finance_watch_panel_payload(context, "unregistered")


def test_index_failure_is_isolated_and_does_not_bypass_owner_transport(context, monkeypatch):
    from api.services.finance_watch import common, markets
    monkeypatch.setattr(markets, 'GLOBAL_INDEX_SYMBOLS', [('First', 'A', 'US'), ('Second', 'B', 'EU')])
    def quote(symbol, **kwargs):
        if symbol == 'A':
            raise TimeoutError('route temporarily down')
        return {'price': 100, 'changePercent': 1, 'fetchedAt': 'observed'}
    context['get_yahoo_market_snapshot'] = quote
    context['http_json_get'] = lambda *a, **k: pytest.fail('must not retry outside the owner transport')
    result = markets.build_global_indices_payload(context, 2)
    assert result['status'] == 'partial'
    assert [item['id'] for item in result['items']] == ['B']
    assert result['summary']['failedSymbols'] == ['A']
    def unavailable(*args, **kwargs):
        raise TimeoutError('failure')
    context['http_text_get'] = unavailable
    monkeypatch.setattr(common.requests, 'Session', lambda: pytest.fail('must not use inherited proxy after failure'))
    with pytest.raises(TimeoutError):
        common._http_text_get(context, 'https://source.example/rss')
