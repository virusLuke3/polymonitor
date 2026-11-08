import requests
import pytest

from api.clients import source_transport as transport


def test_full_attempt_does_not_shrink_backup_timeout(monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(transport.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(transport.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    def request(*args, **kwargs):
        calls.append(kwargs)
        clock[0] += 40
        raise requests.exceptions.ReadTimeout()
    monkeypatch.setattr(requests.Session, 'request', request)
    with transport.SourceSession() as session, pytest.raises(requests.exceptions.Timeout):
        transport.read_with_retry(session, 'https://source.example', lambda response: response.content,
            attempts=2, deadline=60, timeout=40, require_full_attempt=True)
    assert len(calls) == 1
    assert calls[0]['timeout'] == 40


def test_two_complete_attempts_fit_fred_budget(monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(transport.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(transport.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    def request(*args, **kwargs):
        calls.append(kwargs)
        clock[0] += 40
        if len(calls) == 1:
            raise requests.exceptions.ReadTimeout()
        return response()
    monkeypatch.setattr(requests.Session, 'request', request)
    with transport.SourceSession() as session:
        assert transport.read_with_retry(session, 'https://source.example', lambda response: response.content,
            attempts=2, deadline=90, timeout=40, require_full_attempt=True) == b'{}'
    assert [call['timeout'] for call in calls] == [40, 40]
    assert [call['proxies']['https'] for call in calls] == ['socks5h://first:1', 'socks5h://second:2']


@pytest.fixture(autouse=True)
def routes(monkeypatch):
    monkeypatch.setattr(transport, '_routes', lambda: {'source.example': ['socks5h://first:1', 'socks5h://second:2']})
    monkeypatch.delenv('POLYDATA_SNAPSHOT_SQLITE_PATH', raising=False)
    transport._COOLDOWNS.clear()
    transport._FAILURES.clear()


def response(status=200, **headers):
    result = requests.Response()
    result.status_code = status
    result.headers.update(headers)
    result._content = b'{}'
    return result


def test_connection_failure_switches_once_and_cools_failed_route(monkeypatch):
    calls = []
    def request(self, method, url, **kwargs):
        calls.append(kwargs)
        if kwargs['proxies']['https'].endswith('first:1'):
            raise requests.exceptions.ConnectTimeout()
        return response()
    monkeypatch.setattr(requests.Session, 'request', request)
    with transport.SourceSession() as session:
        assert session.get('https://source.example', timeout=10).status_code == 200
        assert session.get('https://source.example', timeout=10).status_code == 200
        assert session.get('https://source.example', timeout=10).status_code == 200
    assert len(calls) == 5
    assert calls[0]['timeout'].total == 10
    assert calls[-1]['proxies']['https'].endswith('second:2')


def test_rate_limit_does_not_switch_and_survives_session_replacement(monkeypatch):
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        return response(429, **{'Retry-After': '600'})
    monkeypatch.setattr(requests.Session, 'request', request)
    with transport.SourceSession() as session:
        assert session.get('https://source.example').status_code == 429
    with transport.SourceSession() as session, pytest.raises(requests.exceptions.RetryError):
        session.get('https://source.example')
    assert len(calls) == 1


@pytest.mark.parametrize('url,method,status', [
    ('https://source.example', 'GET', 403),
    ('http://127.0.0.1/internal', 'GET', 200),
    ('https://clob.polymarket.com/book', 'GET', 200),
    ('https://source.example', 'POST', 200),
])
def test_no_forbidden_fallback_or_internal_route(monkeypatch, url, method, status):
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        return response(status)
    monkeypatch.setattr(requests.Session, 'request', request)
    with transport.SourceSession() as session:
        assert session.request(method, url).status_code == status
    assert len(calls) == 1
    if status != 403:
        assert 'proxies' not in calls[0]


def test_success_clears_transient_route_failure(monkeypatch):
    monkeypatch.setattr(requests.Session, 'request', lambda *args, **kwargs: response())
    with transport.SourceSession() as session:
        session._route_failed('source.example:0')
        assert session.get('https://source.example').status_code == 200
        session._route_failed('source.example:0')
        assert session._due('source.example:0')
        session._route_failed('source.example:0')
        assert not session._due('source.example:0')
