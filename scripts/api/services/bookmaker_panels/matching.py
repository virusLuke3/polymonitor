"""Evidence-based event and selection linking; prices never select an identity."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import hashlib
import json
import re
import unicodedata
from zoneinfo import ZoneInfo

VERSION = 1
SPORT_PREFIX = {'nba': 'nba', 'nfl': 'nfl', 'nhl': 'nhl', 'mlb': 'mlb',
                'cs2': 'cs2', 'lol': 'lol', 'dota2': 'dota2', 'val': 'valorant', 'r6': 'r6'}
GAMES = {'cs2', 'lol', 'dota2', 'valorant', 'r6'}


def key(value):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', str(value)).casefold())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def identity(f):
    return digest([f['sport'], f['home'], f['away'], f['startTime'], f['competition']])


def epoch(value):
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return d.timestamp() if d.tzinfo else None
    except (ValueError, TypeError):
        return None


def scheduled(description):
    # Rules contain an explicit event clock. endDate is deliberately excluded.
    m = re.search(r'scheduled for (?:[A-Za-z]+, )?([A-Za-z]+ \d{1,2}, \d{4} at \d{1,2}:\d{2} [AP]M) ET\b', description or '')
    if not m:
        return None
    try:
        return datetime.strptime(m[1], '%B %d, %Y at %I:%M %p').replace(tzinfo=ZoneInfo('America/New_York')).timestamp()
    except ValueError:
        return None


class Aliases:
    def __init__(self, rows=()):
        self.rows, self.index = list(rows), {}
        for row in self.rows:
            if not isinstance(row, dict) or not all(row.get(k) for k in ('sport', 'entity', 'names', 'evidence')):
                raise ValueError('Aliases require sport, entity, names and evidence')
            if not isinstance(row['names'], list) or len(row['names']) < 2:
                raise ValueError('Alias names must be an explicit list')
            for label in row['names']:
                k = (row['sport'], key(label))
                if not k[1] or k in self.index and self.index[k] != row['entity']:
                    raise ValueError('Ambiguous alias')
                self.index[k] = row['entity']
        self.version = digest(self.rows)

    def entity(self, sport, label):
        return self.index.get((sport, key(label)), 'name:' + key(label))

    def same(self, sport, a, b):
        return self.entity(sport, a) == self.entity(sport, b)


def event(row):
    slug = str(row.get('slug') or '')
    sport = SPORT_PREFIX.get(slug.split('-')[0])
    if not sport or not re.search(r'-\d{4}-\d{2}-\d{2}$', slug):
        return None
    title = str(row.get('title') or '')
    if sport in GAMES:
        m = re.fullmatch(r'[^:]+: (.+?) vs\.? (.+?) \(BO([13579])\) - (.+)', title)
    else:
        m = re.fullmatch(r'(.+?) vs\.? (.+)', title)
    if not m or not row.get('event_id'):
        return None
    start = scheduled(row.get('description'))
    if start is None:
        return None
    return {'pmEventId': str(row['event_id']), 'sport': sport, 'teams': [m[1], m[2]],
            'start': start, 'competition': m[4] if sport in GAMES else sport,
            'bestOf': int(m[3]) if sport in GAMES else None, 'row': row}


def competition_match(a, b):
    ignore = {'group', 'playoffs', 'playoff', 'stage', 'qualifier', 'qualifiers', 'league',
              'season', 'division', 'div', 'bo3', 'bo5', 'bo1', 'cs2', 'lol', 'dota', 'counter', 'strike'}
    def tokens(s):
        return {x for x in re.findall(r'[a-z0-9]+', s.casefold()) if len(x) > 2 and x not in ignore}
    return bool(tokens(a) & tokens(b))


def assess(f, rows, aliases, *, truncated=False):
    candidates, confirmed = [], {}
    for row in rows:
        e = event(row)
        if not e or e['sport'] != f['sport']:
            continue
        start = epoch(f['startTime'])
        delta = abs(e['start'] - start) if start is not None else None
        if delta is None or delta > 86400:
            continue
        a, b = e['teams']
        direct = aliases.same(f['sport'], f['home'], a) and aliases.same(f['sport'], f['away'], b)
        reverse = aliases.same(f['sport'], f['home'], b) and aliases.same(f['sport'], f['away'], a)
        if not direct and not reverse:
            # A proposal only; no aliases are learned from this score.
            score = max(min(SequenceMatcher(None, key(f['home']), key(a)).ratio(), SequenceMatcher(None, key(f['away']), key(b)).ratio()),
                        min(SequenceMatcher(None, key(f['home']), key(b)).ratio(), SequenceMatcher(None, key(f['away']), key(a)).ratio()))
            if score < .55:
                continue
            reason = 'team_alias_unverified'
        elif delta > 300:
            reason = 'kickoff_conflict'
        elif f['sport'] in GAMES and not competition_match(f['competition'], e['competition']):
            reason = 'competition_unverified'
        else:
            reason = 'exact_entities_and_time'
            confirmed[e['pmEventId']] = e
        candidates.append({'eventId': e['pmEventId'], 'title': row['title'], 'reason': reason, 'timeDeltaSeconds': delta})
    if truncated:
        return {'state': 'incomplete', 'reason': 'candidate_search_truncated', 'candidates': candidates[:8]}, None
    if len(confirmed) == 1:
        selected = next(iter(confirmed.values()))
        # A second same-pair event close in time is an ambiguity, even if its
        # competition needs review. Do not let weaker metadata hide a collision.
        competing = {c['eventId'] for c in candidates if c['timeDeltaSeconds'] <= 300 and c['reason'] != 'team_alias_unverified'}
        if len(competing) == 1:
            return {'state': 'linked', 'reason': 'exact_entities_and_time', 'pmEventId': selected['pmEventId'],
                    'title': selected['row']['title'], 'candidates': candidates[:8]}, selected
    return {'state': 'review' if candidates else 'unmatched',
            'reason': 'ambiguous_event' if len(confirmed) > 1 else candidates[0]['reason'] if candidates else 'no_candidate_in_catalog',
            'candidates': candidates[:8]}, None


def decimal_line(value):
    try:
        n = Decimal(str(value))
        return n if n.is_finite() else None
    except InvalidOperation:
        return None


def semantics(row, e):
    """Strict, small grammar. Unrecognized variants stay unsupported."""
    slug, root = row.get('slug', ''), e['row']['slug']
    suffix = slug[len(root):] if slug.startswith(root) else '?'
    title = row.get('title', '')
    if suffix == '':
        return {'type': 'h2h', 'metric': 'series' if e['sport'] in GAMES else 'match', 'line': None, 'team': None}
    if re.fullmatch(r'-(?:total-games|total)-\d+(?:pt\d+)?', suffix):
        n = decimal_line(suffix.rsplit('-', 1)[1].replace('pt', '.'))
        return {'type': 'totals', 'metric': 'maps' if e['sport'] in GAMES else {'nhl': 'goals', 'mlb': 'runs'}.get(e['sport'], 'points'), 'line': n, 'team': None}
    if re.fullmatch(r'-(?:map-handicap|spread|handicap)-[a-z0-9]+-\d+(?:pt\d+)?', suffix):
        m = re.search(r'(?:Spread: |Handicap: )?(.+?) \(([+-]?\d+(?:\.\d+)?)\)', title)
        if m:
            team = re.sub(r'^(?:Map Handicap: |Spread: |Handicap: )', '', m[1])
            return {'type': 'spreads', 'metric': 'maps' if e['sport'] in GAMES else {'nhl': 'goals', 'mlb': 'runs'}.get(e['sport'], 'points'),
                    'line': decimal_line(m[2]), 'team': team}
    return None


def market_links(e, rows):
    result = []
    for row in rows:
        s = semantics(row, e)
        if not s or s['type'] != 'h2h' and (s['line'] is None or abs(s['line']) % 1 != Decimal('.5')):
            continue
        ids, labels = row.get('quote_token_ids'), row.get('quote_labels')
        if not isinstance(ids, list) or not isinstance(labels, list) or len(ids) != 2 or len(labels) != 2 or len(set(ids)) != 2:
            continue
        if set(ids) != {row.get('yes_token_id'), row.get('no_token_id')} or row.get('quote_condition_id') != row.get('condition_id'):
            continue
        if not re.fullmatch(r'0x[0-9a-fA-F]{64}', str(row.get('condition_id') or '')):
            continue
        if s['type'] == 'h2h' and {key(x) for x in labels} != {key(x) for x in e['teams']}:
            continue  # e.g. football Yes/No requires a different predicate grammar
        if s['type'] == 'totals' and {key(x) for x in labels} != {'over', 'under'}:
            continue
        if s['type'] == 'spreads' and (key(s['team']) not in {key(x) for x in e['teams']} or {key(x) for x in labels} != {key(x) for x in e['teams']}):
            continue
        prices = row.get('quote_prices') or [None, None]
        outcomes = []
        for i, (token, label) in enumerate(zip(ids, labels)):
            p = decimal_line(prices[i]) if i < len(prices) else None
            outcomes.append({'tokenId': token, 'label': label, 'catalogPrice': float(p) if p is not None and 0 <= p <= 1 else None})
        result.append({'marketId': str(row['id']), 'conditionId': row['condition_id'], 'slug': row['slug'],
                       'title': row['title'], 'type': s['type'], 'metric': s['metric'], 'period': 'full',
                       'line': str(s['line']) if s['line'] is not None else None, 'handicapTeam': s['team'],
                       'outcomes': outcomes, 'observedAt': row.get('quote_observed_at'),
                       'sourceUpdatedAt': row.get('quote_updated_at'), 'rulesHash': digest(row.get('description')),
                       'settlement': 'unknown', 'reason': 'bookmaker_settlement_rules_unverified'})
    return sorted(result, key=lambda m: (m['type'] != 'h2h', m['type'], m['line'] or '', m['conditionId']))


def compatible_selection(f, q, m, aliases):
    if q.get('category') != 'sportsbook' or q.get('market') != m['type'] or q.get('period') != 'full':
        return None
    if f['sport'] in GAMES and m['type'] != 'h2h' and not q.get('metric'):
        return None  # a generic "total" can be maps, rounds or kills
    if q.get('metric') and q['metric'] != m['metric']:
        return None
    pairs = []
    for o in q['outcomes']:
        found = [p for p in m['outcomes'] if aliases.same(f['sport'], o['name'], p['label'])]
        if len(found) != 1:
            return None
        if m['type'] != 'h2h':
            expected = decimal_line(m['line'])
            if m['type'] == 'spreads' and not aliases.same(f['sport'], o['name'], m['handicapTeam']):
                expected = -expected
            if decimal_line(o.get('point')) != expected:
                return None
        pairs.append({'selection': o['name'], 'tokenId': found[0]['tokenId']})
    return pairs if len(pairs) == len(m['outcomes']) else None
