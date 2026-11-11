"""Bounded public collection, durable recovery and read-only panel composition."""
from __future__ import annotations

from functools import partial
import json
import time
from urllib.parse import urlencode

from api.services.panel_evidence_store import SourceSpec, collect_one, fetch_bytes, read_source
from data_sources import source_value
from .model import GAMES, book_category, book_key, name, parse_board, parse_guest, parse_props, parse_the_odds
from .budget import reserve_guest
from . import moviodds, public_books

SPORTS = ('nba', 'soccer', 'nfl', 'nhl', 'mlb', 'tennis', 'mma', 'ncaab', 'ncaaf', 'wnba')
GAME_LIST = ('lol', 'valorant', 'cs2', 'dota2')
THE_ODDS = SourceSpec('bookmakers:the-odds-api:v1', 'The Odds API',
    'POLYDATA_THE_ODDS_API_BASE_URL', parse_the_odds, cadence=7200, stale_after=10800, retain_for=21600)


class GuestBudgetExhausted(ValueError):
    pass


def specs():
    result = [SourceSpec(f'bookmakers:board:{s}:v1', f'OddsLink · {s.upper()}',
        'POLYDATA_ODDSLINK_PUBLIC_BOARD_URL', partial(parse_board, sport=s),
        cadence=900, stale_after=1800, retain_for=7200) for s in SPORTS + GAME_LIST]
    for s in ('lol', 'valorant'):
        result.append(SourceSpec(f'bookmakers:guest:{s}:v1', f'OddsLink daily sample · {s}',
            'POLYDATA_ODDSLINK_TRY_URL', partial(parse_guest, sport=s), cadence=86400, stale_after=86400, retain_for=86400))
    for s in GAME_LIST:
        result.append(SourceSpec(f'bookmakers:props:{s}:v1', f'KashRock public demo · {s}',
            'POLYDATA_KASHROCK_DEMO_PROPS_URL', partial(parse_props, sport=s), cadence=86400, stale_after=86400, retain_for=86400))
    return result + moviodds.specs() + public_books.specs()


def _acquire(store, spec, deadline):
    _, kind, sport, _ = spec.key.split(':')
    url = source_value(spec.url_env)
    if not url:
        raise ValueError('Source not configured')
    if kind == 'movi':
        return moviodds.acquire(spec, deadline)
    if kind in {*public_books.LABELS, 'portalbooks'}:
        return public_books.acquire(store, spec, deadline)
    if kind == 'board':
        url = url.format(sport=sport)
    elif kind == 'props':
        url += ('&' if '?' in url else '?') + urlencode({'sport': sport})
    else:
        # Share the conservative daily allowance with the existing research tool.
        if not reserve_guest(store):
            raise GuestBudgetExhausted('Daily guest budget exhausted')
        url += ('&' if '?' in url else '?') + urlencode({'path': f'/v1/sports/{sport}/odds?markets=h2h&oddsFormat=american'})
        # Guest attempts are billable even on failure. No retry or route failover.
        from api.clients.source_transport import source_session, read_with_retry, read_response_bytes
        with source_session() as session:
            session.trust_env = False
            raw = read_with_retry(session, url,
                lambda r: read_response_bytes(r, spec.max_bytes, deadline=deadline),
                attempts=1, deadline=deadline, timeout=45, stream=True, allow_redirects=False)
        return raw, spec.parse(raw)
    raw = fetch_bytes(url, deadline=deadline, timeout=45, max_bytes=spec.max_bytes)
    return raw, spec.parse(raw)


