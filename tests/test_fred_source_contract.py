from types import SimpleNamespace
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from api.services.finance_watch import sentiment
from api.clients import fred_csv, source_transport
from runtime.food_retail_basket_watcher import FoodRetailBasketWatcher
from runtime.macro_cpi_panels_watcher import MacroCpiPanelsWatcher


def test_fred_reads_requested_series_and_dates_without_using_other_columns():
    calls = []

    def read(url, **kwargs):
        calls.append((url, kwargs))
        return (
            '\ufeffDATE,OTHER,DGS10\n2026-11-04,99,"4.90"\n'
            '2026-11-03,88,4.95\n2026-11-05,77,.\n'
            'not-a-date,66,1\n2026-11-06,55,inf\n'
        )

    ctx = {
        "SETTINGS": SimpleNamespace(finance_fred_csv_url_template="https://fred.example/series?id={series_id}&cosd=2025-01-01"),
        "http_text_get": read,
    }
    assert sentiment._fetch_fred_observations(ctx, "DGS10") == [
        {"date": "2026-11-03", "value": 4.95},
        {"date": "2026-11-04", "value": 4.9},
    ]
    assert parse_qs(urlsplit(calls[0][0]).query)["cosd"] == ["2025-01-01"]
    assert calls[0][1]["headers"]["Accept"] == "text/csv"


def test_fred_rejects_an_html_success_response_without_injecting_dynamic_date_query():
    calls = []
    ctx = {
        "SETTINGS": SimpleNamespace(finance_fred_csv_url_template="https://fred.example/series?id={series_id}"),
        "http_text_get": lambda url, **kwargs: calls.append(url) or "<html>upstream failure</html>",
    }
    with pytest.raises(ValueError, match="CSV schema mismatch"):
        sentiment._fetch_fred_observations(ctx, "DGS10")
    assert "cosd" not in parse_qs(urlsplit(calls[0]).query)


def test_fear_greed_reports_fred_failure_without_losing_other_sources(monkeypatch):
    monkeypatch.setattr(sentiment, "_http_json_get", lambda *a, **k: {"data": [{"value": "50"}]})
    monkeypatch.setattr(sentiment, "_fetch_cnn_fng", lambda *a: None)
    monkeypatch.setattr(sentiment, "_fetch_aaii_sentiment", lambda *a: None)
    monkeypatch.setattr(sentiment, "_fetch_barchart_last_price", lambda *a: None)
    monkeypatch.setattr(sentiment, "_fetch_yahoo_closes", lambda *a, **k: {})
    monkeypatch.setattr(sentiment, "_fetch_yahoo_snapshot", lambda *a, **k: {})

    def unavailable(*args):
        raise requests.ReadTimeout("private transport details must not be published")

    monkeypatch.setattr(sentiment, "_fetch_fred_observations", unavailable)
    result = sentiment.build_fear_greed_payload({"SETTINGS": SimpleNamespace()}, 24)
    assert result["summary"]["cryptoScore"] == 50
    assert result["sources"]["alternativeMe"] == "ok"
    assert result["sources"]["fred.DGS10"] == "error"
    assert result["errors"]["fred.DGS10"] == "ReadTimeout"
    assert result["sourceDetails"]["fred.DGS10"]["sourceObservedAt"] is None
    assert result["sourceDetails"]["fred.DGS10"]["sourceFetchedAt"] is None
    assert result["status"] == "partial"
    assert "private transport" not in str(result)


def test_fear_greed_keeps_fred_observation_and_fetch_clocks_separate(monkeypatch):
    monkeypatch.setattr(sentiment, "_http_json_get", lambda *a, **k: {"data": [{"value": "50"}]})
    monkeypatch.setattr(sentiment, "_fetch_cnn_fng", lambda *a: None)
    monkeypatch.setattr(sentiment, "_fetch_aaii_sentiment", lambda *a: None)
    monkeypatch.setattr(sentiment, "_fetch_barchart_last_price", lambda *a: None)
    monkeypatch.setattr(sentiment, "_fetch_yahoo_closes", lambda *a, **k: {})
    monkeypatch.setattr(sentiment, "_fetch_yahoo_snapshot", lambda *a, **k: {})
    monkeypatch.setattr(sentiment, "_fetch_fred_observations", lambda *a: [
        {"date": "2026-11-03", "value": 4.95}, {"date": "2026-11-04", "value": 4.9},
    ])
    monkeypatch.setattr(sentiment, "utc_now_iso", lambda: "2026-11-06T13:50:00Z")

    result = sentiment.build_fear_greed_payload({"SETTINGS": SimpleNamespace()}, 24)

    detail = result["sourceDetails"]["fred.DGS10"]
    assert detail == {
        "seriesId": "DGS10", "status": "ok", "value": 4.9,
        "sourceObservedAt": "2026-11-04", "sourceFetchedAt": "2026-11-06T13:50:00Z",
        "sourcePublishedAt": None, "observationCount": 2,
    }
    assert result["sourceDetails"]["fred.VIXCLS"]["sourceObservedAt"] == "2026-11-04"
    assert result["errors"] == {}


