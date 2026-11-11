"""Ordered WebSocket state machine. No network or storage side effects."""
from __future__ import annotations

from collections import Counter
import json
import time

from . import moviodds
from .model import GAMES, instant
from .movi_archive import point
from api.services.panel_evidence_store import iso

NAMESPACE = 'source:bookmakers:moviodds'
KEY = 'stream:v1'
LEASE_SECONDS = 45


def quote_key(q):
    # remove omits optional period/phase; removing this base identity removes
    # every period variant. The stored value still preserves all period fields.
    return str(q.get('group_id', '')), str(q.get('market_id') or ''), str(q.get('sel_id', ''))


def catalog(body, sports):
    value = json.loads(body)
    rows = value.get('fixtures') if isinstance(value, dict) else None
    if not isinstance(value, dict) or value.get('warming') or not isinstance(rows, list) or len(rows) > 10000 or value.get('count') != len(rows):
        raise ValueError('Invalid or incomplete MoviOdds catalog')
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid catalog row')
        if row.get('sport') not in sports:
            continue
        if not all(isinstance(row.get(k), str) and 0 < len(row[k]) <= 500 for k in ('id', 'home', 'away', 'league')):
            raise ValueError('Missing catalog identity')
        result.append(row)
    return result


class Stream:
    def __init__(self, sports):
        self.sports = sports
        self.metadata = {}
        self.matches = {}
        self.connected = False
        self.last_frame = None
        self.last_quote = None
        self.catalog_at = None
        self.error = 'connecting'
        self.feed = None
        self.counts = Counter()
        self.generation = 0

    def set_catalog(self, rows, now):
        self.metadata = {r['id']: r for r in rows}
        self.matches = {k: v for k, v in self.matches.items() if k in self.metadata}
        self.catalog_at = now

    def begin(self):
        self.generation += 1
        self.connected = True
        self.error = None
        self.feed = None
        # Never restore qualification from disk after reconnect/process restart.
        for state in self.matches.values():
            state['ready'] = False

    def disconnect(self, error):
        self.connected = False
        self.error = error
        for state in self.matches.values():
            state['ready'] = False

    def apply(self, msg, now):
        if not isinstance(msg, dict) or not isinstance(msg.get('type'), str):
            raise ValueError('Invalid WebSocket envelope')
        typ = msg['type']
        self.counts[typ] += 1
        self.last_frame = now
        if typ in ('lagged', 'resync'):
            for state in self.matches.values():
                state['ready'] = False
            self.error = 'resynchronizing'
            return
        if typ == 'error':
            raise ValueError('MoviOdds subscription rejected')
        if typ == 'feed':
            self.feed = msg.get('feed') if isinstance(msg.get('feed'), dict) else None
            return
        if typ in ('pong', 'subscribed'):
            return
        if typ == 'polled':
            polled = msg.get('groups') or {}
            if not isinstance(polled, dict) or len(polled) > 10000:
                raise ValueError('Invalid polled map')
            for fi, groups in polled.items():
                if not isinstance(groups, dict) or len(groups) > 1000:
                    raise ValueError('Invalid polled groups')
                state = self.matches.get(fi)
                if state and state['ready']:
                    for group, at in groups.items():
                        self._status(state, {group: {'polled_at': at}})
                    state['receivedAt'] = now
            return
        if typ not in ('snapshot', 'delta', 'remove', 'status', 'stats'):
            raise ValueError('Unknown WebSocket message type')
        fi = str(msg.get('fixture') or '')
        at = instant(msg.get('server_time'))
        if not fi or len(fi) > 100 or not at:
            raise ValueError('Missing WebSocket fixture/time')
        state = self.matches.get(fi)
        if state and at < state['serverTime']:
            self.counts['outOfOrder'] += 1
            return
        if typ == 'remove' and 'quotes' not in msg:
            self.matches.pop(fi, None)
            return
        if typ == 'snapshot':
            if len(self.matches) >= 10000 and fi not in self.matches:
                raise ValueError('WS fixture budget exceeded')
            state = {'quotes': {}, 'groups': {}, 'ready': True, 'serverTime': at, 'receivedAt': now}
            self.matches[fi] = state
        elif not state or not state['ready']:
            # A polled/delta cannot repair a missing baseline after loss.
            return
        if typ in ('snapshot', 'delta', 'remove'):
            rows = msg.get('quotes')
            if not isinstance(rows, list) or len(rows) > 5000:
                raise ValueError('Invalid WS price list')
            for q in rows:
                if not isinstance(q, dict) or not q.get('sel_id') or str(q.get('fixture_id') or fi) != fi:
                    raise ValueError('Invalid WS selection identity')
                key = quote_key(q)
                if typ == 'remove':
                    state['quotes'].pop(key, None)
                else:
                    point(q)
                    # Optional fields are replaced, never merged with stale ones.
                    state['quotes'][key] = {**q, 'phase': q.get('phase', 'prematch')}
            if len(state['quotes']) > 5000:
                raise ValueError('WS selection budget exceeded')
        if typ == 'stats':
            state['stats'] = msg.get('stats')
        self._status(state, msg.get('group_status') or {})
        state.update(serverTime=at, receivedAt=now)
        if typ == 'snapshot':
            self.error = None
        if typ in ('snapshot', 'delta') and msg.get('quotes'):
            self.last_quote = now

    @staticmethod
    def _status(state, groups):
        if not isinstance(groups, dict) or len(groups) > 1000:
            raise ValueError('Invalid market confirmation map')
        for group, status in groups.items():
            at = instant(status.get('polled_at')) if isinstance(status, dict) else None
            old = state['groups'].get(group, {})
            if at and at >= (old.get('polled_at') or ''):
                state['groups'][group] = {'polled_at': at, 'stale': status.get('stale') is True}

    def payload(self, now):
        connected = self.connected and self.last_frame is not None and now - self.last_frame < 45
        catalog_ok = self.catalog_at is not None and now - self.catalog_at < 180
        result = []
        for fi, state in self.matches.items():
            meta = self.metadata.get(fi)
            if not meta or meta['sport'] not in self.sports:
                continue
            row = {**meta, 'quotes': list(state['quotes'].values()), 'group_status': state['groups']}
            parsed = moviodds.parse(json.dumps({'matches': [row]}).encode(), meta['sport'])['fixtures']
            for event in parsed:
                received = iso(state['receivedAt'])
                feed = (self.feed or {}).get('sports', {}).get(meta['sport'], {})
                for q in event['quotes']:
                    lane = 'live' if q.get('phase') == 'inplay' else 'pre_match'
                    feed_ok = (self.feed or {}).get('state') == 'ok' and feed.get(lane, {}).get('state') == 'ok'
                    q.update(receivedAt=received, retentionSeconds=1800, sampleTier='stream',
                             sourceStale=q.get('sourceStale', False) or not state['ready'] or not connected or not catalog_ok or not feed_ok,
                             sourceError=self.error if not connected else None,
                             streamValidUntil=iso(now + LEASE_SECONDS) if connected and catalog_ok else iso(now),
                             fixtureId=fi, sportKey=meta['sport'])
                event.update(fetchedAt=received, sourceStale=not connected or not catalog_ok,
                             sourceError=self.error, tier='stream')
                result.append(event)
        return {'schemaVersion': 1, 'generatedAt': iso(now), 'lastFrameAt': iso(self.last_frame), 'lastQuoteAt': iso(self.last_quote),
                'catalogAt': iso(self.catalog_at), 'connected': connected, 'validUntil': iso(now + LEASE_SECONDS),
                'error': self.error, 'generation': self.generation, 'messageCounts': dict(self.counts), 'fixtures': result}


def read_stream(store, game, now=None):
    now = time.time() if now is None else now
    value = store.get_stale(NAMESPACE, KEY) or {}
    fixtures = [f for f in value.get('fixtures', []) if (f['sport'] in GAMES) == game]
    lease = instant(value.get('validUntil'))
    healthy = bool(value.get('connected') and lease and lease > iso(now))
    if not healthy:
        fixtures = [{**f, 'sourceStale': True, 'quotes': [{**q, 'sourceStale': True, 'sourceError': 'stream-disconnected'} for q in f['quotes']]} for f in fixtures]
    fixtures = [f for f in fixtures if f.get('fetchedAt') and f['fetchedAt'] >= iso(now - 1800)]
    meta = {'id': 'bookmakers:movi:stream:v1', 'label': 'bet365 · MoviOdds stream',
            'usable': bool(value.get('lastQuoteAt')), 'stale': not healthy, 'error': value.get('error'),
            'lastSuccessAt': value.get('lastQuoteAt'), 'fixtureCount': len(fixtures),
            'quoteCount': sum(len(f['quotes']) for f in fixtures)}
    return fixtures, meta
