import json
from copy import deepcopy

import pytest

from scripts.api.services.bookmaker_panels.moviodds import parse, project
from scripts.api.services.bookmaker_panels.snapshot_service import merge_exact_events


def sample():
    return {'matches': [{'id': '10', 'sport': 'esports', 'league': 'LOL - Example',
        'home': 'Alpha', 'away': 'Beta', 'kickoff_utc': '2026-11-10T18:00:00Z',
        'in_play': False, 'polled_at': '2026-11-10T12:00:00Z',
        'group_status': {'1510001': {'polled_at': '2026-11-10T12:00:00Z'}},
        'quotes': [dict(fixture_id='10', group_id='1510001', group_name='Match Lines',
            market_id='winner', sel_id=sel, side=side, line='To Win', odds_dec=price,
            label=None, ts='2026-11-09T22:00:00Z') for sel, side, price in [('99', 'Beta', 3), ('12', 'Alpha', 1.5)]]}]}


def read(raw):
    return parse(json.dumps(raw), 'esports')


def test_missing_label_uses_explicit_side_not_array_or_selection_order():
    row = read(sample())['fixtures'][0]
    assert row['sport'] == 'lol'
    quote = row['quotes'][0]
    assert [(o['name'], o['decimal']) for o in quote['outcomes']] == [('Beta', 3), ('Alpha', 1.5)]
    assert quote['sourceUpdatedAt'] == '2026-11-09T22:00:00+00:00'
    assert quote['sourceCheckedAt'] == '2026-11-10T12:00:00+00:00'
    assert quote['selectionIds'] == ['99', '12']


def test_unknown_direction_cannot_be_guessed_from_id():
    raw = sample()
    raw['matches'][0]['quotes'][0].pop('side')
    assert not read(raw)['fixtures']


def test_fixture_poll_cannot_renew_unknown_market_clock():
    raw = sample()
    raw['matches'][0].pop('group_status')
    assert read(raw)['fixtures'][0]['quotes'][0]['sourceCheckedAt'] is None


@pytest.mark.parametrize('fraction,expected', [('355481677', '355481'), ('1', '100000'), ('12345', '123450')])
def test_native_subsecond_clocks_survive_on_collector_python(fraction, expected):
    raw = sample()
    stamp = f'2026-11-10T12:00:00.{fraction}Z'
    raw['matches'][0]['group_status']['1510001']['polled_at'] = stamp
    for q in raw['matches'][0]['quotes']:
        q['ts'] = stamp
    quote = read(raw)['fixtures'][0]['quotes'][0]
    assert quote['sourceCheckedAt'] == f'2026-11-10T12:00:00.{expected}+00:00'
    assert quote['sourceUpdatedAt'] == f'2026-11-10T12:00:00.{expected}+00:00'


def test_suspension_stale_and_phase_survive_normalization():
    raw = sample()
    raw['matches'][0]['quotes'][0]['suspended'] = True
    raw['matches'][0]['group_status']['1510001']['stale'] = True
    q = read(raw)['fixtures'][0]['quotes'][0]
    assert q['suspended'] and q['sourceStale'] and q['phase'] == 'prematch'


def test_maps_and_mixed_lines_cannot_form_a_series_price():
    raw = sample()
    raw['matches'][0]['quotes'][0]['period'] = '1'
    assert not read(raw)['fixtures']
    raw = sample()
    for q, line in zip(raw['matches'][0]['quotes'], ('-1.5', '+2.5')):
        q.update(line='Handicap', handicap=line)
    assert not read(raw)['fixtures']


def test_duplicate_selections_and_mixed_fixtures_are_rejected():
    raw = sample()
    raw['matches'][0]['quotes'][1]['sel_id'] = '99'
    assert not read(raw)['fixtures']
    raw = sample()
    raw['matches'][0]['quotes'][0]['fixture_id'] = '11'
    assert not read(raw)['fixtures']


