from datetime import datetime, timedelta, timezone

from scripts.api.services.weather_book_quote import project_weather_book

NOW = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)


def payload(**patch):
    return {"yes": {"tokenId": "1", "bookStatus": "available", "upstreamReady": True,
                    "observedAt": NOW.isoformat(), "eventAt": (NOW - timedelta(minutes=10)).isoformat(),
                    "bestBid": 0, "bestAsk": .1, **patch}}


def test_native_snapshot_is_not_live_and_preserves_source_clock():
    result = project_weather_book(payload(), "1", now=NOW)
    assert result["bookStatus"] == "snapshot"
    assert result["bids"] == [{"price": 0}]
    assert result["quoteUpdatedAt"] == payload()["yes"]["eventAt"]
    assert result["quoteStaleAfter"] == (NOW + timedelta(seconds=30)).isoformat()


def test_unready_is_retained_and_reader_time_cannot_extend_retention():
    value = payload(upstreamReady=False)
    assert project_weather_book(value, "1", now=NOW)["bookStatus"] == "retained"
    value["yes"]["observedAt"] = (NOW + timedelta(hours=3)).isoformat()
    assert not project_weather_book(value, "1", now=NOW + timedelta(hours=3))["bids"]
    assert not project_weather_book(payload(upstreamReady=False, eventAt=None), "1", now=NOW)["bids"]


def test_identity_crossed_future_and_one_sided_books():
    assert not project_weather_book(payload(), "2", now=NOW)["bids"]
    assert project_weather_book(payload(bestBid=.5), "1", now=NOW)["bookStatus"] == "invalid"
    assert not project_weather_book(payload(upstreamReady=False, eventAt=(NOW + timedelta(seconds=1)).isoformat()), "1", now=NOW)["bids"]
    assert project_weather_book(payload(bestAsk=None), "1", now=NOW)["asks"] == []
    assert project_weather_book(payload(bestAsk=None, bestBid=None), "1", now=NOW)["bookStatus"] == "no-book"


def test_only_continuous_books_use_live_deadline():
    value = payload(bookStatus="live", continuity=True, receivedAt=NOW.isoformat(), heartbeatAt=NOW.isoformat(), staleAfter=(NOW + timedelta(seconds=10)).isoformat())
    assert project_weather_book(value, "1", now=NOW)["bookStatus"] == "ok"
    assert project_weather_book(value, "1", now=NOW + timedelta(seconds=11))["bookStatus"] == "retained"
