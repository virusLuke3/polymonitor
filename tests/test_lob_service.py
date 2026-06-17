from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from api.services import lob_service
from api.services.lob_service import LocalOrderBookRuntimeManager, _book_side_summary


def test_book_side_summary_sorts_levels_and_computes_notional_depth():
    summary = _book_side_summary({
        "bids": [
            {"price": "0.04", "size": "100"},
            {"price": "0.07", "size": "50"},
        ],
        "asks": [
            {"price": "0.98", "size": "10"},
            {"price": "0.81", "size": "20"},
        ],
    })

    assert summary["bids"][0]["price"] == "0.07"
    assert summary["asks"][0]["price"] == "0.81"
    assert summary["bestBid"] == "0.07"
    assert summary["bestAsk"] == "0.81"
    assert summary["spread"] == "0.74"
    assert summary["mid"] == "0.44"
    assert summary["bidDepth"] == "7.50"
    assert summary["askDepth"] == "26.00"
    assert summary["depthTotal"] == "33.50"
    assert summary["imbalance"].startswith("0.223880")


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"{}"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, payloads):
        self.payloads = payloads
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        token_id = (params or {}).get("token_id")
        self.calls.append((url, token_id, timeout))
        payload = self.payloads.get(token_id)
        if payload is None:
            return FakeResponse({"bids": [], "asks": []}, status_code=404)
        return FakeResponse(payload)


def test_local_orderbook_runtime_manager_feeds_rest_book_into_registry():
    session = FakeSession({
        "yes-token": {
            "bids": [{"price": "0.184", "size": "25549.68"}],
            "asks": [{"price": "0.185", "size": "15090.41"}],
        },
        "no-token": {
            "bids": [{"price": "0.815", "size": "100"}],
            "asks": [{"price": "0.816", "size": "200"}],
        },
    })
    manager = LocalOrderBookRuntimeManager(api_base="https://clob.test", session=session, cache_ttl_seconds=30)

    payload = manager.get_market_snapshot(
        market_id=42,
        yes_token_id="yes-token",
        no_token_id="no-token",
        market_title="Sample market",
        condition_id="0xcondition",
    )

    assert payload["source"] == "local-orderbook"
    assert payload["runtimeModel"] == "LocalOrderBook"
    assert payload["bookStatus"] == "ok"
    assert payload["yes"]["bestBid"] == "0.184"
    assert payload["yes"]["bestAsk"] == "0.185"
    assert payload["yes"]["statePayload"]["snapshot_source"] == "rest-book"
    assert payload["yes"]["statePayload"]["runtime_model"] == "LocalOrderBook"
    assert manager.registry.get("yes-token").snapshot_payload(depth_levels=12)["best_bid"] == "0.184"


def test_token_lob_payload_persists_state_machine_payload(monkeypatch):
    session = FakeSession({
        "yes-token": {
            "bids": [{"price": "0.40", "size": "10"}],
            "asks": [{"price": "0.41", "size": "12"}],
        }
    })
    manager = LocalOrderBookRuntimeManager(api_base="https://clob.test", session=session, cache_ttl_seconds=30)
    persisted = []

    monkeypatch.setattr(
        lob_service,
        "_persist_orderbook_snapshots",
        lambda ctx, payload, yes_token_id, no_token_id: persisted.append((payload, yes_token_id, no_token_id)),
    )

    class FakeLogger:
        def exception(self, *args, **kwargs):
            raise AssertionError(args)

    ctx = {"LOB_RUNTIME_MANAGER": manager, "app": type("FakeApp", (), {"logger": FakeLogger()})()}

    payload = lob_service.get_runtime_lob_by_token_payload(ctx, "yes-token", market_title="Token mode")

    assert payload["yes"]["bestBid"] == "0.4"
    assert persisted
    persisted_payload, yes_token_id, no_token_id = persisted[0]
    assert yes_token_id == "yes-token"
    assert no_token_id == ""
    assert persisted_payload["yes"]["statePayload"]["source"] == "local-orderbook"
    assert persisted_payload["yes"]["statePayload"]["snapshot_version"]