def test_cnn_uses_the_owner_http_helper_and_preserves_zero_score_and_source_time(monkeypatch):
    calls = []
    monkeypatch.setattr(sentiment, "utc_now_iso", lambda: "2026-11-06T13:55:00Z")
    context = {"SETTINGS": SimpleNamespace(finance_cnn_fng_url="https://cnn.example/fng",
        finance_cnn_fng_referer_url="https://cnn.example/markets"),
        "http_json_get": lambda url, **kwargs: calls.append((url, kwargs)) or {
            "fear_and_greed": {"score": 0, "rating": "extreme fear", "timestamp": "2026-11-05T16:00:00-05:00"}}}
    reading = sentiment._fetch_cnn_fng(context)
    assert len(calls) == 1 and calls[0][0] == "https://cnn.example/fng"
    assert reading["score"] == 0
    assert reading["sourceObservedAt"] == "2026-11-05T21:00:00Z"
    assert reading["sourceFetchedAt"] == "2026-11-06T13:55:00Z"


def test_sentiment_does_not_report_http_denial_or_bad_schema_as_empty(monkeypatch):
    response = requests.Response()
    response.status_code = 403
    def denied(*a, **k):
        raise requests.HTTPError("private proxy must not be published", response=response)
    monkeypatch.setattr(sentiment, "_fetch_aaii_sentiment", denied)
    monkeypatch.setattr(sentiment, "_fetch_cnn_fng", lambda *a: (_ for _ in ()).throw(ValueError("schema")))
    monkeypatch.setattr(sentiment, "_fetch_barchart_last_price", lambda *a: None)
    monkeypatch.setattr(sentiment, "_fetch_yahoo_closes", lambda *a, **k: {})
    monkeypatch.setattr(sentiment, "_fetch_yahoo_snapshot", lambda *a, **k: {})
    monkeypatch.setattr(sentiment, "_fetch_fred_observations", lambda *a: [])
    context = {"SETTINGS": SimpleNamespace(), "http_json_get": lambda *a, **k: {"data": [{"value": 50}]}}
    result = sentiment.build_fear_greed_payload(context, 24)
    assert result["sources"]["aaii"] == "error" and result["sources"]["cnn"] == "error"
    assert result["sourceDetails"]["aaii"]["httpStatus"] == 403
    assert result["sourceDetails"]["aaii"]["sourceObservedAt"] is None
    assert result["errors"]["cnn"] == "ValueError"
    assert "private proxy" not in str(result)


def test_aaii_invalid_proportions_raise_instead_of_returning_empty():
    context = {"SETTINGS": SimpleNamespace(finance_aaii_sentiment_url="https://aaii.example/survey"),
        "http_text_get": lambda *a, **k: '<html>Access denied</html>'}
    with pytest.raises(ValueError, match="proportions"):
        sentiment._fetch_aaii_sentiment(context)


@pytest.mark.parametrize("watcher_type", [MacroCpiPanelsWatcher, FoodRetailBasketWatcher])
def test_macro_http_preserves_the_provider_attempt_budget(watcher_type):
    calls = []
    watcher = watcher_type.__new__(watcher_type)
    response = SimpleNamespace(status_code=200, raise_for_status=lambda: None,
        iter_content=lambda chunk_size: iter([b"DATE,DGS10\n2026-11-04,4.90"]), close=lambda: None)
    watcher.requests = SimpleNamespace(request=lambda method, url, **kwargs: calls.append(kwargs) or response)
    watcher._http_text_get("https://fred.example/series", timeout=30)
    assert calls[0]["timeout"] == 30


def test_shared_fred_window_filters_locally_and_preserves_original_dates():
    calls = []
    text = "DATE,DGS10\n2021-12-31,1\n2022-01-01,2\n2026-11-04,4.9\n2026-11-05,.\n"
    rows = fred_csv.fetch_fred_observations(
        lambda url, **kwargs: calls.append(url) or text,
        "https://fred.example/series?id=DGS10", "DGS10", lookback_years=4,
        now=datetime(2026, 11, 6, tzinfo=timezone.utc),
    )
    assert calls == ["https://fred.example/series?id=DGS10"]
    assert rows == [{"date": "2022-01-01", "value": 2.0}, {"date": "2026-11-04", "value": 4.9}]


def test_shared_fred_transport_retries_body_once_and_closes_responses(monkeypatch):
    calls, closed = [], []
    monkeypatch.setattr(source_transport.time, "sleep", lambda seconds: None)

    class Response:
        status_code = 200
        def __init__(self, fail):
            self.fail = fail
        def raise_for_status(self):
            pass
        def iter_content(self, chunk_size):
            if self.fail:
                raise requests.ReadTimeout("body timed out")
            yield b"DATE,DGS10\n2026-11-04,4.9\n"
        def close(self):
            closed.append(self.fail)

    def request(method, url, **kwargs):
        calls.append(kwargs)
        return Response(len(calls) == 1)

    result = fred_csv.read_fred_text(SimpleNamespace(request=request), "https://fred.example/series")
    assert result.endswith("2026-11-04,4.9\n")
    assert len(calls) == 2 and closed == [True, False]
    assert all(call["stream"] and call["timeout"] <= 45 for call in calls)


def test_shared_fred_transport_rejects_oversized_body_without_retry():
    calls, closed = [], []
    response = SimpleNamespace(status_code=200, raise_for_status=lambda: None,
        iter_content=lambda chunk_size: iter([b"x" * (fred_csv.MAX_CSV_BYTES + 1)]),
        close=lambda: closed.append(True))
    session = SimpleNamespace(request=lambda *args, **kwargs: calls.append(True) or response)
    with pytest.raises(ValueError, match="SOURCE_RESPONSE_TOO_LARGE"):
        fred_csv.read_fred_text(session, "https://fred.example/series")
    assert calls == [True] and closed == [True]
