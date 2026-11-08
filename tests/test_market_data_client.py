from __future__ import annotations

import unittest
import json
import pytest
from types import SimpleNamespace


from api.clients import market_data_client


class FakeResponse:
    content = b"{}"

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        yield json.dumps(self.payload).encode()

    def close(self):
        pass


class FakeRequests:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *args, **kwargs):
        return FakeResponse(self.payload)


def make_chart_payload(*, symbol: str, current: float, previous: float, closes: list[float]):
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": symbol,
                        "regularMarketPrice": current,
                        "chartPreviousClose": previous,
                        "currency": "USD",
                        "regularMarketVolume": 1000,
                    },
                    "timestamp": [1714700000 + index * 1800 for index in range(len(closes))],
                    "indicators": {"quote": [{"close": closes}]},
                }
            ]
        }
    }


def make_context(payload):
    return {
        "SETTINGS": SimpleNamespace(yahoo_chart_base_url="https://example.test/chart"),
        "FINANCE_RUNTIME_TTL_SECONDS": 300,
        "requests": FakeRequests(payload),
        "_safe_float": lambda value: None if value in (None, "") else float(value),
        "get_cached_runtime_payload": lambda namespace, cache_key: None,
        "set_cached_runtime_payload": lambda namespace, cache_key, payload, ttl_seconds: payload,
    }


def nasdaq_summary(symbol="TSM", cap="1,957,905,601,260"):
    return {"data": {"symbol": symbol, "assetClass": "STOCKS", "summaryData": {
        "MarketCap": {"label": "Market Cap", "value": cap},
        "Exchange": {"label": "Exchange", "value": "NYSE"}}}, "status": {"rCode": 200}}


def test_nasdaq_market_cap_reads_provider_value_with_independent_clock(monkeypatch):
    monkeypatch.setenv("POLYDATA_NASDAQ_STOCK_SUMMARY_URL_TEMPLATE", "https://example.test/{symbol}/summary")
    ctx = make_context(nasdaq_summary())
    stored = {}
    ctx["get_cached_runtime_payload"] = lambda ns, key: stored.get((ns, key))
    ctx["set_cached_runtime_payload"] = lambda ns, key, value, ttl_seconds: stored.setdefault((ns, key), value)
    value = market_data_client.get_nasdaq_market_cap(ctx, "TSM")
    assert value["marketCap"] == 1_957_905_601_260
    assert value["marketCapSource"] == "nasdaq-stock-summary"
    assert value["marketCapSymbol"] == "TSM"
    assert value["marketCapCurrency"] == "USD"
    assert value["marketCapQuoteAt"] is None
    assert value["marketCapFetchedAt"]
    assert value["marketCapReference"] == {"assetClass": "STOCKS", "exchange": "NYSE"}
    assert market_data_client.get_nasdaq_market_cap(ctx, "TSM") is value


@pytest.mark.parametrize("symbol,cap", [("SAP", "123"), ("TSM", "N/A"), ("TSM", "0"),
                                          ("TSM", "-1"), ("TSM", "NaN"), ("TSM", "1,23")])
def test_nasdaq_market_cap_rejects_wrong_identity_or_invalid_amount(monkeypatch, symbol, cap):
    monkeypatch.setenv("POLYDATA_NASDAQ_STOCK_SUMMARY_URL_TEMPLATE", "https://example.test/{symbol}/summary")
    with pytest.raises(ValueError):
        market_data_client.get_nasdaq_market_cap(make_context(nasdaq_summary(symbol, cap)), "TSM")


def test_nasdaq_market_cap_missing_configuration_makes_no_request(monkeypatch):
    monkeypatch.delenv("POLYDATA_NASDAQ_STOCK_SUMMARY_URL_TEMPLATE", raising=False)
    assert market_data_client.get_nasdaq_market_cap({}, "NVDA") is None


