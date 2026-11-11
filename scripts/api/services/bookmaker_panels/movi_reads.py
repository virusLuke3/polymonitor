"""Read-only, bounded historical projections for the existing Sports/Game UI."""
from __future__ import annotations

import json
import time

from api.services.panel_evidence_store import iso
from .movi_archive import Archive, unpack, selection_key
from .moviodds import GROUPS


def read(query, archive=None):
    archive = archive or Archive()
    with archive.connection() as db:
        fi, sport, selection = query['fixture'], query['sport'], query['selection']
        offset, limit = query['offset'], query['limit']
        if not fi:
            where, args = ('WHERE project=?', [sport]) if sport else ('', [])
            count = db.execute('SELECT count(*) FROM fixtures ' + where, args).fetchone()[0]
            rows = db.execute('SELECT * FROM fixtures f ' + where +
                " ORDER BY EXISTS(SELECT 1 FROM documents d WHERE d.fixture=f.id AND d.kind='result') DESC,received DESC,id LIMIT ? OFFSET ?",
                [*args, limit, offset]).fetchall()
            items = []
            for row in rows:
                meta = unpack(row['data'])
                items.append({'id': row['id'], 'sport': row['project'], 'home': meta['home'], 'away': meta['away'],
                              'league': meta.get('league', ''), 'kickoff': meta.get('kickoff_utc'),
                              'receivedAt': iso(row['received'])})
            result = {'items': items, 'total': count, 'nextOffset': offset + len(items) if offset + len(items) < count else None}
            received = max((row['received'] for row in rows), default=None)
        else:
            meta_row = db.execute('SELECT * FROM fixtures WHERE id=?', (fi,)).fetchone()
            if meta_row is None or sport and meta_row['project'] != sport:
                raise LookupError('MoviOdds fixture not in archive scope')
            docs = {r['kind']: {'data': unpack(r['data']), 'receivedAt': iso(r['received'])}
                    for r in db.execute('SELECT * FROM documents WHERE fixture=?', (fi,))}
            tasks = [{**dict(r), 'cursor': json.loads(r['cursor'])} for r in db.execute(
                'SELECT kind,checked,error,cursor FROM tasks WHERE fixture=?', (fi,))]
            where, args = ('fixture=? AND selection=?', [fi, selection]) if selection else ('fixture=?', [fi])
            total = db.execute('SELECT count(*) FROM points WHERE ' + where, args).fetchone()[0]
            # Newest page first; values in each page are rendered chronologically.
            prices = db.execute('SELECT * FROM points WHERE ' + where + ' ORDER BY ts DESC,id DESC LIMIT ? OFFSET ?', [*args, limit, offset]).fetchall()
            selections = db.execute('SELECT selection,MAX(ts) AS latest FROM points WHERE fixture=? GROUP BY selection ORDER BY latest DESC LIMIT 200', (fi,)).fetchall()
            options = []
            for s in selections:
                p = db.execute('SELECT data FROM points WHERE fixture=? AND selection=? ORDER BY ts DESC LIMIT 1', (fi, s['selection'])).fetchone()
                q = unpack(p[0])
                options.append({'key': s['selection'], 'label': ' · '.join(str(q.get(k) or '') for k in ('group_name', 'side', 'label', 'line', 'handicap')).strip(' ·') or q['sel_id']})
            closing = docs.get('closing')
            if closing:
                candidates = closing['data']['selections']
                if selection:
                    candidates = [r for r in candidates if selection_key(r) == selection]
                candidates = sorted(candidates, key=lambda r: str(r.get('group_id')) not in GROUPS.get(meta_row['sport'], ()))
                closing = {**closing, 'data': {**closing['data'], 'selections': candidates[:200]},
                           'omittedSelections': max(0, len(candidates) - 200)}
            result = {'fixture': unpack(meta_row['data']), 'project': meta_row['project'], 'selections': options,
                      'selectionLimit': 200, 'points': [{**unpack(r['data']), 'firstReceivedAt': iso(r['received']),
                          'channel': r['channel']} for r in reversed(prices)], 'total': total,
                      'nextOffset': offset + len(prices) if offset + len(prices) < total else None,
                      'closing': closing, 'result': docs.get('result'), 'tasks': tasks}
            received = max([meta_row['received'], *[r['received'] for r in prices], *[t['checked'] for t in tasks if t['checked']]])
        result.update(schemaVersion=1, query=query, generatedAt=iso(received) if received else None,
                      observedAt=iso(time.time()))
        if len(json.dumps(result).encode()) > 450000:
            raise ValueError('MoviOdds historical projection exceeds byte budget')
        return result
