from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests


from api.services import finance_external_sources_service, finance_panels_service


@pytest.fixture(autouse=True)
def no_live_finance_fallback(monkeypatch):
    # An unhandled fixture URL must never fall through to real HTTP.
    monkeypatch.setattr(finance_external_sources_service, "requests", None)


def _ctx():
    def http_json_post(url, json_payload=None, timeout=12, headers=None):
        assert "hyperliquid" in url
        return [
            {"universe": [{"name": "BTC"}, {"name": "ETH"}, {"name": "DOGE"}]},
            [
                {"markPx": "77000", "oraclePx": "77001", "openInterest": "10", "dayNtlVlm": "1000000", "funding": "0.0001"},
                {"markPx": "2100", "oraclePx": "2101", "openInterest": "20", "dayNtlVlm": "2000000", "funding": "-0.0002"},
                {"markPx": "0.1", "openInterest": "1", "dayNtlVlm": "2", "funding": "0"},
            ],
        ]

    def http_json_get(url, params=None, timeout=12, headers=None):
        if "okx" in url:
            return {"code": "0", "data": [{"instType": "SWAP", "instId": "BTC-USDT-SWAP", "last": "80000"}]}
        if "yahoo" in url:
            return {"chart": {"result": []}}
        if "stablecoins" in url:
            return {
                "peggedAssets": [
                    {
                        "symbol": "USDT",
                        "name": "Tether",
                        "price": 0.999,
                        "pegMechanism": "fiat-backed",
                        "circulating": {"peggedUSD": 1000},
                        "circulatingPrevDay": {"peggedUSD": 990},
                        "circulatingPrevWeek": {"peggedUSD": 980},
                    }
                ]
            }
        if "cftc" in url:
            return [
                {
                    "market_and_exchange_names": "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
                    "report_date_as_yyyy_mm_dd": "2026-05-12T00:00:00.000",
                    "open_interest_all": "100",
                    "noncomm_positions_long_all": "60",
                    "noncomm_positions_short_all": "40",
                }
            ]
        raise AssertionError(url)

    def yahoo(symbol, interval="30m", range_name="5d", ttl_seconds=None):
        return {"symbol": symbol, "price": 10, "changePercent": 2, "volume24h": 1000}

    return {
        "SETTINGS": SimpleNamespace(
            finance_hyperliquid_info_url="https://hyperliquid.test/info",
            finance_okx_market_ticker_url="https://okx.test/ticker",
            finance_okx_market_tickers_url="https://okx.test/tickers",
            finance_defillama_stablecoins_url="https://stablecoins.test/",
            finance_cftc_legacy_cot_url="https://cftc.test/",
            finance_yahoo_chart_url_template="https://yahoo.test/chart/{symbol}",
        ),
        "http_json_get": http_json_get,
        "http_json_post": http_json_post,
        "get_yahoo_market_snapshot": yahoo,
        "utc_now_iso": lambda: "2026-05-19T00:00:00Z",
    }


def test_finance_external_sources_payload_has_seeded_sources():
    payload = finance_external_sources_service.build_finance_external_sources_payload(_ctx())

    assert payload["status"] == "partial"  # OKX returned no usable instruments.
    assert payload["sources"]["okxTradfiPerps"] == "empty"
    assert payload["sources"]["hyperliquid"] == "ok"
    assert payload["sources"]["tradexyz"] == "proxy"
    assert payload["summary"]["perpCount"] == 6
    assert all(item["source"] == "yahoo-reference" for item in payload["tradfiPerps"]["items"])
    assert payload["summary"]["etfCount"] >= 1
    assert payload["summary"]["cotCount"] == 5
    assert payload["summary"]["stablecoinCount"] == 1


def test_finance_external_sources_uses_etf_proxy_when_yahoo_empty():
    ctx = _ctx()
    ctx["get_yahoo_market_snapshot"] = lambda *args, **kwargs: None

    payload = finance_external_sources_service.build_finance_external_sources_payload(ctx)

    assert payload["sources"]["etfFlow"] == "proxy"
    assert payload["summary"]["etfCount"] == 2
    assert payload["etfFlow"]["items"][0]["source"] == "hyperliquid-etf-proxy"


