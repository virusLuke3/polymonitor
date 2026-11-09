"""Validated prices. Market completeness and line identity precede probability."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

GAMES = frozenset({'lol', 'valorant', 'cs2', 'dota2'})
PRIORITY = ('bet365', 'pinnacle', 'stake', 'ggbet', 'thunderpick', 'draftkings', 'fanduel', 'betmgm')


def instant(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc).isoformat() if dt.tzinfo else None
    except (TypeError, ValueError):
        return None


def name(value):
    return re.sub(r'[^\w]', '', str(value).casefold())


def number(value):
    if isinstance(value, bool):
        raise ValueError('Boolean price')
    n = float(value)
    if not math.isfinite(n):
        raise ValueError('Nonfinite price')
    return n


def decimal(value, american=True):
    n = number(value)
    if american:
        if abs(n) < 100 or not n.is_integer():
            raise ValueError('Invalid American price')
        return 1 + (n / 100 if n > 0 else 100 / abs(n))
    if n <= 1:
        raise ValueError('Invalid decimal price')
    return n


def link(value):
    try:
        p = urlsplit(value or '')
        secret = any(k.lower().replace('_', '') in {'apikey', 'token', 'secret', 'password', 'authorization'} for k in parse_qs(p.query))
        return value if p.scheme == 'https' and p.hostname and not p.username and not p.password and not secret else None
    except ValueError:
        return None


def fixture(raw, *, provider='oddslink', american=True, tier='public-board'):
    if not isinstance(raw, dict) or not all(isinstance(raw.get(k), str) and raw[k] for k in ('id', 'sport_key', 'home_team', 'away_team')):
        raise ValueError('Fixture identity missing')
    kickoff = instant(raw.get('commence_time'))
    if not kickoff or not isinstance(raw.get('bookmakers'), list):
        raise ValueError('Invalid fixture')
    teams = {name(raw['home_team']), name(raw['away_team'])}
    if len(teams) != 2:
        raise ValueError('Identical teams')
    result = {'id': f'{provider}:{raw["id"]}', 'provider': provider, 'tier': tier,
        'sport': raw['sport_key'], 'competition': str(raw.get('sport_title') or raw['sport_key']),
        'home': raw['home_team'], 'away': raw['away_team'], 'startTime': kickoff, 'quotes': []}
    if provider == 'the-odds-api':
        key = raw['sport_key']
        result['sport'] = {'basketball_nba': 'nba', 'americanfootball_nfl': 'nfl', 'baseball_mlb': 'mlb',
                           'icehockey_nhl': 'nhl'}.get(key, 'soccer' if key.startswith('soccer_') else 'tennis' if key.startswith('tennis_') else key)
    rejected = 0
    for book in raw['bookmakers'][:80]:
        if not isinstance(book, dict) or not isinstance(book.get('key'), str):
            rejected += 1
            continue
        markets = book.get('markets', {})
        if isinstance(markets, dict):
            markets = [{'key': k, 'outcomes': v} for k, v in markets.items()]
        if not isinstance(markets, list):
            rejected += 1
            continue
        for market in markets[:20]:
            try:
                kind = market['key']
                outcomes = market['outcomes']
                if kind not in {'h2h', 'spreads', 'totals'} or market.get('period') not in (None, 'full'):
                    continue
                if not isinstance(outcomes, list) or len(outcomes) not in (2, 3):
                    raise ValueError('Incomplete market')
                labels = {name(o['name']) for o in outcomes}
                if len(labels) != len(outcomes):
                    raise ValueError('Duplicate outcomes')
                if kind == 'h2h' and labels not in (teams, teams | {'draw'}):
                    raise ValueError('Wrong winner outcomes')
                if kind == 'totals' and labels != {'over', 'under'}:
                    raise ValueError('Incomplete total')
                if kind == 'spreads' and labels != teams:
                    raise ValueError('Incomplete spread')
                points = [number(o['point']) for o in outcomes] if kind != 'h2h' else []
                if points and (len(points) != 2 or (kind == 'totals' and points[0] != points[1]) or
                               (kind == 'spreads' and abs(sum(points)) > 1e-6)):
                    raise ValueError('Different lines')
                prices = [decimal(o['price'], american) for o in outcomes]
                implied = [1 / p for p in prices]
                total = sum(implied)
                category = book.get('kind', 'sportsbook')
                if book['key'].lower() in {'polymarket', 'kalshi'}:
                    category = 'prediction_market'
                elif name(book['key']) in {'betfair', 'matchbook', 'novig', 'prophetx', 'sxbet', '4casters'} or book['key'].startswith('betfair_ex_'):
                    category = 'exchange'
                if category not in {'sportsbook', 'exchange', 'prediction_market'}:
                    category = 'unknown'
                result['quotes'].append({'book': book['key'], 'label': str(book.get('title') or book['key']),
                    'category': category, 'market': kind, 'period': 'full', 'provider': provider,
                    'sourceUpdatedAt': instant(market.get('last_update') or book.get('last_update')),
                    'url': link(book.get('link')), 'overround': total - 1,
                    'outcomes': [{'name': o['name'], 'decimal': p, 'implied': 1/p,
                                  'probability': (1/p)/total, 'point': points[i] if points else None}
                                 for i, (o, p) in enumerate(zip(outcomes, prices))]})
            except (KeyError, TypeError, ValueError, OverflowError):
                rejected += 1
    result['rejectedMarkets'] = rejected
    if raw['bookmakers'] and not result['quotes']:
        raise ValueError('No valid markets in nonempty fixture')
    result['quotes'].sort(key=lambda q: (q['category'] != 'sportsbook',
        PRIORITY.index(name(q['book'])) if name(q['book']) in PRIORITY else 99, q['book'], q['market']))
    return result


def parse_board(body, sport):
    raw = json.loads(body)
    if not isinstance(raw, dict) or raw.get('sport_key') != sport or not isinstance(raw.get('fixtures'), list) or len(raw['fixtures']) > 60:
        raise ValueError('Wrong board response')
    rows = [fixture(x) for x in raw['fixtures']]
    if any(r['sport'] != sport for r in rows):
        raise ValueError('Mixed board identities')
    return {'fixtures': rows, 'providerGeneratedAt': instant(raw.get('generated_at'))}


def parse_the_odds(body):
    raw = json.loads(body)
    if not isinstance(raw, list) or len(raw) > 300:
        raise ValueError('Invalid The Odds API response')
    return {'fixtures': [fixture(x, provider='the-odds-api', american=False, tier='quota-feed') for x in raw]}


def parse_guest(body, sport):
    raw = json.loads(body)
    if not isinstance(raw, list) or len(raw) > 200:
        raise ValueError('Invalid guest response')
    rows = [fixture(x, tier='daily-sample') for x in raw]
    if any(x['sport'] != sport for x in rows):
        raise ValueError('Wrong guest game')
    return {'fixtures': rows}


def parse_props(body, sport):
    raw = json.loads(body)
    if not isinstance(raw, dict) or raw.get('sport') != sport or not isinstance(raw.get('props'), list) or len(raw['props']) > 1:
        raise ValueError('Invalid demo response')
    rows = []
    for p in raw['props']:
        if not all(isinstance(p.get(k), str) and p[k] for k in ('propId', 'player_name', 'stat_type', 'book_name', 'direction')):
            raise ValueError('Invalid player prop')
        rows.append({'id': p['propId'], 'sport': sport, 'player': p['player_name'],
            'stat': p['stat_type'], 'line': number(p['line']), 'decimal': decimal(p['odds']),
            'direction': p['direction'], 'book': p['book_name'], 'startTime': instant(p.get('event_time')),
            'url': link((p.get('links') or {}).get('market')), 'sourceUpdatedAt': None,
            'tier': 'public-demo', 'provider': 'kashrock'})
    return {'props': rows}
