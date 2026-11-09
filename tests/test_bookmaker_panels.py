import json
import pytest

from scripts.api.services.bookmaker_panels.model import decimal, parse_board, parse_the_odds
from scripts.api.services.bookmaker_panels.snapshot_service import specs, read_board
from scripts.api.services.panel_evidence_store import collect_one, read_source, NAMESPACE
from scripts.runtime.snapshot_store import SnapshotStore


def raw_fixture(outcomes=None, market='h2h'):
    return {'id': 'test', 'sport_key': 'soccer', 'home_team': 'Red', 'away_team': 'Blue',
        'commence_time': '2026-11-10T18:00:00Z', 'bookmakers': [{'key': 'pinnacle', 'title': 'Pinnacle',
        'last_update': '2026-11-09T10:00:00Z', 'kind': 'sportsbook', 'markets': {market: outcomes or [
            {'name': 'Red', 'price': 150}, {'name': 'Blue', 'price': 200}, {'name': 'Draw', 'price': 250}]}}]}


def body(row):
    return json.dumps({'sport_key': 'soccer', 'fixtures': [row]}).encode()


def test_three_way_winner_keeps_draw_and_removes_margin_per_book():
    q = parse_board(body(raw_fixture()), 'soccer')['fixtures'][0]['quotes'][0]
    assert [o['name'] for o in q['outcomes']] == ['Red', 'Blue', 'Draw']
    assert sum(o['probability'] for o in q['outcomes']) == pytest.approx(1)
    assert q['outcomes'][0]['probability'] == pytest.approx((1/2.5) / (1/2.5 + 1/3 + 1/3.5))
    assert q['sourceUpdatedAt'] == '2026-11-09T10:00:00+00:00'


@pytest.mark.parametrize('value', [True, False, 0, 99, -50, float('inf'), float('nan'), 110.5])
def test_reject_invalid_american_price(value):
    with pytest.raises(ValueError):
        decimal(value)


def test_negative_american_and_decimal_modes():
    assert decimal(-200) == 1.5
    assert decimal(150) == 2.5
    assert decimal(1.91, False) == 1.91


@pytest.mark.parametrize('market,rows', [
    ('totals', [{'name': 'Over', 'price': -110, 'point': 2.5}, {'name': 'Under', 'price': -110, 'point': 3.5}]),
    ('spreads', [{'name': 'Red', 'price': -110, 'point': -1.5}, {'name': 'Blue', 'price': -110, 'point': 2.5}]),
    ('h2h', [{'name': 'Red', 'price': -110}]),
    ('h2h', [{'name': 'Red', 'price': -110}, {'name': 'Other team', 'price': -110}]),
])
def test_incomplete_or_mixed_line_is_not_publishable(market, rows):
    with pytest.raises(ValueError):
        parse_board(body(raw_fixture(rows, market)), 'soccer')


def test_prediction_market_is_not_a_sportsbook_and_secret_link_removed():
    row = raw_fixture()
    row['bookmakers'][0].update(key='polymarket', kind='sportsbook', link='https://user:password@example.test/market')
    q = parse_board(body(row), 'soccer')['fixtures'][0]['quotes'][0]
    assert q['category'] == 'prediction_market'
    assert q['url'] is None


def test_unknown_clock_remains_unknown():
    row = raw_fixture()
    row['bookmakers'][0].pop('last_update')
    assert parse_board(body(row), 'soccer')['fixtures'][0]['quotes'][0]['sourceUpdatedAt'] is None


def test_exchange_is_not_counted_as_bookmaker_when_aggregator_omits_kind():
    row = raw_fixture()
    row['bookmakers'][0].update(key='sx.bet')
    row['bookmakers'][0].pop('kind')
    assert parse_board(body(row), 'soccer')['fixtures'][0]['quotes'][0]['category'] == 'exchange'


def test_wrong_board_and_corrupt_empty_rejected():
    for raw in [{'error': 'unavailable'}, {'sport_key': 'lol', 'fixtures': []}, {'sport_key': 'soccer', 'fixtures': None}]:
        with pytest.raises(ValueError):
            parse_board(json.dumps(raw), 'soccer')
    assert parse_board(b'{"sport_key":"soccer","fixtures":[]}', 'soccer')['fixtures'] == []