def test_liquidity_regime_uses_external_seed_components():
    external = finance_external_sources_service.build_finance_external_sources_payload(_ctx())

    def get_cached_json(namespace, cache_key):
        if namespace == finance_external_sources_service.FINANCE_EXTERNAL_NAMESPACE:
            return external
        return None

    ctx = {
        "get_cached_json": get_cached_json,
        "get_snapshot_payload": lambda namespace, cache_key, builder, ttl_seconds=60: builder(),
        "get_market_groups_payload": lambda **kwargs: {
            "items": [
                {
                    "title": "When will Bitcoin hit $150k?",
                    "category": "crypto",
                    "volume24h": 100000,
                    "topOutcomes": [{"marketId": 1, "yesPrice": 0.25, "volume24h": 100000}],
                }
            ]
        },
        "get_yahoo_market_snapshot": lambda *args, **kwargs: {"price": 10, "changePercent": 1, "volume24h": 1000},
        "get_crypto_funding_watch_snapshot": lambda limit=8: {"assets": []},
        "utc_now_iso": lambda: "2026-05-19T00:00:00Z",
    }

    payload = finance_panels_service.get_finance_liquidity_regime_snapshot(ctx, limit=12)
    component_keys = {item["key"] for item in payload["components"]}
    sources = payload["sources"]

    assert {"cot", "etfFlow", "stablecoin"}.issubset(component_keys)
    assert sources["cot"] == "ok"
    assert sources["etf"] == "ok"
    assert sources["stablecoin"] == "ok"


def test_cold_liquidity_composition_never_nests_snapshot_refresh_permits():
    active = []
    def snapshot(namespace, key, builder, **kwargs):
        assert not active, f"nested admission: {active} -> {namespace}"
        assert namespace not in {"runtime:finance:liquidity-regime", "runtime:finance:onchain-tradfi-perp-radar"}
        active.append(namespace)
        try:
            return builder()
        finally:
            active.pop()
    ctx = {"get_snapshot_payload": snapshot, "get_market_groups_payload": lambda **kwargs: {"groups": []},
           "get_yahoo_market_snapshot": lambda *args, **kwargs: None,
           "utc_now_iso": lambda: "2026-11-04T08:00:00Z"}
    payload = finance_panels_service.get_finance_liquidity_regime_snapshot(ctx)
    assert "components" in payload


def test_okx_batches_real_tickers_and_does_not_invent_funding_or_notional():
    ctx = _ctx()
    calls = []
    ctx["http_json_get"] = lambda url, **kwargs: calls.append((url, kwargs)) or {"code": "0", "data": [
        {"instType": "SWAP", "instId": "XAU-USDT-SWAP", "last": "2200", "open24h": "2000",
         "volCcy24h": "123", "ts": "1793952000000"},
        {"instType": "SWAP", "instId": "BTC-USDT-SWAP", "last": "80000"},
    ]}
    source = finance_external_sources_service.fetch_okx_tradfi_perp_source(ctx)
    assert len(calls) == 1 and calls[0][1]["params"] == {"instType": "SWAP"}
    assert source["status"] == "partial" and source["availableInstrumentCount"] == 2
    assert "SPACEX-USDT-SWAP" in source["unsupportedSymbols"]
    assert source["failedSymbols"] == []
    item, = source["items"]
    assert item["lastPx"] == 2200 and item["changePercent"] == 10
    assert item["funding"] is None and item["markPx"] is None and item["spotPx"] is None
    assert item["dayNotional"] is None and item["volumeBase24h"] == 123
    assert item["sourceObservedAt"] == "2026-11-06T08:00:00Z"
    from api.services.finance_watch.markets import build_tradfi_perps_payload
    panel = build_tradfi_perps_payload(ctx, 24, {"tradfiPerps": source})
    assert panel["items"][0]["metric"] == 2200 and panel["items"][0]["metricUnit"] == "PRICE"


def test_okx_nonzero_api_code_is_not_an_unsupported_empty_catalog():
    ctx = _ctx()
    ctx["http_json_get"] = lambda *a, **kw: {"code": "50011", "data": []}
    with pytest.raises(ValueError, match="response invalid"):
        finance_external_sources_service.fetch_okx_tradfi_perp_source(ctx)
    ctx["http_json_get"] = lambda *a, **kw: {"code": "0", "data": []}
    with pytest.raises(ValueError, match="catalog missing"):
        finance_external_sources_service.fetch_okx_tradfi_perp_source(ctx)


