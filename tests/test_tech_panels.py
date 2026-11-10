from __future__ import annotations

import json
import pytest
from types import SimpleNamespace


from api.runtime_panels.registry import get_panel_by_id
from api.services import tech_panels_service


RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss><channel>
  <item>
    <title>OpenAI launches new model benchmark push - Reuters</title>
    <link>https://example.com/openai</link>
    <guid>openai-1</guid>
    <pubDate>Sun, 24 May 2026 10:00:00 GMT</pubDate>
    <source>Reuters</source>
    <description>OpenAI model release signal.</description>
  </item>
  <item>
    <title>TikTok app ban lawsuit update - CNBC</title>
    <link>https://example.com/tiktok</link>
    <guid>tiktok-1</guid>
    <pubDate>Sun, 24 May 2026 09:00:00 GMT</pubDate>
    <source>CNBC</source>
    <description>TikTok regulation signal.</description>
  </item>
</channel></rss>
"""

OPENROUTER_MODELS = {
    "data": [
        {
            "id": "qwen/qwen3.7-max",
            "canonical_slug": "qwen/qwen3.7-max-20260520",
            "name": "Qwen: Qwen3.7 Max",
            "created": 1779376861,
            "description": "Flagship Qwen model for agent-centric workloads.",
            "context_length": 1000000,
            "pricing": {"prompt": "0.0000025", "completion": "0.0000075"},
        },
        {
            "id": "x-ai/grok-build-0.1",
            "canonical_slug": "x-ai/grok-build-0.1-20260520",
            "name": "xAI: Grok Build 0.1",
            "created": 1779298123,
            "description": "Fast coding model.",
            "context_length": 256000,
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        },
    ]
}

OPENROUTER_RANKINGS_ROWS = [
    {"variant_permaslug": "qwen/qwen3.7-max-20260520", "total_completion_tokens": 1000000000, "total_prompt_tokens": 2000000000, "count": 120000, "change": 0.22},
    {"variant_permaslug": "x-ai/grok-build-0.1-20260520", "total_completion_tokens": 400000000, "total_prompt_tokens": 600000000, "count": 42000},
]


def rankings_html(view="week", rows=None):
    query = {"queryKey": ["rankings", "models", {"view": view}], "state": {
        "status": "success", "dataUpdatedAt": 1779580800000,
        "data": OPENROUTER_RANKINGS_ROWS if rows is None else rows}}
    rsc = "7a:" + json.dumps(["$", "component", None, {"state": {"queries": [query]}}])
    # Real RSC records may span multiple script chunks.
    return "".join("<script>self.__next_f.push(" + json.dumps([1, piece]) + ")</script>" for piece in [rsc[:50], rsc[50:]])


def _ctx():
    def http_text_get(url, timeout=12, headers=None):
        if "openrouter.ai/rankings" in url:
            return rankings_html()
        assert "news.google.com" in url
        return RSS_XML

    def http_json_get(url, params=None, timeout=12, headers=None):
        if "openrouter.ai/api/v1/models" in url:
            return OPENROUTER_MODELS
        assert "itunes.apple.com" in url
        if "topgrossingapplications" in url:
            title = "iTunes Store: Top Grossing Apps"
            names = [("ChatGPT", "OpenAI"), ("YouTube", "Google")]
        elif "genre=6014" in url:
            title = "iTunes Store: Top Free Applications in Games"
            names = [("Roblox", "Roblox Corporation"), ("Block Blast!", "Hungry Studio")]
        elif "genre=6009" in url:
            title = "iTunes Store: Top Free Applications in News"
            names = [("X", "X Corp."), ("Reddit", "reddit")]
        else:
            title = "iTunes Store: Top Free Apps"
            names = [("ChatGPT", "OpenAI"), ("TikTok", "TikTok Ltd.")]
        while len(names) < 10:
            names.append((f"{names[0][0]} {len(names) + 1}", names[0][1]))
        return {
            "feed": {
                "title": {"label": title},
                "entry": [
                    {
                        "im:name": {"label": name},
                        "im:artist": {"label": artist},
                        "id": {"attributes": {"im:id": str(index)}},
                        "link": {"attributes": {"href": f"https://apps.apple.com/app/{index}"}},
                    }
                    for index, (name, artist) in enumerate(names, start=1)
                ]
            }
        }

    def yahoo(symbol, interval="30m", range_name="5d", ttl_seconds=None):
        prices = {
            "NVDA": (180.0, 4_400_000_000_000, 2.4),
            "AAPL": (220.0, 3_400_000_000_000, -0.5),
            "MSFT": (510.0, 3_800_000_000_000, 0.8),
        }
        price, market_cap, change = prices.get(symbol, (100.0, 1_000_000_000_000, 0.0))
        return {
            "symbol": symbol,
            "price": price,
            "marketCap": market_cap,
            "changePercent": change,
            "points": [{"timestamp": "2026-05-24T00:00:00Z", "value": price}],
        }

    return {
        "SETTINGS": SimpleNamespace(
            tech_runtime_ttl_seconds=600,
            tech_google_news_rss_url="https://news.google.com/rss/search",
            tech_app_store_top_free_url="https://rss.applemarketingtools.com/api/v2/us/apps/top-free/25/apps.json",
        ),
        "http_text_get": http_text_get,
        "http_json_get": http_json_get,
        "get_yahoo_market_snapshot": yahoo,
        "utc_now_iso": lambda: "2026-05-24T00:00:00Z",
    }


def test_tech_runtime_panels_are_registered():
    assert get_panel_by_id("ai-model-race").route == "/runtime/tech/ai-model-race"
    assert get_panel_by_id("big-tech-market-cap").route == "/runtime/tech/big-tech-market-cap"
    assert get_panel_by_id("consumer-app-pulse").route == "/runtime/tech/consumer-app-pulse"


def test_ai_model_race_payload_extracts_entity_and_tags():
    payload = tech_panels_service.build_tech_panel_payload(_ctx(), "ai-model-race", limit=36)

    assert payload["status"] == "ok"
    assert payload["sources"]["openRouterUsage"] == "ok"
    assert payload["sources"]["productSignal"] == "ok"
    assert payload["sources"]["apiPrice"] == "ok"
    assert [item["symbol"] for item in payload["summary"]["watchlist"]] == ["NEWS", "USAGE", "PRODUCT SIGNAL", "API PRICE"]
    usage_items = [item for item in payload["items"] if item.get("category") == "USAGE"]
    assert usage_items[0]["source"] == "OpenRouter Usage"
    assert usage_items[0]["metricLabel"] == "3.00B TOK"
    assert any("API PRICE" in item["tags"] for item in payload["items"])


def test_big_tech_market_cap_payload_ranks_by_market_cap():
    payload = tech_panels_service.build_tech_panel_payload(_ctx(), "big-tech-market-cap", limit=16)

    assert payload["status"] == "ok"
    assert payload["items"][0]["symbol"] == "NVDA"
    assert payload["items"][0]["metricUnit"] == "MKT CAP"
    assert payload["items"][0]["rank"] == 1
    assert len(payload["items"]) == 16
    assert payload["summary"]["tracked"] >= 20


def test_slow_cap_provider_cannot_starve_remaining_quote_symbols():
    ctx = _ctx()
    original_quote = ctx['get_yahoo_market_snapshot']
    cap_started = False
    quotes = []
    def quote(symbol, **kwargs):
        assert not cap_started, 'An independent cap failure consumed the quote batch budget'
        quotes.append(symbol)
        return original_quote(symbol, **kwargs)
    def cap(symbol):
        nonlocal cap_started
        cap_started = True
        raise TimeoutError('cap provider exhausted its remaining budget')
    ctx.update(get_yahoo_market_snapshot=quote, get_nasdaq_market_cap=cap)
    result = tech_panels_service.build_big_tech_market_cap_payload(ctx, 24)
    assert len(quotes) == len(tech_panels_service.BIG_TECH_SYMBOLS)
    assert result['summary']['fetchedCount'] == 24
    assert result['sources']['yahoo'] == 'ok'
    assert result['sources']['nasdaqMarketCap'] == 'unavailable'


def test_big_tech_missing_cap_keeps_quotes_without_inventing_cap_or_rank():
    ctx = _ctx()

    def yahoo_without_cap(symbol, interval="30m", range_name="5d", ttl_seconds=None):
        return {
            "symbol": symbol,
            "price": {"NVDA": 200.0, "AAPL": 100.0}.get(symbol, 10.0),
            "changePercent": 0.0,
            "points": [],
        }

    ctx["get_yahoo_market_snapshot"] = yahoo_without_cap
    payload = tech_panels_service.build_tech_panel_payload(ctx, "big-tech-market-cap", limit=2)

    assert payload["status"] == "partial"
    assert payload["items"][0]["symbol"] == "NVDA"
    assert payload["items"][0]["marketCap"] is None
    assert payload["items"][0]["marketCapEstimated"] is False
    assert payload["items"][0]["rank"] is None
    assert payload["items"][0]["metricLabel"] == "--"
    assert payload["items"][0]["price"] == 200.
    assert payload["summary"]["marketCapCount"] == 0
    assert len(payload["summary"]["missingMarketCapSymbols"]) == 24
    assert payload["sources"]["yahooMarketCap"] == "unavailable"


def test_big_tech_cap_failure_retains_its_original_clock_while_quote_refreshes():
    from datetime import datetime, timedelta, timezone
    old_at = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    previous = {"items": [{"id": "NVDA", "symbol": "NVDA", "marketCap": 4_500_000_000_000,
                            "marketCapSource": "nasdaq-stock-summary", "marketCapFetchedAt": old_at,
                            "marketCapQuoteAt": None, "marketCapCurrency": "USD"}]}
    ctx = _ctx()
    ctx["SNAPSHOT_STORE"] = SimpleNamespace(get_stale=lambda *args: previous)
    def failed_cap(symbol):
        raise TimeoutError("source failed")
    ctx["get_nasdaq_market_cap"] = failed_cap
    result = tech_panels_service.build_big_tech_market_cap_payload(ctx, 24)
    row = next(row for row in result["items"] if row["symbol"] == "NVDA")
    assert row["price"] == 180.
    assert row["marketCap"] == 4_500_000_000_000
    assert row["marketCapFetchedAt"] == old_at
    assert row["marketCapStatus"] == "stale"
    assert row["fetchedAt"] != old_at
    assert result["status"] == "partial"
    previous["items"][0]["marketCapFetchedAt"] = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
    expired = tech_panels_service.build_big_tech_market_cap_payload(ctx, 24)
    assert all(row["marketCap"] is None for row in expired["items"])


def test_big_tech_real_cap_survives_quote_failure_and_rejects_estimated_last_good():
    ctx = _ctx()
    ctx["get_yahoo_market_snapshot"] = lambda *a, **k: None
    ctx["get_nasdaq_market_cap"] = lambda symbol: {
        "marketCap": 1000., "marketCapSource": "nasdaq-stock-summary", "marketCapSymbol": symbol,
        "marketCapCurrency": "USD", "marketCapFetchedAt": "2026-11-06T04:00:00Z", "marketCapQuoteAt": None}
    result = tech_panels_service.build_big_tech_market_cap_payload(ctx, 24)
    assert result["status"] == "partial"
    assert result["summary"]["marketCapCount"] == 24
    assert len(result["summary"]["failedSymbols"]) == 24
    assert all(row["price"] is None and row["quoteAt"] is None for row in result["items"])
    assert all(row["marketCapStatus"] == "available" for row in result["items"])
    previous = {"items": [{**result["items"][0], "marketCapEstimated": True}]}
    ctx["SNAPSHOT_STORE"] = SimpleNamespace(get_stale=lambda *a: previous)
    ctx["get_yahoo_market_snapshot"] = _ctx()["get_yahoo_market_snapshot"]
    ctx["get_nasdaq_market_cap"] = lambda symbol: None
    assert all(row["marketCap"] is None for row in tech_panels_service.build_big_tech_market_cap_payload(ctx, 24)["items"])


def test_big_tech_whole_snapshot_fallback_never_restores_estimated_or_expired_cap():
    payload = {"items": [
        {"symbol": "NVDA", "marketCap": 9e12, "marketCapEstimated": True, "price": 180.},
        {"symbol": "TSM", "marketCap": 2e12, "marketCapSource": "nasdaq-stock-summary", "marketCapFetchedAt": "2000-01-01T00:00:00Z"},
    ]}
    result = tech_panels_service.bounded_big_tech_caps(payload)
    assert all(row["marketCap"] is None and row["rank"] is None for row in result["items"])
    assert result["items"][0]["price"] == 180.
    assert payload["items"][0]["marketCap"] == 9e12


def test_consumer_app_pulse_combines_app_store_and_news():
    payload = tech_panels_service.build_tech_panel_payload(_ctx(), "consumer-app-pulse", limit=40)

    assert payload["status"] == "ok"
    assert payload["sources"]["appStoreCharts"] == "ok"
    assert payload["summary"]["appStoreSourceCount"] >= 20
    assert [item["symbol"] for item in payload["summary"]["watchlist"]] == ["DOWNLOADS", "GAMES", "NEWS", "GROSSING"]
    assert [item["count"] for item in payload["summary"]["watchlist"]] == [10, 10, 10, 10]
    assert "TOP FREE" not in payload["items"][0]["tags"]
    categories = [item["category"] for item in payload["items"]]
    assert len(payload["items"]) == 40
    assert categories.count("DOWNLOADS") == 10
    assert categories.count("GAMES") == 10
    assert categories.count("NEWS") == 10
    assert categories.count("GROSSING") == 10


def test_app_chart_failures_are_not_healthy_empty():
    ctx = _ctx()
    def failed(*args, **kwargs):
        raise TimeoutError("source timeout")
    ctx["http_json_get"] = failed
    result = tech_panels_service.build_consumer_app_pulse_payload(ctx, 40)
    assert result["status"] == "error"
    assert result["sources"]["appStoreCharts"] == "error"
    assert len(result["summary"]["appStoreFailures"]) == len(tech_panels_service.APP_STORE_CHART_FEEDS)


def test_app_chart_wrong_schema_is_not_a_valid_empty_chart():
    ctx = _ctx()
    ctx["http_json_get"] = lambda *args, **kwargs: {"error": "upstream failure"}
    result = tech_panels_service.build_consumer_app_pulse_payload(ctx, 40)
    assert result["sources"]["appStoreCharts"] == "error"


@pytest.mark.parametrize("html", ["<html>Server Action unavailable</html>", rankings_html("day"), rankings_html(rows=[{"wrong": 1}])])
def test_openrouter_rejects_missing_or_wrong_weekly_query(html):
    with pytest.raises(ValueError):
        tech_panels_service._parse_openrouter_rankings_page(html)


def test_openrouter_source_clock_and_partial_status():
    payload = tech_panels_service.build_ai_model_race_payload(_ctx(), 24)
    row = next(item for item in payload["items"] if item.get("symbol") == "USAGE")
    assert row["sourceUpdatedAt"] == "2026-05-24T00:00:00Z"
    assert tech_panels_service._payload("test", title="test", items=[row], sources={"models": "ok", "usage": "error"})["status"] == "partial"


def test_failed_quote_universe_is_not_authoritative_empty():
    ctx = _ctx()
    ctx["get_yahoo_market_snapshot"] = lambda *args, **kwargs: None
    result = tech_panels_service.build_big_tech_market_cap_payload(ctx, 24)
    assert result["status"] == "error"
    assert result["sources"]["yahoo"] == "error"


def test_partial_big_tech_keeps_original_quote_clock(monkeypatch):
    from types import SimpleNamespace
    ctx = _ctx()
    quote = ctx['get_yahoo_market_snapshot']
    ctx['get_yahoo_market_snapshot'] = lambda symbol, **kw: None if symbol == 'NVDA' else quote(symbol, **kw)
    previous = {'generatedAt': '2026-11-04T08:50:00Z', 'items': [{
        'id': 'NVDA', 'label': 'Nvidia', 'symbol': 'NVDA', 'marketCap': 9e12,
        'fetchedAt': '2026-11-04T08:40:00Z', 'quoteAt': '2026-11-03T21:00:00Z', 'tags': ['CHIPS'],
    }]}
    ctx['SNAPSHOT_STORE'] = SimpleNamespace(get_stale=lambda *a: previous)
    monkeypatch.setattr(tech_panels_service, 'utc_now_iso', lambda: '2026-11-04T09:00:00Z')
    result = tech_panels_service.build_big_tech_market_cap_payload(ctx, 24)
    assert result['status'] == 'partial'
    assert result['summary']['retainedCount'] == 1
    assert result['summary']['failedSymbols'] == ['NVDA']
    row = next(row for row in result['items'] if row['id'] == 'NVDA')
    assert row['fetchedAt'] == '2026-11-04T08:40:00Z' and row['retained']
    assert row['quoteAt'] == '2026-11-03T21:00:00Z'


def test_big_tech_does_not_retain_legacy_estimated_market_cap(monkeypatch):
    ctx = _ctx()
    quote = ctx['get_yahoo_market_snapshot']
    ctx['get_yahoo_market_snapshot'] = lambda symbol, **kw: None if symbol == 'NVDA' else quote(symbol, **kw)
    previous = {'generatedAt': '2026-11-04T08:50:00Z', 'items': [{
        'id': 'NVDA', 'label': 'Nvidia', 'symbol': 'NVDA', 'marketCap': 9e12,
        'marketCapEstimated': True, 'metric': 9e12, 'metricLabel': '$9.00T',
        'fetchedAt': '2026-11-04T08:40:00Z', 'quoteAt': '2026-11-03T21:00:00Z', 'tags': ['CHIPS'],
    }]}
    ctx['SNAPSHOT_STORE'] = SimpleNamespace(get_stale=lambda *a: previous)
    monkeypatch.setattr(tech_panels_service, 'utc_now_iso', lambda: '2026-11-04T09:00:00Z')
    result = tech_panels_service.build_big_tech_market_cap_payload(ctx, 24)
    row = next(row for row in result['items'] if row['id'] == 'NVDA')
    assert row['marketCap'] is None and row['metric'] is None and row['rank'] is None
    assert row['metricLabel'] == '--'
    assert row['fetchedAt'] == '2026-11-04T08:40:00Z'
    assert result['summary']['missingMarketCapSymbols'] == ['NVDA']


def test_ai_partial_source_retention_expires_from_original_fetch(monkeypatch):
    monkeypatch.setattr(tech_panels_service, "utc_now_iso", lambda: "2026-05-24T00:00:00Z")
    previous = tech_panels_service.build_ai_model_race_payload(_ctx(), 36)
    ctx = _ctx()
    ctx["get_cached_json"] = lambda *a: previous
    getter = ctx["http_text_get"]
    def failed_rankings(url, **kwargs):
        if "openrouter.ai/rankings" in url:
            raise TimeoutError("source timeout")
        return getter(url, **kwargs)
    ctx["http_text_get"] = failed_rankings
    monkeypatch.setattr(tech_panels_service, "utc_now_iso", lambda: "2026-05-24T00:10:00Z")
    partial = tech_panels_service.build_ai_model_race_payload(ctx, 36)
    rows = [row for row in partial["items"] if row.get("category") == "USAGE"]
    assert rows and rows[0]["retained"]
    assert rows[0]["sourceFetchedAt"] == "2026-05-24T00:00:00Z"
    assert partial["sources"]["openRouterUsage"] == "error"
    previous = partial
    monkeypatch.setattr(tech_panels_service, "utc_now_iso", lambda: "2026-05-24T00:31:00Z")
    expired = tech_panels_service.build_ai_model_race_payload(ctx, 36)
    assert not [row for row in expired["items"] if row.get("category") == "USAGE"]
