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
        self.options = []

    def get(self, url: str, **_kwargs):
        self.calls.append(url)
        self.options.append(_kwargs)
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


def test_explicit_provider_proxy_also_applies_to_an_existing_session(monkeypatch):
    monkeypatch.setenv("POLYDATA_API_HTTP_PROXY_URL", "socks5h://127.0.0.1:18991")
    monkeypatch.delenv("POLYDATA_API_HTTP_TRUST_ENV_PROXY", raising=False)
    session = FakeSession()
    assert http_client.http_json_get({"requests": session}, "https://example.test/data") == {}
    assert session.trust_env is False
    assert session.options[0]["proxies"] == {
        "http": "socks5h://127.0.0.1:18991", "https": "socks5h://127.0.0.1:18991",
    }


def test_provider_proxy_does_not_route_local_services_through_the_remote_host(monkeypatch):
    monkeypatch.setenv("POLYDATA_API_HTTP_PROXY_URL", "socks5h://127.0.0.1:18991")
    monkeypatch.delenv("POLYDATA_API_HTTP_TRUST_ENV_PROXY", raising=False)
    for host in ("localhost", "127.0.0.1", "[::1]"):
        session = FakeSession()
        http_client.http_json_get({"requests": session}, f"http://{host}:18861/health")
        assert "proxies" not in session.options[0]
        assert session.trust_env is False


def test_existing_session_honors_explicit_environment_proxy_opt_in(monkeypatch):
    monkeypatch.setenv("POLYDATA_API_HTTP_TRUST_ENV_PROXY", "true")
    session = FakeSession()
    session.trust_env = False
    http_client.http_json_get({"requests": session}, "https://example.test/data")
    assert session.trust_env is True


def test_http_sessions_are_owned_by_the_application_and_closed(monkeypatch):
    from api.runtime import ServiceRuntime
    from api import bindings

    requests_lib = FakeRequests()
    monkeypatch.setattr(bindings, "requests", requests_lib)
    first, second = ServiceRuntime(), ServiceRuntime()
    try:
        for runtime in (first, second):
            assert runtime.global_transport_shipping_context["http_json_get"]("https://example.test/data") == {}
        assert len(requests_lib.sessions) == 2
        first.close()
        assert requests_lib.sessions[0].closed
        assert not requests_lib.sessions[1].closed
    finally:
        first.close()
        second.close()
    assert all(session.closed for session in requests_lib.sessions)