def test_reference_futures_are_not_labeled_or_scored_as_perp_funding():
    source = finance_external_sources_service.fetch_reference_tradfi_perp_source(_ctx())
    assert all(row["instrumentType"] == "FUTURES_REFERENCE" for row in source["items"])
    assert all(row["display"].endswith("-FUTURES") for row in source["items"])
    assert all(row["funding"] is None and row["basisBps"] is None and row["dayNotional"] is None for row in source["items"])
    assert all(row["lastPx"] == 10 and row["changePercent"] == 2 for row in source["items"])


def _okx_metrics_fixture(monkeypatch):
    ctx = _ctx()
    now = '2026-11-06T16:00:00Z'
    ts = 1793980800000
    # Derive ms from the fixture's fixed UTC clock, not the test machine clock.
    from datetime import datetime
    ts = int(datetime.fromisoformat(now.replace('Z', '+00:00')).timestamp() * 1000)
    monkeypatch.setattr(finance_external_sources_service, 'utc_now_iso', lambda: now)
    data = {
        'tickers': [dict(instId='XAU-USDT-SWAP',instType='SWAP',last='2010',open24h='2000',vol24h='10000',volCcy24h='10',ts=str(ts))],
        'instrument': [dict(instId='XAU-USDT-SWAP',instType='SWAP',ctVal='0.001',ctMult='1',ctValCcy='XAU',ctType='linear',uly='XAU-USDT',settleCcy='USDT')],
        'mark': [dict(instId='XAU-USDT-SWAP',markPx='2001',ts=str(ts))],
        'index': [dict(instId='XAU-USDT',idxPx='2000',ts=str(ts-10000))],
        'openInterest': [dict(instId='XAU-USDT-SWAP',oi='500',oiCcy='.5',oiUsd='1000.5',ts=str(ts))],
        'funding': [dict(instId='XAU-USDT-SWAP',fundingRate='0',fundingTime=str(ts+3600000),nextFundingTime=str(ts+7200000),settFundingRate='-.0001',settState='settled',ts=str(ts))],
    }
    for field, key in [('instruments','instrument'),('mark_price','mark'),('index_tickers','index'),('open_interest','openInterest'),('funding_rate','funding')]:
        setattr(ctx['SETTINGS'], f'finance_okx_{field}_url', 'https://okx.test/'+key)
    calls = []
    def get(url, **kwargs):
        calls.append((url.rsplit('/',1)[-1], kwargs))
        rows = data[url.rsplit('/',1)[-1]]
        if isinstance(rows, Exception): raise rows
        return {'code':'0','data':rows}
    ctx['http_json_get'] = get
    return ctx, data, calls, now


def test_okx_real_metrics_units_clocks_and_batch_funding(monkeypatch):
    ctx, data, calls, now = _okx_metrics_fixture(monkeypatch)
    source = finance_external_sources_service.fetch_okx_tradfi_perp_source(ctx)
    row, = source['items']
    assert source['status'] == 'ok' and len(calls) == 6
    assert calls[-1][1]['params'] == {'instId':'ANY'}
    assert all(call[1]['timeout'] == 45 for call in calls)
    assert row['lastPx'] == 2010 and row['markPx'] == 2001 and row['oraclePx'] == 2000
    assert row['basisBps'] == pytest.approx(5)
    assert row['funding'] == 0 and row['fundingIntervalHours'] == 1
    assert row['openInterest'] == 500 and row['openInterestBase'] == .5 and row['openInterestUsd'] == 1000.5
    assert row['volumeNominal24h'] == 10 and row['volumeNominalCurrency'] == 'XAU'
    assert row['volumeMarkEquivalent24h'] == 20010 and row['quoteCurrency'] == 'USDT'
    assert row['dayNotional'] is None  # Current mark valuation is not traded USD turnover.
    assert row['metricObservedAt']['mark'] == now and row['metricObservedAt']['index'] != now
    from api.services.finance_watch.markets import build_tradfi_perps_payload
    panel = build_tradfi_perps_payload(ctx, 24, {'tradfiPerps':source})
    facts = {d['label']: d for d in panel['items'][0]['details']}
    assert facts['Funding forecast']['value'] == '0 % / 1h'
    assert facts['24h mark valuation']['value'] == '20,010 USDT'


