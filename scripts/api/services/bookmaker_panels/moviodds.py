"""bet365 mirror: explicit directions, whole-match markets and independent clocks."""
from __future__ import annotations

from functools import partial
import json
import re
from urllib.parse import urlencode

from api.services.panel_evidence_store import SourceSpec, fetch_bytes
from data_sources import source_value
from .model import fixture, instant, name, number

# Provider market taxonomy, not endpoint/key defaults. These are whole-match
# groups; map, period and player markets must not enter the winner consensus.
GROUPS = {
    'soccer': ('40', '1777'), 'basketball': ('1453', '112'),
    'tennis': ('83', '67'), 'american_football': ('1441', '58'),
    'ice_hockey': ('972', '96'), 'baseball': ('1096',),
    'esports': ('1510001',),
}


def specs():
    if not source_value('POLYDATA_MOVIODDS_BASE_URL'):
        return []
    return [SourceSpec(f'bookmakers:movi:{sport}:v1', f'bet365 via MoviOdds · {sport}',
        'POLYDATA_MOVIODDS_BASE_URL', partial(parse, sport=sport),
        cadence=300, stale_after=600, retain_for=1800) for sport in GROUPS]


def acquire(spec, deadline):
    sport = spec.key.split(':')[2]
    url = source_value(spec.url_env).rstrip('/') + '/odds?' + urlencode({
        'sport': sport, 'groups': ','.join(GROUPS[sport]), 'stats': '1'})
    token = source_value('POLYDATA_MOVIODDS_API_KEY')
    headers = {'Accept': 'application/json', 'Accept-Encoding': 'gzip'}
    if token:
        headers['X-API-Key'] = token
    raw = fetch_bytes(url, deadline=deadline, timeout=45, max_bytes=spec.max_bytes, headers=headers)
    return raw, spec.parse(raw)


def project(sport, league):
    if re.search(r'\b(e-?soccer|e-?basketball|simulated|virtual)\b', league, re.I):
        return None
    if sport == 'esports':
        prefix = re.split(r'\s+-\s+', league, maxsplit=1)[0].strip().casefold()
        return {'lol': 'lol', 'league of legends': 'lol', 'valorant': 'valorant',
                'cs2': 'cs2', 'counter-strike 2': 'cs2', 'dota2': 'dota2',
                'dota 2': 'dota2', 'r6': 'r6', 'rainbow six': 'r6'}.get(prefix)
    if sport == 'basketball':
        return 'nba' if league.casefold() == 'nba' else 'basketball'
    if sport == 'american_football':
        return 'nfl' if league.casefold() == 'nfl' else 'american_football'
    if sport == 'ice_hockey':
        return 'nhl' if league.casefold() == 'nhl' else 'ice_hockey'
    if sport == 'baseball':
        return 'mlb' if league.casefold() == 'mlb' else 'baseball'
    return sport


def _selection(q, row, sport):
    group = str(q.get('group_id', ''))
    if group not in GROUPS[sport] or q.get('period') not in (None, '', '0', 'full'):
        return None
    line = str(q.get('line') or '').strip().casefold()
    title = str(q.get('group_name') or '').strip().casefold()
    if title not in {'game', 'match lines', 'full time result', 'fulltime result', 'to win match'}:
        return None
    label = q.get('side') or q.get('label')
    if not isinstance(label, str) or not label.strip():
        return None
    team = next((row[k] for k in ('home', 'away') if name(label) == name(row[k])), None)
    if line in ('to win', ''):
        label = team or ('Draw' if name(label) in ('draw', 'tie') else None)
        kind, point = 'h2h', None
    elif line in ('line', 'handicap', 'puck line', 'run line'):
        label, kind, point = team, 'spreads', number(q.get('handicap'))
    elif line in ('total', 'total maps'):
        label = {'over': 'Over', 'under': 'Under'}.get(name(label))
        kind, point = 'totals', number(q.get('handicap'))
    else:
        return None
    if label is None:
        return None
    return kind, {'name': label, 'price': q.get('odds_dec'), 'point': point}


def parse(body, sport):
    raw = json.loads(body)
    if not isinstance(raw, dict) or not isinstance(raw.get('matches'), list) or len(raw['matches']) > 2000:
        raise ValueError('Invalid MoviOdds response')
    if raw.get('warming'):
        raise ValueError('MoviOdds warming; retain last successful board')
    rows, rejected, skipped = [], 0, 0
    for row in raw['matches']:
        if not isinstance(row, dict) or row.get('sport') != sport or not isinstance(row.get('quotes'), list):
            raise ValueError('Invalid MoviOdds fixture identity')
        domain = project(sport, str(row.get('league') or ''))
        if not domain:
            skipped += 1
            continue
        if not all(isinstance(row.get(k), str) and row[k] for k in ('id', 'home', 'away', 'kickoff_utc')):
            rejected += 1
            continue
        groups = {}
        for q in row['quotes']:
            try:
                if not isinstance(q, dict) or str(q.get('fixture_id', row['id'])) != row['id'] or not q.get('sel_id'):
                    raise ValueError('Missing selection identity')
                selection = _selection(q, row, sport)
                if not selection:
                    continue
                kind, outcome = selection
                # Lines pair by magnitude for spreads and exact value for totals.
                line_id = abs(outcome['point']) if kind == 'spreads' else outcome['point']
                phase = q.get('phase') or ('inplay' if row.get('in_play') else 'prematch')
                key = (str(q['group_id']), str(q.get('market_id', '')), kind, line_id, phase)
                groups.setdefault(key, []).append((q, outcome))
            except (TypeError, ValueError, KeyError, OverflowError):
                rejected += 1
        normalized = None
        for (group, market_id, kind, _line, phase), selections in groups.items():
            try:
                if len({str(q['sel_id']) for q, _ in selections}) != len(selections):
                    raise ValueError('Duplicate selection identity')
                clocks = [instant(q.get('ts')) for q, _ in selections]
                changed = min(clocks) if all(clocks) else None
                parsed = fixture({'id': row['id'], 'sport_key': domain, 'sport_title': row.get('league'),
                    'home_team': row['home'], 'away_team': row['away'], 'commence_time': row['kickoff_utc'],
                    'bookmakers': [{'key': 'bet365', 'title': 'bet365', 'markets': [{
                        'key': kind, 'last_update': changed, 'outcomes': [o for _, o in selections]}]}]},
                    provider='moviodds', american=False, tier='mirror-feed')
                quote = parsed['quotes'][0]
                status = (row.get('group_status') or {}).get(group) or {}
                quote.update(sourceCheckedAt=instant(status.get('polled_at')), phase=phase,
                    suspended=any(q.get('suspended') is True for q, _ in selections),
                    sourceStale=status.get('stale') is True,
                    groupId=group, marketId=market_id,
                    selectionIds=[str(q['sel_id']) for q, _ in selections])
                if normalized is None:
                    normalized = {**parsed, 'quotes': []}
                normalized['quotes'].append(quote)
            except (TypeError, ValueError, KeyError, OverflowError):
                rejected += 1
        if normalized:
            stats = row.get('stats') or {}
            normalized.update(inPlay=row.get('in_play') is True,
                score=str(row['score'])[:80] if row.get('score') is not None else None,
                scoreUpdatedAt=instant(stats.get('updated_at') or row.get('last_live_seen')),
                period=stats.get('period') if isinstance(stats.get('period'), (int, str)) else None)
            rows.append(normalized)
    return {'fixtures': rows, 'providerGeneratedAt': instant(raw.get('generated_at')),
            'receivedFixtures': len(raw['matches']), 'rejectedMarkets': rejected, 'excludedFixtures': skipped}
