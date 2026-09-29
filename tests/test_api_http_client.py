from __future__ import annotations


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
        self.closed = False

    def get(self, url: str, **_kwargs):
        self.calls.append(url)
        return FakeResponse()

    def close(self) -> None:
        self.closed = True


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


def test_http_sessions_are_owned_by_the_application_and_closed(monkeypatch):
    from api.runtime import ServiceRuntime
    from api import bindings

    requests_lib = FakeRequests()
    monkeypatch.setattr(bindings, "requests", requests_lib)
    first, second = ServiceRuntime(), ServiceRuntime()
    try:
        for runtime in (first, second):
            assert runtime.market_context["http_json_get"]("https://example.test/data") == {}
        assert len(requests_lib.sessions) == 2
        first.close()
        assert requests_lib.sessions[0].closed
        assert not requests_lib.sessions[1].closed
    finally:
        first.close()
        second.close()
    assert all(session.closed for session in requests_lib.sessions)
