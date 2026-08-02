from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from api.clients import http_client


class FakeResponse:
    content = b"{}"

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {}


class FakeSession:
    def __init__(self) -> None:
        self.trust_env = True
        self.calls: list[str] = []

    def get(self, url: str, **_kwargs):
        self.calls.append(url)
        return FakeResponse()

    def close(self) -> None:
        return None


class FakeRequests:
    def __init__(self) -> None:
        self.sessions: list[FakeSession] = []

    def Session(self):
        session = FakeSession()
        self.sessions.append(session)
        return session


def test_http_json_get_reuses_a_session_within_the_current_worker_thread(monkeypatch) -> None:
    requests_lib = FakeRequests()
    monkeypatch.delenv("POLYDATA_API_HTTP_TRUST_ENV_PROXY", raising=False)
    context = {"requests": requests_lib}

    assert http_client.http_json_get(context, "https://example.test/one") == {}
    assert http_client.http_json_get(context, "https://example.test/two") == {}

    assert len(requests_lib.sessions) == 1
    assert requests_lib.sessions[0].calls == ["https://example.test/one", "https://example.test/two"]
    assert requests_lib.sessions[0].trust_env is False
