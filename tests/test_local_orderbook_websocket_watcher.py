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
from api.services.lob_service import LocalOrderBookRuntimeManager
from runtime.local_orderbook_websocket_watcher import CoverageTarget, LocalOrderBookWebsocketWatcher, _iter_json_events


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.content = b"{}"

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self):
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        token_id = (params or {}).get("token_id")
        if token_id == "yes-token":
            return FakeResponse({"bids": [{"price": "0.40", "size": "10"}], "asks": [{"price": "0.42", "size": "10"}]})
        return FakeResponse({"bids": [{"price": "0.58", "size": "10"}], "asks": [{"price": "0.60", "size": "10"}]})


class FakeLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def exception(self, *args, **kwargs):
        return None


def _target_payload():
    return {
        "marketId": 42,
        "marketSlug": "sample-market",
        "marketTitle": "Bitcoin above 100k?",
        "yesTokenId": "yes-token",
        "noTokenId": "no-token",
        "topic": "crypto",
        "tier": "hot",
        "sampleIntervalSeconds": 15,
    }


def test_coverage_target_builds_token_identities():
    target = CoverageTarget.from_payload(_target_payload())

    assert target is not None
    yes, no = target.identities()
    assert yes.token_id == "yes-token"
    assert yes.outcome == "YES"
    assert no.token_id == "no-token"
    assert no.outcome_index == 1


def test_iter_json_events_accepts_single_and_list_payloads():
    assert list(_iter_json_events({"event_type": "book"})) == [{"event_type": "book"}]
    assert list(_iter_json_events([{"event_type": "book"}, "skip", {"event_type": "price_change"}])) == [
        {"event_type": "book"},
        {"event_type": "price_change"},
    ]


def test_watcher_applies_price_change_and_persists_sample(monkeypatch):
    manager = LocalOrderBookRuntimeManager(api_base="https://clob.test", session=FakeSession(), cache_ttl_seconds=30)
    ctx = {"LOB_RUNTIME_MANAGER": manager}
    watcher = LocalOrderBookWebsocketWatcher(ctx=ctx, ws_url="wss://example.test/ws", persist=True, logger=FakeLogger())
    target = CoverageTarget.from_payload(_target_payload())
    assert target is not None
    watcher.targets_by_market = {target.market_id: target}
    yes_identity, no_identity = target.identities()
    watcher.identities_by_token = {yes_identity.token_id: yes_identity, no_identity.token_id: no_identity}
    watcher.target_by_token = {yes_identity.token_id: target, no_identity.token_id: target}
    watcher.persist = False
    watcher.bootstrap_targets([target], force_refresh=True)
    watcher.persist = True
    persisted = []
    monkeypatch.setattr(
        lob_service,
        "persist_runtime_lob_payload",
        lambda ctx, payload, yes_token_id, no_token_id: persisted.append((payload, yes_token_id, no_token_id)),
    )
    watcher._last_persisted_at_by_market.clear()

    changed = watcher.handle_event(
        {
            "event_type": "price_change",
            "timestamp": "9999999999999",
            "price_changes": [{"asset_id": "yes-token", "side": "BUY", "price": "0.41", "size": "12"}],
        }
    )

    assert changed == 1
    assert persisted
    payload, yes_token_id, no_token_id = persisted[-1]
    assert yes_token_id == "yes-token"
    assert no_token_id == "no-token"
    assert payload["yes"]["bestBid"] == "0.41"
    assert payload["coverage"]["topic"] == "crypto"