def test_the_odds_retains_all_bookmakers_without_another_request():
    row = raw_fixture()
    row['bookmakers'][0]['markets'] = [{'key': 'h2h', 'outcomes': [
        {'name': 'Red', 'price': 1.8}, {'name': 'Blue', 'price': 2.1}]}]
    row['bookmakers'] *= 8
    parsed = parse_the_odds(json.dumps([row]))
    assert len(parsed['fixtures'][0]['quotes']) == 8
    assert parsed['fixtures'][0]['provider'] == 'the-odds-api'


def test_durable_failure_preserves_clock_and_expires_at_retention(tmp_path, monkeypatch):
    monkeypatch.setenv('POLYMONITOR_EXTERNAL_EVIDENCE_SQLITE_PATH', str(tmp_path/'evidence.sqlite3'))
    monkeypatch.setenv('POLYDATA_ODDSLINK_PUBLIC_BOARD_URL', 'https://example.test/{sport}')
    store = SnapshotStore(str(tmp_path/'snapshots.sqlite3'))
    spec = next(s for s in specs() if ':soccer:' in s.key)
    raw = body(raw_fixture())
    collect_one(store, spec, acquire=lambda: (raw, spec.parse(raw)), now=1000)
    def failure():
        raise TimeoutError('failed')
    failed = collect_one(store, spec, acquire=failure, now=2000)
    assert failed['lastSuccessAt'] == 1000
    assert failed['data']['fixtures']
    assert read_source(store, spec, now=2900)[1]['stale']
    assert not read_source(store, spec, now=8201)[0]
    # The original good payload survives a process restart.
    again = SnapshotStore(str(tmp_path/'snapshots.sqlite3'))
    assert again.get_stale(NAMESPACE, spec.key)['lastSuccessAt'] == 1000


def test_empty_success_replaces_prior_fixtures_and_not_due_makes_no_call(tmp_path, monkeypatch):
    monkeypatch.setenv('POLYMONITOR_EXTERNAL_EVIDENCE_SQLITE_PATH', str(tmp_path/'evidence.sqlite3'))
    store = SnapshotStore(str(tmp_path/'snapshots.sqlite3'))
    spec = next(s for s in specs() if ':soccer:' in s.key)
    raw = body(raw_fixture())
    collect_one(store, spec, acquire=lambda: (raw, spec.parse(raw)), now=1000)
    def no_call():
        pytest.fail('Not-due sources must not perform HTTP')
    collect_one(store, spec, acquire=no_call, now=1100)
    empty = b'{"sport_key":"soccer","fixtures":[]}'
    result = collect_one(store, spec, acquire=lambda: (empty, spec.parse(empty)), now=2000)
    assert result['data']['fixtures'] == []
    assert result['lastSuccessAt'] == 2000


def test_public_projection_never_fetches(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.api.services.bookmaker_panels.snapshot_service.fetch_bytes', lambda *a, **k: pytest.fail('API attempted upstream I/O'))
    result = read_board(SnapshotStore(str(tmp_path/'snapshots.sqlite3')), True)
    assert result['fixtures'] == []
    assert result['generatedAt'] is None


def test_guest_quota_is_shared_across_different_snapshot_stores(tmp_path, monkeypatch):
    from scripts.api.services.bookmaker_panels.budget import reserve_guest
    monkeypatch.setenv('POLYDATA_BOOKMAKER_QUOTA_SQLITE_PATH', str(tmp_path/'budget.sqlite3'))
    research = SnapshotStore(str(tmp_path/'research.sqlite3'))
    production = SnapshotStore(str(tmp_path/'production.sqlite3'))
    for index in range(5):
        assert reserve_guest(research if index % 2 else production)
    assert not reserve_guest(research)
    assert not reserve_guest(production)


def test_multiple_providers_do_not_count_the_same_book_twice():
    from copy import deepcopy
    from scripts.api.services.bookmaker_panels.snapshot_service import merge_exact_events
    first = parse_board(body(raw_fixture()), 'soccer')['fixtures'][0]
    other = deepcopy(first)
    other['id'] = 'another-provider:id'
    other['provider'] = 'the-odds-api'
    other['quotes'][0]['sourceUpdatedAt'] = '2026-11-09T11:00:00+00:00'
    combined = merge_exact_events([first, other])
    assert len(combined) == 1
    assert len(combined[0]['quotes']) == 1
    assert combined[0]['quotes'][0]['sourceUpdatedAt'] == '2026-11-09T11:00:00+00:00'
    other['startTime'] = '2026-11-11T18:00:00+00:00'
    assert len(merge_exact_events([first, other])) == 2
