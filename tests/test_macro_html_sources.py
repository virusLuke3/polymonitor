"""Calendar/nowcast transport, schema and last-good clock regressions."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import requests
from bs4 import BeautifulSoup

from api.services import bls_calendar, cpi_release_calendar_service, runtime_service
from runtime import cpi_release_calendar_watcher, inflation_nowcast_watcher
from test_cpi_release_calendar import make_context


def nowcast_html():
    result = ''
    for caption, period, values in [
        ('Inflation, month-over-month percent change', 'Month', ['November 2026', 'October 2026']),
        ('Inflation, year-over-year percent change', 'Month', ['November 2026', 'October 2026']),
        ('Quarterly annualized percent change', 'Quarter', ['2026:Q4']),
    ]:
        headers = ''.join(f'<th>{key}</th>' for key in [period, 'CPI', 'Core CPI', 'PCE', 'Core PCE', 'Updated'])
        rows = ''.join(f'<tr><td>{value}</td><td>0.19</td><td></td><td>0.25</td><td>0.26</td><td>11/05</td></tr>' for value in values)
        result += f'<table><caption>{caption}</caption><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody><tfoot><tr><td colspan="6">Published measures are blank.</td></tr></tfoot></table>'
    return result


class Response:
    encoding = 'utf-8'
    status_code = 200
    headers = {}

    def __init__(self, body):
        self.body = body.encode()

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        pass


def test_nowcast_valid_schema_preserves_periods_and_publisher_blank_cells():
    payload = runtime_service._parse_inflation_nowcast_html(nowcast_html(), BeautifulSoup)
    assert len(payload['monthlyPeriods']['monthOverMonth']) == 2
    assert payload['monthOverMonth']['Core CPI'] == ''
    assert payload['monthOverMonth']['Updated'] == '11/05'
    assert payload['quarterly'][0]['Quarter'] == '2026:Q4'


@pytest.mark.parametrize('body', [
    '<html>Request blocked</html>',
    '<table><tr><td>Nothing published</td></tr></table>',
    nowcast_html().replace('year-over-year percent change', 'unrecognized heading'),
    nowcast_html().replace('<th>CPI</th>', '<th>Other</th>'),
    nowcast_html().replace('0.19', 'NaN'),
    nowcast_html().replace('November 2026', 'No period'),
])
def test_nowcast_missing_or_invalid_tables_raise_instead_of_becoming_empty(body):
    with pytest.raises(ValueError):
        runtime_service._parse_inflation_nowcast_html(body, BeautifulSoup)


def test_nowcast_source_retries_body_failure_and_stamps_success_after_read(monkeypatch):
    completed = []
    responses = []

    class BrokenResponse(Response):
        def iter_content(self, chunk_size):
            raise requests.exceptions.ChunkedEncodingError('fixture')
            yield b''

    def request(method, url, **kwargs):
        assert method == 'GET' and kwargs['stream'] and 44 <= kwargs['timeout'] <= 45
        responses.append(url)
        completed.append(True)
        return BrokenResponse('') if len(responses) == 1 else Response(nowcast_html())

    def clock():
        assert len(responses) == 2
        return '2026-11-06T14:00:00Z'

    deps = SimpleNamespace(requests_lib=SimpleNamespace(request=request), beautiful_soup=BeautifulSoup,
                           settings=SimpleNamespace(cleveland_fed_nowcast_url='https://example.test/nowcast'), utc_now_iso=clock)
    monkeypatch.setattr(runtime_service, '_dependencies', lambda ctx: deps)
    monkeypatch.setattr('api.clients.source_transport.time.sleep', lambda seconds: None)
    payload = runtime_service.fetch_live_inflation_nowcast_payload({})
    assert payload['generatedAt'] == '2026-11-06T14:00:00Z'
    assert len(completed) == 2 and payload['status'] == 'ok'


def test_nowcast_source_failure_is_visible_to_last_good_owner(monkeypatch):
    deps = SimpleNamespace(requests_lib=object(), beautiful_soup=BeautifulSoup,
                           settings=SimpleNamespace(cleveland_fed_nowcast_url='https://example.test'))
    monkeypatch.setattr(runtime_service, '_dependencies', lambda ctx: deps)
    monkeypatch.setattr(runtime_service, 'read_with_retry', lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout('fixture')))
    with pytest.raises(requests.Timeout):
        runtime_service.fetch_live_inflation_nowcast_payload({})


def test_calendar_transport_keeps_full_attempt_and_body_retry_budget(monkeypatch):
    watcher = cpi_release_calendar_watcher.CpiReleaseCalendarWatcher.__new__(cpi_release_calendar_watcher.CpiReleaseCalendarWatcher)
    watcher.requests = object()

    def read(session, url, callback, **kwargs):
        assert session is watcher.requests
        assert kwargs['attempts'] == 2 and kwargs['timeout'] == 45 and kwargs['deadline'] == 190
        return callback(Response('<html>Calendar</html>'))

    monkeypatch.setattr(cpi_release_calendar_watcher.time, 'monotonic', lambda: 100.)
    monkeypatch.setattr(cpi_release_calendar_watcher, 'read_with_retry', read)
    assert watcher._http_text_get('https://example.test') == '<html>Calendar</html>'


def test_calendar_invalid_auxiliary_pages_report_source_errors():
    ctx = make_context()
    original = ctx['http_text_get']
    ctx['http_text_get'] = lambda url, **kwargs: '<html>Blocked</html>' if 'bea.example' in url or 'fed.example' in url else original(url, **kwargs)
    payload = cpi_release_calendar_service.build_cpi_release_calendar_payload(ctx)
    assert payload['sources']['beaPce'] == payload['sources']['fomc'] == 'error'
    assert set(payload['sourceErrors']) == {'beaPce', 'fomc'}
    assert payload['failedSources'] == ['beaPce', 'fomc']
    assert payload['freshCount'] == len(payload['items']) and payload['retainedCount'] == 0


def test_calendar_retained_items_do_not_advance_success_clock():
    previous = {'generatedAt': '2026-05-10T00:00:00Z', 'items': [
        {'id': 'cpi-2026-05-12', 'kind': 'cpi', 'releaseAt': '2026-05-12T12:30:00Z', 'verifiedAt': '2026-05-10T00:00:00Z'}]}
    store = SimpleNamespace(get_stale=lambda *args: previous)
    ctx = make_context(snapshot_store=store, http_text_get=lambda *a, **kw: (_ for _ in ()).throw(requests.Timeout('fixture')))
    payload = cpi_release_calendar_service.build_cpi_release_calendar_payload(ctx)
    assert payload['generatedAt'] == previous['generatedAt']
    assert payload['projectedAt'] == '2026-05-11T00:00:00Z'
    assert payload['items'][0]['verifiedAt'] == previous['items'][0]['verifiedAt']
    assert payload['freshCount'] == 0 and payload['retainedCount'] == 1
    assert len(payload['failedSources']) == 6


def test_calendar_verification_timestamp_uses_completed_source_read():
    from test_bls_replacement import fake_get
    rows, *_ = bls_calendar.build(fake_get, None, datetime(2026, 11, 4, tzinfo=timezone.utc),
                                 checked_at=lambda: '2026-11-04T00:00:45Z')
    assert all(row['verifiedAt'] == '2026-11-04T00:00:45Z' for row in rows)


def test_partial_calendar_keeps_other_verified_months_without_overriding_new_date():
    from test_bls_replacement import fred, nyfed
    old = [{**bls_calendar.parse_fred(fred(date=date), 'cpi', 2026)[0], 'verifiedAt': '2026-11-03T00:00:00Z'}
           for date in ['November 10, 2026', 'December 10, 2026']]

    def get(url, **kwargs):
        if url == bls_calendar.NYFED_URL:
            return nyfed(day=11)
        raise requests.Timeout('fixture')

    rows, states, *_ = bls_calendar.build(get, None, datetime(2026, 11, 4, tzinfo=timezone.utc), {'items': old})
    assert [row['releaseAt'] for row in rows] == ['2026-11-11T13:30:00Z', '2026-12-10T13:30:00Z']
    assert rows[1]['retained'] and rows[1]['verifiedAt'] == old[1]['verifiedAt']
    assert states['fredCpi'] == 'error' and states['cpiSchedule'] == 'ok'
    expired, *_ = bls_calendar.build(get, None, datetime(2026, 11, 12, tzinfo=timezone.utc), {'items': old})
    assert len(expired) == 1 and not expired[0].get('retained')


@pytest.mark.parametrize('module, klass', [
    (cpi_release_calendar_watcher, 'CpiReleaseCalendarWatcher'),
    (inflation_nowcast_watcher, 'InflationNowcastWatcher'),
])
def test_macro_owner_constructs_source_session(module, klass, monkeypatch, tmp_path):
    session = SimpleNamespace(headers={})
    calls = []
    monkeypatch.setattr(module, 'source_session', lambda **kwargs: calls.append(kwargs) or session)
    watcher = getattr(module, klass)(redis_url='', redis_prefix='', snapshot_sqlite_path=str(tmp_path / 'snap.sqlite'), settings=SimpleNamespace())
    assert watcher.requests is session and session.trust_env is False
    assert calls == [{'requests_lib': module.requests}]
