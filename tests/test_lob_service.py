"""The panel reads the live engine and never collects or persists order books."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import requests

from api.services import lob_service


def side(token="123", status="live"):
    now = datetime.now(timezone.utc)
    return {
        "tokenId": token,
        "bookStatus": status,
        "continuity": True,
        "receivedAt": (now - timedelta(minutes=2)).isoformat(),
        "heartbeatAt": (now - timedelta(seconds=1)).isoformat(),
        "staleAfter": (now + timedelta(seconds=19)).isoformat(),
        "bids": [{"price": "0.4", "size": "10"}],
        "asks": [{"price": "0.5", "size": "20"}],
    }


def engine(monkeypatch, payload=None, error=None):
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            assert url.endswith("/book/123")
            assert self.trust_env is False
            if error:
                raise error
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)

    monkeypatch.setattr(lob_service.requests, "Session", Session)


def test_live_source_preserves_receive_time_without_database_or_cache(monkeypatch):
    yes = side()
    engine(
        monkeypatch,
        {"source": "market-data", "runtimeModel": "websocket-live", "yes": yes, "no": side("", "unavailable")},
    )
    result = lob_service.get_runtime_lob_by_token_payload("123", market_id=42)
    assert result["bookStatus"] == "live"
    assert result["fetchedAt"] == yes["receivedAt"]
    assert result["yes"]["heartbeatAt"] == yes["heartbeatAt"]
    assert result["marketId"] == 42


@pytest.mark.parametrize("fault", ["heartbeat", "continuity", "identity", "deadline", "missing-received"])
def test_stale_or_wrong_identity_cannot_be_live(monkeypatch, fault):
    yes = side()
    if fault == "heartbeat":
        yes["heartbeatAt"] = yes["receivedAt"]
    if fault == "continuity":
        yes["continuity"] = False
    if fault == "identity":
        yes["tokenId"] = "999"
    if fault == "deadline":
        yes["staleAfter"] = yes["receivedAt"]
    if fault == "missing-received":
        yes.pop("receivedAt")
    engine(
        monkeypatch,
        {"source": "market-data", "runtimeModel": "websocket-live", "yes": yes, "no": side("", "unavailable")},
    )
    assert lob_service.get_runtime_lob_by_token_payload("123")["bookStatus"] in {"stale", "unavailable"}


def test_source_outage_returns_explicit_unavailable_without_rest_fallback(monkeypatch):
    engine(monkeypatch, error=requests.ConnectionError("down"))
    result = lob_service.get_runtime_lob_by_token_payload("123")
    assert result["bookStatus"] == "unavailable"
    assert result["yes"]["bids"] == []
    assert "fetchedAt" not in result


def test_both_outcomes_required_for_pair_live(monkeypatch):
    engine(
        monkeypatch,
        {"source": "market-data", "runtimeModel": "websocket-live", "yes": side(), "no": side("456", "warming")},
    )
    result = lob_service.get_runtime_lob_by_token_payload("123", no_token_id="456")
    assert result["bookStatus"] == "warming"
    assert result["yes"]["bookStatus"] == "live"


def test_token_path_validated_before_upstream_request():
    assert lob_service.get_runtime_lob_by_token_payload("../health")["_status"] == 400


def test_retired_history_endpoint_does_not_query_legacy_database():
    from flask import Flask
    from api.routes.lob import LobRouteDependencies, create_lob_blueprint

    def unexpected(*args, **kwargs):
        raise AssertionError("retired history performed a live or legacy read")

    app = Flask(__name__)
    app.register_blueprint(create_lob_blueprint(LobRouteDependencies(unexpected, unexpected)))
    response = app.test_client().get("/runtime/lob/token/123/snapshots")
    assert response.status_code == 410
    assert response.get_json()["code"] == "lob_history_retired"
    assert response.headers["Cache-Control"] == "no-store"
