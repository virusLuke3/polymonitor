from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from runtime import official_disclosures_watcher as watcher


@pytest.mark.parametrize("redirect", [False, True])
def test_contact_identity_is_sec_only(monkeypatch, redirect):
    contact = "Polymonitor test-contact@example.invalid"
    sec_proxy = "socks5h://127.0.0.1:18992"
    monkeypatch.setenv("POLYDATA_SNAPSHOT_SQLITE_PATH", "unused")
    monkeypatch.setenv("POLYMONITOR_SEC_USER_AGENT", contact)
    monkeypatch.setenv("POLYMONITOR_DISCLOSURES_SEC_PROXY_URL", sec_proxy)
    monkeypatch.setattr(watcher, "SnapshotStore", lambda _: SimpleNamespace(fetch_lock=lambda *a, **kw: nullcontext()))
    monkeypatch.setattr(watcher, "WATCHLIST", {"AAPL": "0000320193"})
    monkeypatch.setattr(watcher, "publish", lambda _: None)
    monkeypatch.setattr(watcher.time, "sleep", lambda _: None)
    calls = []

    class Response:
        status_code = 302 if redirect else 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, _):
            assert not redirect, "Redirect response must not be parsed as source data"
            yield b'{"results": []}'

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    session = SimpleNamespace(get=get, close=lambda: None)
    monkeypatch.setattr(watcher, "source_session", lambda: session)

    def collect(store, key, url, parse, fetch, cadence):
        urls = [url]
        if key == "federal-register":
            urls += ["https://data.sec.gov.example.invalid/data", "https://example.invalid/?source=data.sec.gov"]
        for target in urls:
            if redirect:
                with pytest.raises(ValueError, match="redirected"):
                    fetch(target)
            else:
                assert fetch(target)["results"] == []
        return {}

    monkeypatch.setattr(watcher, "collect_source", collect)
    watcher.run()
    assert len(calls) == 6
    for index, (_, request) in enumerate(calls):
        is_sec = index >= 4
        assert request["headers"]["User-Agent"] == (contact if is_sec else "Polymonitor")
        assert request["proxies"] == {"http": sec_proxy if is_sec else "", "https": sec_proxy if is_sec else ""}
        assert request["allow_redirects"] is False
    assert session.trust_env is False