def test_warming_and_malformed_response_do_not_erase_success():
    for raw in [{'warming': True, 'matches': []}, {'error': 'unauthorized'}, {'matches': None}]:
        with pytest.raises(ValueError):
            read(raw)
    assert read({'matches': []})['fixtures'] == []


def test_virtual_basketball_is_not_nba():
    assert project('basketball', 'NBA') == 'nba'
    assert project('basketball', 'Ebasketball H2H GG League - 4x5mins') is None
    assert project('basketball', 'NCAAB') == 'basketball'
    assert project('esports', 'VALORANT - Example') == 'valorant'
    assert project('esports', 'Unknown game') is None


@pytest.mark.parametrize('sport,group,title,line', [
    ('rugby_union', '80007', 'Game', 'To Win'), ('rugby_league', '190006', 'Game', 'To Win'),
    ('cricket', '1246', 'To Win the Match', ''), ('australian_rules', '360005', 'Game', 'To Win'),
    ('table_tennis', '920000', 'To Win Match', 'To Win'), ('volleyball', '910000', 'Winner', 'Winner'),
    ('handball', '780001', 'Game', 'To Win'), ('badminton', '940002', 'Match Lines', 'To Win'),
    ('boxing', '148', 'To Win Fight', ''), ('mma', '1620232', 'Fight Lines', 'To Win'),
    ('darts', '703', 'Match Winner', ''), ('snooker', '952', 'To Win', 'To Win'),
    ('bandy', '890000', 'To Win', 'To Win'), ('floorball', '900134', 'To Win', 'To Win'),
    ('gaelic_sports', '750036', 'To Win', 'To Win'),
])
def test_additional_verified_match_groups_preserve_direction_and_clock(sport, group, title, line):
    raw = sample()
    row = raw['matches'][0]
    row.update(sport=sport, league='Real competition', group_status={group: {'polled_at': '2026-11-11T08:00:00Z'}})
    for q in row['quotes']:
        q.update(group_id=group, group_name=title, line=line)
    parsed = parse(json.dumps(raw), sport)
    assert len(parsed['fixtures']) == 1
    assert parsed['fixtures'][0]['sport'] == sport
    assert parsed['fixtures'][0]['quotes'][0]['sourceCheckedAt'] == '2026-11-11T08:00:00+00:00'
    row['quotes'][0]['period'] = '1'
    assert not parse(json.dumps(raw), sport)['fixtures']


def test_draw_missing_from_explicit_three_way_market_is_not_two_way():
    raw = sample()
    row = raw['matches'][0]
    row.update(sport='cricket', league='Test Match')
    for q in row['quotes']:
        q.update(group_id='30155', group_name='Match Winner (Incl. Draw)', line='')
    assert not parse(json.dumps(raw), 'cricket')['fixtures']


def test_recent_confirmation_supersedes_old_price_even_if_price_did_not_move():
    old = read(sample())['fixtures'][0]
    old['quotes'][0]['sourceCheckedAt'] = None
    old['quotes'][0]['sourceUpdatedAt'] = '2026-11-10T11:00:00Z'
    new = read(sample())['fixtures'][0]
    new['id'] = 'other:10'
    merged = merge_exact_events([old, new])
    assert len(merged[0]['quotes']) == 1
    assert merged[0]['quotes'][0]['sourceCheckedAt'] == '2026-11-10T12:00:00+00:00'


def test_three_way_soccer_keeps_draw():
    raw = sample()
    row = raw['matches'][0]
    row.update(sport='soccer', league='Example League', group_status={'40': {'polled_at': '2026-11-10T12:00:00Z'}})
    for q in row['quotes']:
        q.update(group_id='40', group_name='Full Time Result', line='')
    draw = deepcopy(row['quotes'][0])
    draw.update(sel_id='100', side='Draw', odds_dec=4)
    row['quotes'].append(draw)
    quote = parse(json.dumps(raw), 'soccer')['fixtures'][0]['quotes'][0]
    assert len(quote['outcomes']) == 3
    assert sum(o['probability'] for o in quote['outcomes']) == pytest.approx(1)
