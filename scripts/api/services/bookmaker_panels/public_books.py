"""Public bookmaker feeds. Endpoints/credentials live only in personal env.

Only explicit whole-match markets enter the shared model. A receipt, event
modification or HTML generation time is never substituted for a price clock.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
import hashlib
import json
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from api.services.panel_evidence_store import SourceSpec, fetch_bytes, read_source
from data_sources import source_value
from .model import GAMES, book_key, fixture, instant, name

PATHS = {
    'bovada': {'nba': 'basketball/nba', 'nfl': 'football/nfl', 'nhl': 'hockey/nhl',
               'mlb': 'baseball/mlb', 'ncaaf': 'football/college-football', 'ncaab': 'basketball/college-basketball'},
    'betrivers': {'nba': 'basketball/nba', 'nfl': 'american_football/nfl',
                  'nhl': 'ice_hockey/nhl', 'mlb': 'baseball/mlb'},
}
LABELS = {'fanduel': 'FanDuel direct', 'bovada': 'Bovada direct',
          'betrivers': 'BetRivers / Kambi', 'pinnodds': 'Pinnacle via Pinnodds', 'oddsportal': 'OddsPortal'}


def epoch(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc).isoformat()


def emit(event_id, sport, home, away, start, book, markets, *, provider, competition=None, phase='prematch'):
    row = fixture({'id': str(event_id), 'sport_key': sport, 'sport_title': competition or sport.upper(),
        'home_team': home, 'away_team': away, 'commence_time': start,
        'bookmakers': [{'key': book, 'title': book, 'markets': markets}]},
        provider=provider, american=False, tier='public-feed')
    for q in row['quotes']:
        market = next(m for m in markets if m['key'] == q['market'] and
                      {o['name'] for o in m['outcomes']} == {o['name'] for o in q['outcomes']})
        q.update(suspended=bool(market.get('suspended')), phase=phase)
    return row


def parse_fanduel(body, sport):
    raw = json.loads(body)
    attachments = raw['attachments']
    events, markets = attachments['events'], attachments['markets']
    if not isinstance(events, dict) or not isinstance(markets, dict):
        raise ValueError('Invalid FanDuel attachments')
    kinds = {'MONEY_LINE': 'h2h', 'MATCH_HANDICAP_(2-WAY)': 'spreads',
             'TOTAL_POINTS_(OVER/UNDER)': 'totals', 'TOTAL_RUNS_(OVER/UNDER)': 'totals',
             'TOTAL_GOALS_(OVER/UNDER)': 'totals'}
    rows, rejected = [], 0
    for e in events.values():
        if ' @ ' not in e.get('name', ''):
            continue  # Outrights, awards and season totals are not matches.
        away, home = e['name'].split(' @ ', 1)
        selected = [m for m in markets.values() if m.get('eventId') == e['eventId'] and m.get('marketType') in kinds]
        parsed = []
        for m in selected:
            try:
                kind = kinds[m['marketType']]
                outcomes = []
                for r in m['runners']:
                    side = r.get('result', {}).get('type')
                    label = {'HOME': home, 'AWAY': away, 'OVER': 'Over', 'UNDER': 'Under'}.get(side)
                    if not label or (kind != 'totals' and name(label) != name(r['runnerName'])):
                        raise ValueError('Unverified runner direction')
                    outcomes.append({'name': label, 'price': r['winRunnerOdds']['trueOdds']['decimalOdds']['decimalOdds'],
                                     'point': r.get('handicap')})
                parsed.append({'key': kind, 'outcomes': outcomes,
                    'suspended': m.get('marketStatus') != 'OPEN' or any(r.get('runnerStatus') != 'ACTIVE' for r in m['runners'])})
            except (KeyError, TypeError, ValueError):
                rejected += 1
        if not parsed:
            continue
        try:
            rows.append(emit(e['eventId'], sport, home, away, e['openDate'], 'fanduel', parsed,
                provider='fanduel', phase='inplay' if any(m.get('inPlay') for m in selected) else 'prematch'))
        except ValueError:
            rejected += 1
    if markets and not rows and any(m.get('marketType') in kinds for m in markets.values()):
        raise ValueError('No valid FanDuel match markets')
    return {'fixtures': rows, 'rejectedMarkets': rejected}


def parse_bovada(body, sport):
    blocks = json.loads(body)
    if not isinstance(blocks, list) or any(not isinstance(b.get('events'), list) for b in blocks):
        raise ValueError('Invalid Bovada response')
    rows, rejected, candidates = [], 0, 0
    kinds = {'2W-12': 'h2h', '3W-12': 'h2h', '2W-HCAP': 'spreads', '2W-OU': 'totals'}
    for block in blocks:
        for e in block['events']:
            if e.get('type') != 'GAMEEVENT':
                continue
            teams = {c.get('home'): c for c in e.get('competitors', []) if isinstance(c.get('home'), bool)}
            if len(teams) != 2:
                continue
            home, away = teams[True]['name'], teams[False]['name']
            parsed = []
            for group in e.get('displayGroups', []):
                for m in group.get('markets', []):
                    # Main period alone is insufficient: player props use it too.
                    if (m.get('key') not in kinds or m.get('period', {}).get('abbreviation') != 'G' or
                            m.get('descriptionKey') not in {'Head To Head', 'Main Dynamic Asian Handicap', 'Main Dynamic Over/Under'}):
                        continue
                    candidates += 1
                    try:
                        outcomes = []
                        for o in m['outcomes']:
                            label = {'H': home, 'A': away, 'O': 'Over', 'U': 'Under', 'D': 'Draw'}.get(o.get('type'))
                            if not label:
                                raise ValueError('Unknown Bovada direction')
                            if o.get('type') in ('H', 'A') and str(o.get('competitorId')) != str(teams[o['type'] == 'H']['id']):
                                raise ValueError('Wrong Bovada competitor')
                            outcomes.append({'name': label, 'price': o['price']['decimal'], 'point': o['price'].get('handicap')})
                        parsed.append({'key': kinds[m['key']], 'outcomes': outcomes,
                            'suspended': m.get('status') != 'O' or any(o.get('status') != 'O' for o in m['outcomes'])})
                    except (KeyError, TypeError, ValueError):
                        rejected += 1
            if parsed:
                try:
                    row = emit(e['id'], sport, home, away, epoch(e['startTime']), 'bovada', parsed,
                        provider='bovada', phase='inplay' if e.get('live') else 'prematch')
                    row['eventUpdatedAt'] = epoch(e.get('lastModified'))
                    rows.append(row)
                except ValueError:
                    rejected += 1
    if candidates and not rows:
        raise ValueError('No valid Bovada match markets')
    return {'fixtures': rows, 'rejectedMarkets': rejected}


def parse_betrivers(body, sport):
    raw = json.loads(body)
    if not isinstance(raw.get('events'), list):
        raise ValueError('Invalid Kambi response')
    rows, rejected, candidates = [], 0, 0
    for item in raw['events']:
        e = item['event']
        parsed = []
        for m in item.get('betOffers', []):
            c = m.get('criterion', {})
            nhl_full = c.get('label') == 'Moneyline - Inc. OT and Shootout' and c.get('englishLabel') == 'Moneyline - Including Overtime and penalty shootout'
            if c.get('lifetime') not in ('FULL_TIME', 'FULL_TIME_OVERTIME') and not nhl_full:
                continue
            kind = {'Moneyline': 'h2h', 'Point Spread': 'spreads', 'Run Line': 'spreads',
                    'Puck Line': 'spreads', 'Total Points': 'totals', 'Total Runs': 'totals', 'Total Goals': 'totals',
                    'Moneyline - Inc. OT and Shootout': 'h2h'}.get(c.get('label'))
            if not kind:
                continue
            candidates += 1
            try:
                outcomes = []
                for o in m['outcomes']:
                    label = o.get('participant') if kind != 'totals' else {'OVER': 'Over', 'UNDER': 'Under'}.get(o.get('type'))
                    outcomes.append({'name': label, 'price': o['odds'] / 1000,
                                     'point': o['line'] / 1000 if 'line' in o else None})
                clocks = [instant(o.get('changedDate')) for o in m['outcomes']]
                parsed.append({'key': kind, 'outcomes': outcomes,
                    'last_update': min(clocks) if clocks and all(clocks) else None,
                    'suspended': bool(m.get('suspended')) or any(o.get('status') != 'OPEN' for o in m['outcomes'])})
            except (KeyError, TypeError, ValueError):
                rejected += 1
        if parsed:
            try:
                rows.append(emit(e['id'], sport, e['homeName'], e['awayName'], e['start'], 'betrivers', parsed,
                    provider='betrivers', competition=e.get('group'), phase='inplay' if e.get('state') == 'STARTED' else 'prematch'))
            except (KeyError, ValueError):
                rejected += 1
    if candidates and not rows:
        raise ValueError('No valid Kambi match markets')
    return {'fixtures': rows, 'rejectedMarkets': rejected}


def flight(body):
    """Decode public JSON strings; never evaluate remote JavaScript."""
    chunks = []
    for script in BeautifulSoup(body, 'html.parser').find_all('script'):
        m = re.fullmatch(r'self\.__next_f\.push\((.*)\)', script.get_text(), re.S)
        if m:
            value = json.loads(m[1])
            if len(value) == 2 and value[0] == 1 and isinstance(value[1], str):
                chunks.append(value[1])
    return ''.join(chunks)


def parse_portal_books(body):
    text = flight(body)
    marker = '"bookmakersList":'
    start = text.find(marker)
    if start < 0:
        raise ValueError('OddsPortal bookmaker catalog missing')
    rows, _ = json.JSONDecoder().raw_decode(text[start + len(marker):])
    books = {str(b['bookiesColumn']['bookieId']): b['bookiesColumn']['bookieName'] for b in rows}
    if not books:
        raise ValueError('Empty bookmaker catalog')
    return {'books': books}


PORTAL_BOOKS = SourceSpec('bookmakers:portalbooks:catalog:v1', 'OddsPortal bookmaker identities',
    'POLYDATA_ODDSPORTAL_BOOKMAKERS_URL', parse_portal_books, cadence=86400, stale_after=172800, retain_for=604800)


def parse_oddsportal(body, sport, books):
    text = flight(body)
    start = text.find('"rows":[{"id":')
    if start < 0:
        raise ValueError('OddsPortal event table missing')
    props, _ = json.JSONDecoder().raw_decode(text[start - 1:])
    odds = props['initialOddsMap']
    rows, unknown = [], set()
    for e in props['rows']:
        # Public listing's columns explicitly identify the outcome order.
        if e.get('cols') != '1|2' or e.get('event-stage-name') != 'Scheduled':
            continue
        quote = odds.get(e['encodeEventId'], {})
        parts = quote.get('odds', [])
        expected_scope = 2 if sport in GAMES else 1
        if len(parts) != 2 or any(p.get('scopeId') != expected_scope or p.get('bettingTypeId') != 3 or not p.get('active') for p in parts):
            continue
        positions = parts[0].get('positionsWithProviders', [])
        if len(positions) != 2 or parts[1].get('positionsWithProviders') != positions:
            continue
        if isinstance(positions, dict):
            if set(positions) != {'0', '1'}:
                continue
            positions = [positions['0'], positions['1']]
        rows_by_book = []
        for book_id in positions[0].keys() & positions[1].keys():
            if book_id not in books:
                unknown.add(book_id)
                continue
            try:
                prices = []
                for i, side in enumerate(positions):
                    value = side[book_id]['odds']
                    # Indexed dict or single first-position array; no guessing.
                    prices.append(value[str(i)] if isinstance(value, dict) else value[i])
                markets = [{'key': 'h2h', 'outcomes': [{'name': e['home-name'], 'price': prices[0]},
                                                     {'name': e['away-name'], 'price': prices[1]}]}]
                rows_by_book.append(emit(e['id'], sport, e['home-name'], e['away-name'], epoch(e['date-start-timestamp']),
                    name(books[book_id]), markets, provider='oddsportal', competition=e['tournament-name']))
            except (KeyError, IndexError, TypeError, ValueError):
                continue
        if rows_by_book:
            row = rows_by_book[0]
            row['quotes'] = [q for item in rows_by_book for q in item['quotes']]
            for q in row['quotes']:
                q['label'] = next(v for v in books.values() if book_key(v) == q['book'])
            rows.append(row)
    return {'fixtures': rows, 'unknownBookmakerIds': sorted(unknown)}


def parse_pinnodds(body, sport):
    soup = BeautifulSoup(body, 'html.parser')
    stamp = None
    for script in soup.select('script[type="application/ld+json"]'):
        value = json.loads(script.get_text())
        if value.get('@type') == 'WebPage':
            stamp = instant(value.get('dateModified'))
    if stamp and re.search(r'No [A-Za-z ]+ fixtures are open on the board right now\.', soup.get_text(' ', strip=True)):
        return {'fixtures': [], 'boardGeneratedAt': stamp, 'rejectedMarkets': 0}
    if not stamp or not soup.select('table'):
        raise ValueError('Pinnodds snapshot identity missing')
    anchor = datetime.fromisoformat(stamp)
    rows, rejected = [], 0
    for tr in soup.select('tbody tr'):
        try:
            cell = tr.select_one('td.ev')
            title = cell.select_one('b')
            sides = list(title.stripped_strings)
            divider = sides.index('v')
            home, away = ' '.join(sides[:divider]), ' '.join(sides[divider + 1:])
            competition = cell.select_one('small').get_text(strip=True)
            project = sport
            if sport == 'esports':
                prefix = competition.split(' - ', 1)[0].casefold()
                project = {'cs2': 'cs2', 'league of legends': 'lol', 'dota 2': 'dota2',
                           'valorant': 'valorant', 'rainbow six': 'r6', 'r6': 'r6'}.get(prefix)
                if not project:
                    continue
            when = tr.select_one('td.when').get_text(strip=True)
            candidates = [datetime.strptime(f'{year} {when}', '%Y %a %d %b %H:%M UTC').replace(tzinfo=timezone.utc)
                          for year in (anchor.year - 1, anchor.year, anchor.year + 1)]
            start = min(candidates, key=lambda d: abs((d - anchor).total_seconds()))
            if not -86400 < (start - anchor).total_seconds() < 8 * 86400:
                raise ValueError('Pinnodds date outside declared window')
            markets = []
            for keys, kind in [(('Moneyline', '1 / X / 2'), 'h2h'), (('Spread', 'Asian handicap', 'Puck line', 'Run line', 'Game handicap'), 'spreads'), (('Total', 'Total goals', 'Total runs', 'Total games'), 'totals')]:
                col = next((tr.select_one(f'td[data-l="{key}"]') for key in keys if tr.select_one(f'td[data-l="{key}"]')), None)
                spans = [s.get_text(' ', strip=True) for s in col.select('span')] if col else []
                if len(spans) not in (2, 3):
                    continue
                point = float(col.select_one('i').get_text()) if kind != 'h2h' else None
                labels = ['Over', 'Under'] if kind == 'totals' else [home, 'Draw', away] if len(spans) == 3 else [home, away]
                outcomes = [{'name': label, 'price': float(re.sub(r'^[ou]\s+', '', price)),
                    'point': -point if kind == 'spreads' and i == 1 else point} for i, (label, price) in enumerate(zip(labels, spans))]
                markets.append({'key': kind, 'outcomes': outcomes})
            if not markets:
                continue
            identity = hashlib.sha256(json.dumps([project, home, away, start.isoformat()]).encode()).hexdigest()[:24]
            row = emit(identity, project, home, away, start.isoformat(), 'pinnacle', markets,
                provider='pinnodds', competition=competition)
            row.update(idKind='derived-exact', boardGeneratedAt=stamp)
            rows.append(row)
        except (AttributeError, IndexError, TypeError, ValueError):
            rejected += 1
    if soup.select('tbody tr') and not rows:
        raise ValueError('No valid Pinnodds rows')
    return {'fixtures': rows, 'boardGeneratedAt': stamp, 'rejectedMarkets': rejected}


def specs():
    result = []
    parsers = {'fanduel': parse_fanduel, 'bovada': parse_bovada, 'betrivers': parse_betrivers,
               'pinnodds': parse_pinnodds}
    for provider, sports in [('fanduel', ('nba', 'nfl', 'nhl', 'mlb')), ('bovada', PATHS['bovada']),
                             ('betrivers', PATHS['betrivers']), ('pinnodds', ('nba', 'nfl', 'nhl', 'mlb', 'soccer', 'tennis', 'esports'))]:
        env = f'POLYDATA_{provider.upper()}_PUBLIC_' + ('BOARD_URL' if provider == 'pinnodds' else 'URL')
        if source_value(env):
            result.extend(SourceSpec(f'bookmakers:{provider}:{sport}:v1', f'{LABELS[provider]} · {sport.upper()}',
                env, partial(parsers[provider], sport=sport), cadence=900, stale_after=1800, retain_for=7200) for sport in sports)
    if source_value('POLYDATA_ODDSPORTAL_PUBLIC_URL') and source_value(PORTAL_BOOKS.url_env):
        result.extend([PORTAL_BOOKS, SourceSpec('bookmakers:oddsportal:nba:v1', 'OddsPortal · NBA',
            'POLYDATA_ODDSPORTAL_PUBLIC_URL', lambda body: {}, cadence=900, stale_after=1800, retain_for=7200)])
        if source_value('POLYDATA_ODDSPORTAL_LOL_URL'):
            result.append(SourceSpec('bookmakers:oddsportal:lol:v1', 'OddsPortal · LoL Worlds',
                'POLYDATA_ODDSPORTAL_LOL_URL', lambda body: {}, cadence=900, stale_after=1800, retain_for=7200))
    return result


def acquire(store, spec, deadline):
    _, provider, sport, _ = spec.key.split(':')
    url = source_value(spec.url_env)
    if provider == 'fanduel':
        key = source_value('POLYDATA_FANDUEL_PUBLIC_APP_KEY')
        if not key:
            raise ValueError('FanDuel public application identifier not configured')
        url += '?' + urlencode({'page': 'CUSTOM', 'customPageId': sport, '_ak': key})
    elif provider in PATHS:
        url = url.format(path=PATHS[provider][sport])
    elif provider == 'pinnodds':
        url = url.format(sport=sport)
    raw = fetch_bytes(url, deadline=deadline, timeout=45, max_bytes=spec.max_bytes)
    if provider == 'oddsportal':
        catalog, meta = read_source(store, PORTAL_BOOKS)
        if not meta['usable']:
            raise ValueError('No verified bookmaker catalog')
        return raw, parse_oddsportal(raw, sport, catalog['books'])
    return raw, spec.parse(raw)