class MarketDataClientTestCase(unittest.TestCase):
    def test_yahoo_snapshot_falls_back_when_previous_close_scale_is_incompatible(self):
        payload = make_chart_payload(symbol="ZR=F", current=12.455, previous=1250.0, closes=[12.5, 12.455])

        snapshot = market_data_client.get_yahoo_market_snapshot(make_context(payload), "ZR=F")

        self.assertEqual(12.455, snapshot["price"])
        self.assertEqual(-0.36, snapshot["changePercent"])

    def test_yahoo_snapshot_uses_previous_close_when_scale_is_compatible(self):
        payload = make_chart_payload(symbol="GC=F", current=4353.9, previous=4475.2, closes=[4546.1, 4353.9])

        snapshot = market_data_client.get_yahoo_market_snapshot(make_context(payload), "GC=F")

        self.assertEqual(4353.9, snapshot["price"])
        self.assertEqual(-2.71, snapshot["changePercent"])


def test_yahoo_body_failure_retries_complete_request_within_owner_deadline(monkeypatch):
    from unittest.mock import Mock
    import requests
    from api.clients import source_transport
    from api.context import RuntimeResources

    payload = make_chart_payload(symbol="NVDA", current=100, previous=95, closes=[95, 100])
    first, second = FakeResponse(payload), FakeResponse(payload)
    first.status_code = second.status_code = 200
    first.headers = second.headers = {}
    def interrupted(chunk_size):
        yield b'{"chart":'
        raise requests.exceptions.ChunkedEncodingError("upstream closed response")
    first.iter_content = interrupted
    first.close, second.close = Mock(), Mock()
    session = SimpleNamespace(request=Mock(side_effect=[first, second]), close=Mock())
    ctx = make_context(payload)
    resources = RuntimeResources()
    ctx.update(requests=SimpleNamespace(Session=lambda: session), _resources=resources,
               external_source_deadline=110.)
    monkeypatch.setattr(market_data_client.time, "monotonic", lambda: 10.)
    monkeypatch.setattr(source_transport.time, "sleep", lambda seconds: None)
    try:
        result = market_data_client.get_yahoo_market_snapshot(ctx, "NVDA", ttl_seconds=5)
        assert result["price"] == 100
        assert session.request.call_count == 2
        assert all(call.kwargs["timeout"] == 45 for call in session.request.call_args_list)
        assert all(call.kwargs["stream"] for call in session.request.call_args_list)
        assert first.close.called and second.close.called
    finally:
        resources.close()


def test_yahoo_uses_remaining_owner_budget_and_exposes_bounded_body(monkeypatch):
    from unittest.mock import Mock
    getter = Mock(return_value={})
    ctx = make_context({})
    ctx["external_source_deadline"] = 25.
    monkeypatch.setattr(market_data_client.time, "monotonic", lambda: 10.)
    monkeypatch.setattr(market_data_client, "http_json_get", getter)
    assert market_data_client.get_yahoo_market_snapshot(ctx, "^IXIC") is None
    options = getter.call_args.kwargs
    assert options["retry_deadline"] == 25.
    assert options["max_response_bytes"] == 2_500_000
    assert options["retry_attempts"] == 2


@pytest.mark.parametrize("status", [403, 429])
def test_yahoo_source_denial_is_not_retried(monkeypatch, status):
    from unittest.mock import Mock
    import requests
    from api.context import RuntimeResources

    response = requests.Response()
    response.status_code = status
    response.headers["Retry-After"] = "300"
    response._content = b'{}'
    response._content_consumed = True
    session = SimpleNamespace(request=Mock(return_value=response), close=Mock())
    resources = RuntimeResources()
    ctx = make_context({})
    ctx.update(requests=SimpleNamespace(Session=lambda: session), _resources=resources)
    try:
        with pytest.raises(requests.HTTPError):
            market_data_client.get_yahoo_market_snapshot(ctx, "NVDA", ttl_seconds=5)
        session.request.assert_called_once()
    finally:
        resources.close()
