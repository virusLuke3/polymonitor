"""Bounded asynchronous owner; public requests only consume its Redis projection."""
import json
import re
import time
from urllib.parse import urlsplit

from api.services.market_service import read_query, market_rows
from market.market_serving_identity import binary_serving_identity_sql
from data_sources import source_value
from .matching import Aliases, VERSION, SPORT_PREFIX, assess, identity, market_links, compatible_selection
from .movi_archive import configured_int

NAMESPACE, SNAPSHOT = 'source:bookmakers:matching', 'snapshot:v1'


def aliases():
    return Aliases(json.loads(source_value('POLYDATA_ODDS_MATCH_ALIASES_JSON') or '[]'))


def evidence_rows(rows):
    fields = ('id', 'gamma_market_id', 'slug', 'title', 'event_id', 'event_slug', 'event_title',
              'condition_id', 'yes_token_id', 'no_token_id', 'description',
              'quote_token_ids', 'quote_labels', 'quote_condition_id')
    return [{k: r.get(k) for k in fields} for r in rows]


class Catalog:
    def __init__(self, settings):
        self.settings = settings

    def query(self, sql, params=()):
        s = self.settings
        return read_query(lambda p: s.database.connect(p, readonly=True, connect_timeout=3), s.database.sqlite_path, sql, params)

    def candidates(self, fixture):
        # Team suffix blocks are for recall only. Full identities are checked
        # independently by assess(); Academy/Women etc. are never stripped there.
        def term(label):
            words = re.findall(r'\w+', label, flags=re.UNICODE)
            useful = [w for w in words if w.casefold() not in {'team', 'esports', 'gaming', 'fc', 'club'}]
            return useful[-1] if useful else words[-1] if words else ''
        text = term(fixture['home']) + ' ' + term(fixture['away'])
        rows = market_rows(self.query,
            "m.active IS TRUE AND m.closed IS FALSE AND "
            "to_tsvector('simple', coalesce(m.title,'') || ' ' || coalesce(m.slug,'') || ' ' || coalesce(m.category,'')) "
            "@@ plainto_tsquery('simple', ?) AND m.slug ~ ?",
            (text, '-[0-9]{4}-[0-9]{2}-[0-9]{2}$'), limit=21)
        return rows[:20], len(rows) > 20

    def markets(self, event):
        # Outcome labels are identity evidence even when a quote is old. The
        # general catalog drops old quotes altogether; keep their clock here,
        # with a separate UI freshness gate, rather than losing token mappings.
        rows = self.query(f'''SELECT m.*, q.token_ids AS quote_token_ids,
            q.outcome_labels AS quote_labels, q.outcome_prices AS quote_prices,
            q.condition_id AS quote_condition_id, q.source_updated_at AS quote_updated_at,
            q.observed_at AS quote_observed_at
            FROM core.markets m LEFT JOIN core.market_quote_current q
            ON q.gamma_market_id=m.gamma_market_id AND q.condition_id=m.condition_id
            AND q.token_ids @> jsonb_build_array(m.yes_token_id,m.no_token_id)
            WHERE m.event_id=? AND m.active IS TRUE AND m.closed IS FALSE
            AND {binary_serving_identity_sql('m', qualified_ops=True)}
            ORDER BY m.id LIMIT 201''', (event['pmEventId'],))
        return rows[:200], len(rows) > 200