def collect(store, *, force=False):
    deadline = time.monotonic() + 240
    from api.services.panel_evidence_store import NAMESPACE
    ordered = sorted(specs(), key=lambda s: (s.key != public_books.PORTAL_BOOKS.key,
        (store.get_stale(NAMESPACE, s.key) or {}).get('lastAttemptAt', 0)))
    result = {}
    for spec in ordered:
        if deadline - time.monotonic() < 45:
            result[spec.key] = 'deferred-budget'
            continue
        try:
            state = collect_one(store, spec, acquire=lambda s=spec: _acquire(store, s, deadline), force=force)
            if state.get('error') == 'GuestBudgetExhausted':
                state['nextAttemptAt'] = (int(time.time()) // 86400 + 1) * 86400 + 60
                if not store.set(NAMESPACE, spec.key, state, ttl_seconds=366 * 86400):
                    raise RuntimeError('Guest backoff was not saved')
            result[spec.key] = state.get('error') or 'stored-or-not-due'
        except TimeoutError:
            result[spec.key] = 'deferred-lock'
    return result


def save_the_odds(store, body):
    """Called by its existing owner after the already-budgeted HTTP read."""
    data = parse_the_odds(body)
    return collect_one(store, THE_ODDS, acquire=lambda: (body, data), force=True)


def merge_exact_events(fixtures):
    """Join only exact sport, normalized teams and kickoff; never fuzzy aliases."""
    groups = {}
    for row in fixtures:
        key = (row['sport'], tuple(sorted([name(row['home']), name(row['away'])])), row['startTime'])
        if key not in groups:
            groups[key] = {**row, 'quotes': list(row['quotes']), 'providerFixtureIds': [row['id']]}
            continue
        target = groups[key]
        target['providerFixtureIds'].append(row['id'])
        if row.get('fetchedAt') and row['fetchedAt'] > target.get('fetchedAt', ''):
            target['fetchedAt'] = row['fetchedAt']
        target['tier'] = 'merged-feed'
        if row.get('score') is not None and (row.get('scoreUpdatedAt') or '') > (target.get('scoreUpdatedAt') or ''):
            target.update({k: row.get(k) for k in ('score', 'scoreUpdatedAt', 'period', 'inPlay')})
        def identity(q):
            return (name(q['book']), q['provider'], q['category'], q['market'], q['period'],
                    tuple(sorted((name(o['name']), o['point']) for o in q['outcomes'])))
        quotes = {identity(q): q for q in target['quotes']}
        for q in row['quotes']:
            old = quotes.get(identity(q))
            if old is None or (q.get('sourceCheckedAt') or q['sourceUpdatedAt'] or '') > (old.get('sourceCheckedAt') or old['sourceUpdatedAt'] or ''):
                quotes[identity(q)] = q
        target['quotes'] = list(quotes.values())
    return list(groups.values())


def read_board(store, game=False, *, query=None):
    from .movi_archive import enabled as stream_enabled
    chosen = [s for s in specs() if (s.key.split(':')[2] in GAMES or s.key.split(':')[2] == 'esports') == game]
    if stream_enabled():
        # The live stream owns removals/resync. Older REST quotes cannot resurrect
        # selections it withdrew, including during an outage.
        chosen = [s for s in chosen if not s.key.startswith('bookmakers:movi:')]
    if not game:
        chosen.append(THE_ODDS)
    sources, fixtures, props = [], [], []
    if stream_enabled():
        from .movi_stream import read_stream
        stream_rows, stream_meta = read_stream(store, game)
        fixtures.extend(stream_rows)
        sources.append(stream_meta)
    for spec in chosen:
        data, meta = read_source(store, spec)
        meta = {**meta, 'fixtureCount': len(data.get('fixtures', [])),
                'quoteCount': sum(len(row['quotes']) for row in data.get('fixtures', []))}
        sources.append(meta)
        for row in data.get('fixtures', []):
            if row['provider'] == 'pinnodds':
                project = public_books.pinnodds_project(row['sport'], row['competition'])
                if not project:
                    continue
                row = {**row, 'sport': project}
            # Apply taxonomy fixes to retained evidence without fetching again or
            # rewriting its acquisition clock (notably the daily guest sample).
            quotes = [{**q, 'book': book_key(q['book']), 'category': book_category(q['book'], q['category']),
                       'receivedAt': meta['lastSuccessAt'], 'retentionSeconds': spec.retain_for,
                       'sampleTier': row['tier'],
                       'sourceStale': bool(q.get('sourceStale') or meta['stale']),
                       'sourceError': meta['error']} for q in row['quotes']]
            fixtures.append({**row, 'quotes': quotes, 'fetchedAt': meta['lastSuccessAt'], 'sourceStale': meta['stale'],
                             'sourceError': meta['error']})
        props.extend({**p, 'fetchedAt': meta['lastSuccessAt']} for p in data.get('props', []))
    # A daily guest fixture must not duplicate the same provider's current board.
    fixtures.sort(key=lambda x: (not bool(x['quotes']), x['tier'] == 'daily-sample', x['startTime'], x['id']))
    seen, unique = set(), []
    for row in fixtures:
        if row['id'] not in seen:
            seen.add(row['id'])
            unique.append(row)
    unique = merge_exact_events(unique)
    total = len(unique)
    # Coverage is measured before bounded UI projection. Do not mistake eight
    # visible rows or a small public window for the entire acquired universe.
    coverage = {}
    project_counts = {}
    for row in unique:
        project_counts[row['sport']] = project_counts.get(row['sport'], 0) + 1
        for q in row['quotes']:
            key = name(q['book'])
            item = coverage.setdefault(key, {'book': q['book'], 'label': q['label'], 'category': q['category'],
                'fixtures': set(), 'providers': set(), 'sports': set(), 'fixturesBySport': {}})
            item['fixtures'].add(row['id'])
            item['fixturesBySport'].setdefault(row['sport'], set()).add(row['id'])
            item['providers'].add(q['provider'])
            item['sports'].add(row['sport'])
    coverage = [{**item, 'fixtures': len(item['fixtures']), 'providers': sorted(item['providers']),
                 'sports': sorted(item['sports']),
                 'fixturesBySport': {sport: len(ids) for sport, ids in item['fixturesBySport'].items()}}
                for _, item in sorted(coverage.items())]
    if query is not None:
        # The same retained universe is browsable without collecting on GET or
        # sending thousands of full matrices through the public relay at once.
        sport, provider, search = query['sport'], query['provider'], query['search']
        selected = [row for row in unique if (not sport or row['sport'] == sport) and
                    (not search or search.casefold() in ' '.join((row['home'], row['away'], row['competition'])).casefold())]
        if provider:
            selected = [{**row, 'quotes': [q for q in row['quotes'] if q['provider'] == provider]} for row in selected]
            selected = [row for row in selected if row['quotes']]
        selected.sort(key=lambda row: (row['startTime'], row['id']))
        offset = query['offset']
        page, size = [], 0
        for row in selected[offset:offset + query['limit']]:
            row_size = len(json.dumps(row).encode())
            if size + row_size > 450_000:
                break
            page.append(row)
            size += row_size
        if not page and offset < len(selected):
            raise ValueError('Single fixture exceeds response budget')
        clocks = [s['lastSuccessAt'] for s in sources if s['usable']]
        return {'schemaVersion': 1, 'family': 'game' if game else 'sports', 'fixtures': page,
            'props': [], 'sources': sources, 'generatedAt': max(clocks) if clocks else None,
            'availableFixtures': total, 'omittedFixtures': total - len(page), 'bookmakerCoverage': coverage,
            'projectCounts': project_counts, 'query': query, 'matchedFixtures': len(selected),
            'nextOffset': offset + len(page) if offset + len(page) < len(selected) else None}
    # Round-robin projects: a full soccer board cannot suppress all other sports.
    grouped = {}
    for row in unique:
        grouped.setdefault(row['sport'], []).append(row)
    # A wide aggregate matrix must not consume the response before the newly
    # acquired independent provider is visible for that sport. Identity remains
    # exact; this is projection order, not fuzzy merging of team aliases.
    for sport, rows in grouped.items():
        providers = {}
        for row in rows:
            providers.setdefault(row['provider'], []).append(row)
        ordered = []
        while any(providers.values()):
            for candidates in providers.values():
                if candidates:
                    ordered.append(candidates.pop(0))
        grouped[sport] = ordered
    # First reserve one whole fixture per available provider. Otherwise a wide
    # sports matrix can hide a newly acquired provider behind the 60-row bound.
    interleaved, represented = [], set()
    for rows in grouped.values():
        for row in rows[:]:
            if row['provider'] not in represented:
                interleaved.append(row)
                represented.add(row['provider'])
                rows.remove(row)
    while any(grouped.values()) and len(interleaved) < 60:
        for rows in grouped.values():
            if rows and len(interleaved) < 60:
                interleaved.append(rows.pop(0))
    while len(json.dumps(interleaved).encode()) > 450_000:
        interleaved.pop()
    clocks = [s['lastSuccessAt'] for s in sources if s['usable']]
    return {'schemaVersion': 1, 'family': 'game' if game else 'sports', 'fixtures': interleaved,
        'props': props, 'sources': sources, 'generatedAt': max(clocks) if clocks else None,
        'availableFixtures': total, 'omittedFixtures': total - len(interleaved), 'bookmakerCoverage': coverage,
        'projectCounts': project_counts}


def attach_board(store, legacy, *, game=False):
    if store is None:
        return legacy
    board = read_board(store, game)
    # A live source and an official score have independent clocks. Preserve both.
    times = [x for x in (board['generatedAt'], legacy.get('generatedAt')) if x]
    result = {**legacy, 'officialGeneratedAt': legacy.get('generatedAt'), 'bookmakerBoard': board,
        'panelId': 'esports-intel' if game else 'sports-odds', 'generatedAt': max(times) if times else None}
    if board['generatedAt']:
        result['status'] = 'ok' if all(s['usable'] and not s['stale'] and not s['error'] for s in board['sources']) else 'degraded'
    # Reuse already-collected official statistics without another upstream read.
    from api.services.sports_expansion.snapshot_service import PRO_MATCHES, STANDINGS, TENNIS
    context = []
    for spec in ([PRO_MATCHES] if game else [STANDINGS, TENNIS]):
        data, meta = read_source(store, spec)
        rows = []
        for group in data.get('groups', []):
            for row in group.get('rows', [])[:15]:
                rows.append({'title': row['name'], 'value': f'{row.get("wins", "—"):g}–{row.get("losses", "—"):g}'
                    if isinstance(row.get('wins'), (float, int)) and isinstance(row.get('losses'), (float, int)) else '—',
                    'detail': group.get('name'), 'url': row.get('url')})
        for row in data.get('matches', [])[:15]:
            rows.append({'title': f'{row["radiant"]} · {row["dire"]}',
                'value': f'{row.get("radiantScore")}–{row.get("direScore")}', 'detail': row.get('league'), 'url': None})
        for row in data.get('tournaments', [])[:4]:
            rows.append({'title': row.get('name'), 'value': str(len(row.get('matches', []))), 'detail': 'ATP matches', 'url': row.get('url')})
        context.append({'rows': rows, 'source': meta})
    result['sportsContext'] = context
    return result
