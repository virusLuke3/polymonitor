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
    assert payload["status"] == ("error" if panel_id == "global-index-monitor" else "empty")
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


@pytest.mark.parametrize("panel_id", ["defi-security-watch", "ipo-news-watch", "blockchain-policy-news"])
@pytest.mark.parametrize("failed", [False, True])
def test_news_worker_replaces_old_window_only_after_success(monkeypatch, panel_id, failed):
    from unittest.mock import Mock
    from runtime.finance_watch_panels_watcher import FinanceWatchPanelsWatcher
    worker = object.__new__(FinanceWatchPanelsWatcher)
    worker.limit = 24
    worker.service_context = lambda: {}
    previous = {"generatedAt": "2026-10-01T00:00:00Z", "status": "ok", "items": [{"title": "Old news"}]}
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
    monkeypatch.setattr(service.seed_recovery, "recover_seed", lambda *args: False)
    cached = {
        "panelId": "stablecoin-monitor",
        "generatedAt": (datetime.now(timezone.utc) - timedelta(seconds=1000)).isoformat(),
        "status": "degraded",
        "sources": {"financeExternal": "stale"},
        "items": [{"id": str(index)} for index in range(8)],
    }
    context["SNAPSHOT_STORE"] = SimpleNamespace(
        get=lambda *args: None, get_stale=lambda *args: cached
    )
    payload = service.get_finance_watch_panel_snapshot(context, "stablecoin-monitor", 3)
    assert payload["cacheMode"] == "stale-seed"
    assert payload["generatedAt"] == cached["generatedAt"]
    assert payload["status"] == "stale"
    assert payload["sources"] == cached["sources"]
    assert payload["summary"] == {"count": 3, "totalCount": 8}
    assert len(cached["items"]) == 8


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
