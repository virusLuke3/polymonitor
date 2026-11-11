import json
import pytest

from scripts.api.services.bookmaker_panels import public_books as p
from scripts.api.services.bookmaker_panels.model import book_key, book_category


def test_fanduel_direction_and_unknown_price_clock():
    e = {'eventId': 1, 'competitionId': 10, 'name': 'Away @ Home', 'openDate': '2026-11-10T02:00:00Z'}
    def runner(label, side, price):
        return {'runnerName': label, 'result': {'type': side}, 'runnerStatus': 'ACTIVE',
                'winRunnerOdds': {'trueOdds': {'decimalOdds': {'decimalOdds': price}}}}
    m = {'eventId': 1, 'marketType': 'MONEY_LINE', 'marketStatus': 'OPEN',
         'marketTime': e['openDate'], 'runners': [runner('Away', 'AWAY', 2.2), runner('Home', 'HOME', 1.8)]}
    raw = {'attachments': {'events': {'1': e}, 'markets': {'1': m}, 'competitions': {'10': {'name': 'NBA'}}}}
    row = p.parse_fanduel(json.dumps(raw), 'nba')['fixtures'][0]
    assert row['home'] == 'Home'
    q = row['quotes'][0]
    assert q['sourceUpdatedAt'] is None  # marketTime is kickoff, not price time.
    assert q['outcomes'][0]['name'] == 'Away'
    m['runners'][0]['result']['type'] = 'HOME'
    with pytest.raises(ValueError):
        p.parse_fanduel(json.dumps(raw), 'nba')


def test_fanduel_landing_page_does_not_turn_simulated_basketball_into_nba():
    from copy import deepcopy
    e = {'eventId': 1, 'competitionId': 10, 'name': 'Boston Celtics @ Toronto Raptors', 'openDate': '2026-11-11T02:00:00Z'}
    def market(event_id, away, home):
        return {'eventId': event_id, 'marketType': 'MONEY_LINE', 'marketStatus': 'OPEN',
            'runners': [{'runnerName': team, 'result': {'type': side}, 'runnerStatus': 'ACTIVE',
                        'winRunnerOdds': {'trueOdds': {'decimalOdds': {'decimalOdds': 1.9}}}}
                       for team, side in ((away, 'AWAY'), (home, 'HOME'))]}
    raw = {'attachments': {'events': {'1': e, '2': {**e, 'eventId': 2, 'competitionId': 11,
        'name': 'Boston Celtics (EXO) @ Toronto Raptors (PLAYER)'}},
        'competitions': {'10': {'name': 'NBA'}, '11': {'name': 'eBasketball H2H GG League 4x5 Mins'}},
        'markets': {'1': market(1, 'Boston Celtics', 'Toronto Raptors'),
                    '2': market(2, 'Boston Celtics (EXO)', 'Toronto Raptors (PLAYER)')}}}
    result = p.parse_fanduel(json.dumps(raw), 'nba')
    assert len(result['fixtures']) == 1
    assert result['fixtures'][0]['away'] == 'Boston Celtics'
    no_real = deepcopy(raw)
    del no_real['attachments']['events']['1']
    assert p.parse_fanduel(json.dumps(no_real), 'nba')['fixtures'] == []
    del raw['attachments']['competitions']
    with pytest.raises(ValueError):
        p.parse_fanduel(json.dumps(raw), 'nba')


def test_kambi_line_scaling_suspension_and_oldest_outcome_clock():
    raw = {'events': [{'event': {'id': 1, 'homeName': 'H', 'awayName': 'A', 'start': '2026-11-11T01:00:00Z'},
        'betOffers': [{'criterion': {'label': 'Point Spread', 'lifetime': 'FULL_TIME_OVERTIME'},
            'suspended': True, 'outcomes': [
                {'participant': 'H', 'odds': 1900, 'line': -1500, 'status': 'OPEN', 'changedDate': '2026-11-10T01:01:00Z'},
                {'participant': 'A', 'odds': 2000, 'line': 1500, 'status': 'OPEN', 'changedDate': '2026-11-10T01:00:00Z'}]}]}]}
    q = p.parse_betrivers(json.dumps(raw), 'nba')['fixtures'][0]['quotes'][0]
    assert q['suspended'] and q['sourceUpdatedAt'] == '2026-11-10T01:00:00+00:00'
    assert q['outcomes'][0]['decimal'] == 1.9 and q['outcomes'][0]['point'] == -1.5
    raw['events'][0]['betOffers'][0]['criterion']['lifetime'] = 'FIRST_HALF'
    assert not p.parse_betrivers(json.dumps(raw), 'nba')['fixtures']


def test_pinnodds_year_uses_source_anchor_and_does_not_forge_price_clock():
    html = '''<script type="application/ld+json">{"@type":"WebPage","dateModified":"2026-12-31T23:50:00Z"}</script>
    <table><tbody><tr><td class="ev"><b>Blue <i>v</i> Red</b><small>League of Legends - Cup</small></td>
    <td class="when">Fri 01 Jan 01:00 UTC</td><td data-l="Moneyline"><span>1.8</span><span>2.1</span></td>
    </tr></tbody></table>'''
    row = p.parse_pinnodds(html, 'esports')['fixtures'][0]
    assert row['sport'] == 'lol' and row['startTime'].startswith('2027-01-01')
    assert row['quotes'][0]['sourceUpdatedAt'] is None
    assert row['idKind'] == 'derived-exact'
    with pytest.raises(ValueError):
        p.parse_pinnodds(html.replace('Fri 01 Jan', 'Mon 01 Mar'), 'esports')


def test_portal_pairs_same_book_not_each_sides_best_price():
    positions = [{'16': {'odds': [1.8]}, '43': {'odds': [1.9]}},
                 {'16': {'odds': {'1': 2.1}}, '43': {'odds': {'1': 2.0}}}]
    part = {'scopeId': 1, 'bettingTypeId': 3, 'active': True, 'positionsWithProviders': positions}
    props = {'rows': [{'id': 2, 'cols': '1|2', 'event-stage-name': 'Scheduled', 'encodeEventId': 'a',
        'home-name': 'H', 'away-name': 'A', 'date-start-timestamp': 1794358800, 'tournament-name': 'NBA'}],
        'initialOddsMap': {'a': {'odds': [part, part]}}}
    html = '<script>self.__next_f.push(' + json.dumps([1, 'x:' + json.dumps(props, separators=(',', ':'))]) + ')</script>'
    result = p.parse_oddsportal(html, 'nba', {'16': 'bet365'})
    assert result['unknownBookmakerIds'] == ['43']
    q = result['fixtures'][0]['quotes'][0]
    assert [o['decimal'] for o in q['outcomes']] == [1.8, 2.1]
    assert q['sourceUpdatedAt'] is None


def test_public_book_aliases_do_not_inflate_company_count():
    assert book_key('Stake.com') == book_key('stake')
    assert book_key('GG.BET') == book_key('GGBET')
    assert book_category('Betfair Exchange') == 'exchange'