def test_okx_missing_metric_keeps_original_clock_and_disables_derived_basis(monkeypatch):
    ctx, data, _, now = _okx_metrics_fixture(monkeypatch)
    old = finance_external_sources_service.fetch_okx_tradfi_perp_source(ctx)
    monkeypatch.setattr(finance_external_sources_service, 'read_finance_external_sources', lambda _: {'tradfiPerps':old})
    data['mark'] = OSError('offline')
    monkeypatch.setattr(finance_external_sources_service, 'utc_now_iso', lambda: '2026-11-06T16:01:00Z')
    row, = finance_external_sources_service.fetch_okx_tradfi_perp_source(ctx)['items']
    assert row['markPx'] == 2001 and row['metricStatus']['mark'] == 'stale'
    assert row['metricFetchedAt']['mark'] == now and row['metricObservedAt']['mark'] == now
    assert row['basisBps'] is None and row['volumeMarkEquivalent24h'] is None
    monkeypatch.setattr(finance_external_sources_service, 'utc_now_iso', lambda: '2026-11-06T16:31:00Z')
    expired, = finance_external_sources_service.fetch_okx_tradfi_perp_source(ctx)['items']
    assert expired['markPx'] is None and expired['metricStatus']['mark'] == 'unavailable'


def test_okx_unaligned_index_invalid_metadata_and_blank_funding_are_unknown(monkeypatch):
    ctx, data, _, _ = _okx_metrics_fixture(monkeypatch)
    data['index'][0]['ts'] = str(int(data['mark'][0]['ts']) - 180000)
    data['funding'][0]['fundingRate'] = ''
    source = finance_external_sources_service.fetch_okx_tradfi_perp_source(ctx)
    row, = source['items']
    assert row['basisBps'] is None and row['basisStatus'] == 'unaligned'
    assert row['funding'] is None and source['status'] == 'partial'
    data['instrument'][0]['ctVal'] = ''
    row, = finance_external_sources_service.fetch_okx_tradfi_perp_source(ctx)['items']
    assert row['volumeNominal24h'] is None and row['volumeMarkEquivalent24h'] is None


def test_cot_access_denial_stops_repeated_queries_and_preserves_error_status():
    ctx = _ctx()
    calls = []
    response = requests.Response()
    response.status_code = 403
    def denied(*args, **kwargs):
        calls.append(True)
        raise requests.HTTPError("private transport details", response=response)
    ctx["http_json_get"] = denied
    source = finance_external_sources_service.fetch_cot_source(ctx)
    assert calls == [True]
    assert source["status"] == "error" and source["items"] == []
    assert len(source["failedSymbols"]) == 5
    assert source["sourceErrors"]["ES"] == {"errorType": "HTTPError", "httpStatus": 403}
    assert "private transport" not in str(source)


def test_external_capture_preserves_read_times_and_expires_failed_rows(monkeypatch):
    now = "2026-11-06T14:00:00Z"
    monkeypatch.setattr(finance_external_sources_service, "utc_now_iso", lambda: now)
    ctx = _ctx()
    ctx["SNAPSHOT_STORE"] = SimpleNamespace(get_stale=lambda *a: {"generatedAt": "2026-11-06T13:50:00Z",
        "sourcePayloads": {"cot": {"items": [
            {"symbol": "ES", "fetchedAt": "2026-11-06T13:50:00Z", "reportDate": "2026-11-03"},
            {"symbol": "GC", "fetchedAt": "2026-11-06T13:29:00Z", "reportDate": "2026-11-03"},
        ]}}})
    original = ctx["http_json_get"]
    def get(url, **kwargs):
        if "cftc" in url:
            response = requests.Response(); response.status_code = 403
            raise requests.HTTPError(response=response)
        return original(url, **kwargs)
    ctx["http_json_get"] = get
    ctx["get_yahoo_market_snapshot"] = lambda *a, **kw: {"price": 10, "changePercent": 2, "fetchedAt": "2026-11-06T13:59:00Z", "quoteAt": "2026-11-06T13:58:00Z"}
    result = finance_external_sources_service.build_finance_external_sources_payload(ctx)
    row, = result["cot"]["items"]
    assert row["symbol"] == "ES" and row["retained"]
    assert row["fetchedAt"] == "2026-11-06T13:50:00Z" and row["reportDate"] == "2026-11-03"
    assert all(row["fetchedAt"] == "2026-11-06T13:59:00Z" for row in result["sourcePayloads"]["referenceTradfiPerps"]["items"])
    assert all(row["sourceObservedAt"] == "2026-11-06T13:58:00Z" for row in result["sourcePayloads"]["referenceTradfiPerps"]["items"])
    ctx.pop("SNAPSHOT_STORE")
    cold = finance_external_sources_service.build_finance_external_sources_payload(ctx)
    assert cold["cot"]["fetchedAt"] is None and cold["cot"]["items"] == []