def run_cycle(store, archive, catalog, *, now=None):
    from .snapshot_service import read_board
    now = time.time() if now is None else now
    a = aliases()
    deadline = time.monotonic() + 90
    max_jobs = configured_int('POLYDATA_ODDS_MATCH_JOBS', 30, 1, 100)
    decisions = archive.decisions()
    inventory = [f for game in (False, True) for f in read_board(store, game, inventory=True)['fixtures']]
    unique = {identity(f): f for f in inventory}
    due = [(k, f) for k, f in unique.items() if f['sport'] in set(SPORT_PREFIX.values()) and
           (decisions.get(k, {}).get('_due', 0) <= now or decisions.get(k, {}).get('aliasVersion') != a.version)]
    due.sort(key=lambda x: decisions.get(x[0], {}).get('checkedAt', 0))
    grouped = {}
    for item in due:
        grouped.setdefault(item[1]['sport'], []).append(item)
    due = []
    while any(grouped.values()):
        for queue in grouped.values():
            if queue:
                due.append(queue.pop(0))
    counts = {'checked': 0, 'linked': 0, 'errors': 0, 'inventory': len(unique), 'due': len(due)}
    for k, f in due[:max_jobs]:
        if time.monotonic() >= deadline:
            break
        evidence = {'aliases': a.rows}
        try:
            rows, truncated = catalog.candidates(f)
            evidence['candidates'] = evidence_rows(rows)
            result, e = assess(f, rows, a, truncated=truncated)
            result['markets'] = []
            if e:
                time.sleep(.15)  # Share the same host read budget with interactive panels.
                rows, more = catalog.markets(e)
                evidence['markets'] = evidence_rows(rows)
                result['marketCoverage'] = 'truncated' if more else 'complete'
                result['markets'] = market_links(e, rows)
            delay = 300 if result['state'] == 'linked' else 1800
            result['verifiedAt'] = time.time()
        except Exception as exc:
            # No exception text: database/proxy diagnostics can contain secrets.
            old = decisions.get(k, {})
            verified = old.get('verifiedAt', old.get('checkedAt', 0))
            retained = {field: old[field] for field in ('pmEventId', 'eventId', 'title', 'firstLinkedAt', 'markets', 'candidates', 'marketCoverage') if field in old} if now - verified <= 86400 else {}
            result = {'markets': [], 'candidates': [], **retained, 'state': 'unavailable',
                      'verifiedAt': verified, 'reason': 'catalog_' + type(exc).__name__}
            delay = min(1800, 120 * 2 ** min(decisions.get(k, {}).get('_failures', 0), 4))
            counts['errors'] += 1
        result.update(version=VERSION, identity=k, aliasVersion=a.version)
        saved = archive.save(k, f, result, evidence, time.time(), delay)
        decisions[k] = saved
        counts['checked'] += 1
        counts['linked'] += int(result['state'] == 'linked')
        time.sleep(.15)
    archive.prune(now)
    # One bounded public projection. Raw rules and audit history remain private.
    public = {k: {field: value for field, value in d.items() if not field.startswith('_')}
              for k, d in decisions.items() if k in unique}
    for k, d in public.items():
        d['availableMarkets'] = len(d.get('markets', []))
        candidates = sorted(d.get('markets', []), key=lambda m: (
            m['type'] != 'h2h',
            not any(compatible_selection(unique[k], q, m, a) for q in unique[k]['quotes']),
            m['type'], m['line'] or ''))
        # Reserve room for every supported type; alternate spreads must not
        # push the winner and totals out of a bounded public projection.
        groups = {kind: [m for m in candidates if m['type'] == kind] for kind in ('h2h', 'spreads', 'totals')}
        projected = []
        while any(groups.values()) and len(projected) < 24:
            for queue in groups.values():
                if queue and len(projected) < 24:
                    projected.append(queue.pop(0))
        d['markets'] = projected
    value = {'version': VERSION, 'generatedAt': time.time(), 'decisions': public, 'counts': counts, 'aliases': a.rows}
    if len(json.dumps(value, default=str).encode()) > 2 * 1024**2:
        raise ValueError('Matching projection capacity reached')
    if not store.set(NAMESPACE, SNAPSHOT, json.loads(json.dumps(value, default=str)), ttl_seconds=86400):
        raise RuntimeError('Matching projection publication failed')
    return counts


def attach_matches(store, fixtures, *, now=None):
    now = time.time() if now is None else now
    snapshot = (store.get_stale(NAMESPACE, SNAPSHOT) if store is not None else None) or {}
    a = Aliases(snapshot.get('aliases', []))
    template = source_value('POLYDATA_ODDS_MATCH_MARKET_URL_TEMPLATE')
    result = []
    for f in fixtures:
        d = snapshot.get('decisions', {}).get(identity(f))
        if not d:
            state = 'pending' if f['sport'] in set(SPORT_PREFIX.values()) else 'unsupported'
            result.append({**f, 'polymarketMatch': {'state': state, 'reason': 'awaiting_catalog_check' if state == 'pending' else 'sport_not_supported', 'markets': []}})
            continue
        expired = d['state'] == 'unavailable' or now - d.get('verifiedAt', d.get('checkedAt', 0)) > 600 or now - snapshot.get('generatedAt', 0) > 600
        d = {**d, 'stale': expired, 'markets': []}
        for m in snapshot['decisions'][identity(f)].get('markets', []):
            matching = []
            for q in f['quotes']:
                pairs = compatible_selection(f, q, m, a)
                if pairs:
                    matching.append({'book': q['book'], 'provider': q['provider'], 'pairs': pairs})
            event_slug = m.get('eventSlug') or next((x['slug'] for x in snapshot['decisions'][identity(f)].get('markets', []) if x['type'] == 'h2h'), None)
            url = template.replace('{event_slug}', event_slug).replace('{slug}', m['slug']) if template and event_slug else None
            parsed = urlsplit(url or '')
            url = url if parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password else None
            d['markets'].append({**m, 'url': url, 'books': matching[:80], 'comparisonReady': False})
        result.append({**f, 'polymarketMatch': d})
    return result
