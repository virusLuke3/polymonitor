"""Bounded REST archive jobs. Cursors only advance with the evidence commit."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from urllib.parse import urlencode, urlsplit

from api.clients.source_transport import _retry_seconds, source_session, read_with_retry, read_response_bytes
from data_sources import source_value
from .model import instant
from .movi_archive import configured_int, point
from .moviodds import GROUPS


def request(path, params, deadline):
    base = source_value('POLYDATA_MOVIODDS_BASE_URL')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query:
        raise ValueError('MoviOdds source is not configured')
    key = source_value('POLYDATA_MOVIODDS_API_KEY')
    with source_session() as session:
        session.trust_env = False
        return read_with_retry(session, base.rstrip('/') + path + '?' + urlencode(params),
            lambda r: read_response_bytes(r, 8 * 1024**2, deadline=deadline), attempts=2,
            require_full_attempt=True, respect_retry_after=True, timeout=45, deadline=deadline, stream=True,
            headers={'Accept-Encoding': 'gzip', **({'X-API-Key': key} if key else {})})


def parse_history(raw, fi, lower, upper):
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('fixture_id') != fi or not isinstance(data.get('points'), list):
        raise ValueError('Invalid history identity')
    ids = data.get('fixture_ids', [fi])
    if not isinstance(ids, list) or fi not in ids or len(ids) > 20 or not all(isinstance(i, str) for i in ids):
        raise ValueError('Invalid merged history identity')
    if data.get('count') != len(data['points']) or len(data['points']) > 5000 or not isinstance(data.get('truncated'), bool):
        raise ValueError('Invalid history coverage')
    for row in data['points']:
        p = point(row)
        if str(p.get('fixture_id', fi)) not in ids or not lower <= p['ts'] <= upper:
            raise ValueError('History outside requested identity/window')
    return data


def parse_closing(raw, fi):
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('fixture_id') != fi or not isinstance(data.get('selections'), list):
        raise ValueError('Invalid closing identity')
    if len(data['selections']) > 20000 or data.get('selection_count') != len(data['selections']):
        raise ValueError('Invalid closing coverage')
    if not isinstance(data.get('closed'), bool) or data.get('pre_close_basis') not in ('kickoff', 'prematch-records', 'omitted'):
        raise ValueError('Unknown closing semantics')
    kickoff = instant(data.get('kickoff_utc'))
    for row in data['selections']:
        for which in ('pre_close', 'last'):
            if row.get(which) is not None:
                p = point({**row, **row[which]})
                if which == 'pre_close' and (data['pre_close_basis'] == 'omitted' or
                        data['pre_close_basis'] == 'kickoff' and (not kickoff or data.get('kickoff_estimated') or p['ts'] > kickoff)):
                    raise ValueError('Invalid pre-match closing basis')
                row[which] = p
    return data


def parse_results(raw, day):
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('results'), list) or data.get('date') != day:
        raise ValueError('Invalid results scope')
    if len(data['results']) > 20000 or data.get('count') != len(data['results']) or data.get('source') not in ('postgres', 'memory'):
        raise ValueError('Invalid result archive coverage')
    for row in data['results']:
        if not all(isinstance(row.get(k), str) and row[k] for k in ('fixture_id', 'sport', 'home', 'away')) or row.get('status') not in ('finished', 'unknown'):
            raise ValueError('Invalid result identity/status')
        if not instant(row.get('finished_at')) or not isinstance(row.get('final_score'), str):
            raise ValueError('Invalid result clock/score')
    return data


def run_job(archive, task, deadline, *, read=request, now=None):
    realtime = now is None
    now = time.time() if now is None else now
    fi, kind = task['fixture'], task['kind']
    cursor = json.loads(task['cursor'])
    if kind == 'history':
        groups = list(GROUPS[task['sport']])
        if cursor.get('scope') != 'primary-groups-v1' or cursor.get('groups') != groups:
            cursor = {'scope': 'primary-groups-v1', 'groups': groups, 'groupIndex': 0}
        group_index = cursor.get('groupIndex', 0)
        lookback = configured_int('POLYDATA_MOVIODDS_LOOKBACK_DAYS', 7, 1, 30)
        upper = cursor.get('to') or datetime.fromtimestamp(now, timezone.utc).isoformat()
        lower = cursor.get('from') or datetime.fromtimestamp(now - lookback * 86400, timezone.utc).isoformat()
        body = read('/history', {'fi': fi, 'group': groups[group_index], 'from': lower, 'to': upper, 'limit': 5000}, deadline)
        data = parse_history(body, fi, lower, upper)
        if any(str(p['group_id']) != groups[group_index] for p in data['points']):
            raise ValueError('History market scope mismatch')
        if data['truncated']:
            oldest = min((instant(p['ts']) for p in data['points']), default=None)
            # Inclusive overlap avoids losing simultaneous changes. A page full
            # of one timestamp needs finer source filtering, not silent skipping.
            if not oldest or oldest >= upper or oldest == cursor.get('to'):
                raise ValueError('History timestamp boundary remains truncated')
            cursor = {**cursor, 'from': lower, 'to': oldest, 'windowEnd': cursor.get('windowEnd', upper), 'complete': False}
            due = now + 30
        else:
            # The next scan overlaps the prior window, then walks back if capped.
            end = cursor.get('windowEnd', upper)
            if group_index + 1 < len(groups):
                cursor = {**cursor, 'from': lower, 'to': end, 'windowEnd': end, 'groupIndex': group_index + 1, 'complete': False}
                due = now + 30
            else:
                cursor = {'scope': 'primary-groups-v1', 'groups': groups, 'groupIndex': 0,
                          'from': end, 'complete': True, 'coveredFrom': cursor.get('coveredFrom', lower), 'coveredTo': end}
                due = now + 3600
    elif kind == 'closing':
        body = read('/closing', {'fi': fi}, deadline)
        data = parse_closing(body, fi)
        cursor = {'closed': data['closed'], 'preCloseBasis': data['pre_close_basis']}
        due = now + (86400 if data['closed'] else 900)
    else:
        body = read('/results', {'sport': task['sport'], 'date': fi, 'stats': 1}, deadline)
        data = parse_results(body, fi)
        if data.get('sport') != task['sport'] or any(r['sport'] != task['sport'] for r in data['results']):
            raise ValueError('Results sport mismatch')
        cursor = {'source': data['source'], 'records': len(data['results'])}
        today = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        due = now + (900 if fi == today or data['source'] == 'memory' else 21600)
    archive.save(task, body, data, cursor=cursor, next_due=due, now=time.time() if realtime else now)
    return kind, len(data.get('points', data.get('selections', data.get('results', []))))


def collect(archive, sports, should_stop=lambda: False):
    deadline = time.monotonic() + 180
    budget = configured_int('POLYDATA_MOVIODDS_REST_REQUESTS_PER_CYCLE', 6, 3, 30)
    lookback = configured_int('POLYDATA_MOVIODDS_LOOKBACK_DAYS', 7, 1, 30)
    archive.result_tasks(sports, lookback, time.time())
    results = []
    # Independent lanes: a large history backlog cannot block results/closing.
    for index in range(budget):
        if should_stop() or deadline - time.monotonic() < 45:
            break
        task = archive.due(time.time(), ('results', 'history', 'closing')[index % 3])
        if not task:
            continue
        try:
            results.append(run_job(archive, task, deadline))
        except Exception as exc:
            response = getattr(exc, 'response', None)
            code = response.status_code if response is not None else None
            delay = min(3600, 60 * 2**min(task['failures'], 6))
            if code in (429, 503):
                delay = max(delay, _retry_seconds(response.headers.get('Retry-After')))
            if code in (401, 403):
                delay = max(delay, 3600)
            archive.fail(task, f'HTTP {code}' if code else type(exc).__name__, delay, time.time())
            results.append((task['kind'], 'failed'))
            if code in (401, 403, 429, 503):
                break
    return results
