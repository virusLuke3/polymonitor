from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from api.services.crypto_strategy.contracts import basis, depth, option_bands, trade_sample
from api.services.crypto_strategy.providers import collect, references, venue_asset
from api.services.crypto_strategy.store import Store, get_snapshot, read_snapshot

NOW = 1793613600000


def test_trade_direction_duplicates_empty_and_negative_prices():
    rows = [dict(execId="1", price="100", size="2", time=NOW, side="Buy"),
            dict(execId="2", price="101", size="1", time=NOW+1, side="Sell")]
    data = trade_sample(rows + [rows[0], dict(rows[0], execId="bad", price="-1")], limit=60)
    assert (data["buy"], data["sell"], data["net"], data["count"]) == (200, 101, 99, 2)
    assert data["cvd"][-1]["v"] == 99
    assert data["coverage"] == "BOUNDED_SAMPLE"
    assert trade_sample([], limit=60)["net"] is None
    assert trade_sample(rows[:1], limit=60)["sell"] == 0
    assert basis(None, 100) is None


def test_depth_rejects_crossed_and_one_sided_book():
    assert depth({"b": [["101", "1"]], "a": [["100", "2"]]})["imbalance"] is None
    assert depth({"b": [["99", "1"]], "a": []})["imbalance"] is None
    assert depth({"b": [["99", "1"], []], "a": [["101", "1"]]})["imbalance"] == pytest.approx(-.01)


def test_options_use_two_sided_quotes_and_actual_instrument_expiry():
    instruments = {str(k): dict(option_type="call", strike=k, expiration_timestamp=NOW+86400000, quote_currency="BTC") for k in [90,110]}
    rows = [dict(instrument_name="90", bid_price=.20, ask_price=.22, underlying_price=100),
            dict(instrument_name="110", bid_price=.10, ask_price=.12, underlying_price=100)]
    data = option_bands(rows, instruments, NOW)
    assert data[0]["bands"][0]["probability"] == pytest.approx(.5)
    assert data[0]["bands"][0]["low"] == pytest.approx(.4)
    assert data[0]["bands"][0]["high"] == pytest.approx(.6)
    for key, value in [("ask_price", None), ("bid_price", .5), ("underlying_price", -100)]:
        broken = deepcopy(rows)
        broken[0][key] = value
        assert option_bands(broken, instruments, NOW) == []
    assert option_bands(rows, instruments, NOW+86400000) == []


def reference_fixture():
    market = dict(asset="BTC", market_id="123", condition_id="0xabc", slug="btc-updown-test", starts_at_ms=NOW-60000,
                  ends_at_ms=NOW+240000, outcomes={"UP":"123456"}, rule_version="twap60", rule_url="https://data.chain.link/streams/btc-usd-twap-60s-streams",
                  price_kind="twap", window_seconds=60, comparator=">=", anchor=dict(value="100", condition_id="0xabc"))
    price = dict(value="101", event_at_ms=NOW-1000, received_at_ms=NOW, feed_id="rtds:crypto_prices_twap_sixty:btc/usd",
                 price_kind="twap", window_seconds=60, quote_currency="USD", full_accuracy_value="101000000000000000000")
    return {"assets":{"BTC":{"market":market, "prices":[price], "quotes":{}}}}


def test_oracle_identity_future_staleness_and_anchor_binding():
    raw = reference_fixture()
    read = lambda: references(lambda *_: raw, "http://owned-reader", NOW)["BTC"]
    assert read()["status"] == "ok"
    assert read()["latest"]["full_accuracy_value"] == "101000000000000000000"
    raw["assets"]["BTC"]["market"]["anchor"]["condition_id"] = "other"
    assert read()["market"]["anchor"] is None
    raw["assets"]["BTC"]["prices"][0]["event_at_ms"] = NOW-60000
    assert read()["status"] == "stale"
    raw["assets"]["BTC"]["prices"][0]["event_at_ms"] = NOW+30000
    assert read()["latest"] == {}
    raw["assets"]["BTC"]["market"]["ends_at_ms"] = NOW
    assert read()["market"] is None


def test_basis_requires_aligned_clocks():
    def get(url, params):
        if url.endswith("tickers"):
            return {"retCode":0, "time": NOW if params["category"] == "spot" else NOW+10000,
                    "result":{"list":[dict(symbol="BTCUSDT",lastPrice="100",markPrice="101",indexPrice="100")]}}
        return {"retCode":0, "time":NOW, "result":{"list":[]}}
    row = venue_asset(get, "https://source", "BTC", NOW)
    assert row["basisBps"] is None
    assert row["premiumBps"] == pytest.approx(100)


def test_unavailable_reference_does_not_poison_other_source_containers():
    def get(*args, **kwargs):
        raise OSError("offline")
    data = collect(get, bybit_base="https://source", reference_url="http://owned-reader", now=NOW)
    assert set(data["references"]) == {"BTC","ETH","SOL","XRP"}
    assert data["references"]["BTC"]["status"] == "unavailable"
    assert data["assets"]["BTC"]["errors"]


def test_read_only_api_never_creates_storage_and_preserves_snapshot_age(tmp_path, monkeypatch):
    path = str(tmp_path / "strategy.db")
    assert get_snapshot(path)["status"] == "warming"
    assert not Path(path).exists()
    store = Store(path)
    store.sample("peg:USDC", NOW, 0)
    store.sample("peg:USDC", NOW+1, None)
    assert store.history("peg:USDC", NOW) == [{"t":NOW,"v":0}]
    store.publish({"collectedAt":NOW,"generatedAt":"2026-11-02T10:00:00Z","status":"partial"}, NOW)
    monkeypatch.setattr("time.time", lambda: (NOW+121000)/1000)
    result = get_snapshot(path)
    assert result["status"] == "stale"
    assert result["generatedAt"] == "2026-11-02T10:00:00Z"
    assert read_snapshot(path)["status"] == "partial"
    store.conn.close()


def test_native_book_reuse_requires_identity_continuity_and_unexpired_heartbeat(monkeypatch):
    from api.services.crypto_strategy.contracts import iso
    raw = reference_fixture()
    book = dict(tokenId="123456", bookStatus="live", continuity=True, bestBid=".4", bestAsk=".5",
                heartbeatAt=iso(NOW-1000), receivedAt=iso(NOW-2000), staleAfter=iso(NOW+10000))
    def get(url, params=None):
        return {"books":{"123456":{"source":"market-data","yes":book}}} if params else raw
    monkeypatch.setattr("time.time", lambda: NOW/1000)
    read = lambda: references(get,"http://reference",NOW,"http://existing-api")["BTC"]["quotes"]
    assert read()["UP"]["bid"] == .4
    book["continuity"] = False
    assert read() == {}
    book["continuity"] = True
    book["staleAfter"] = iso(NOW-1)
    assert read() == {}
