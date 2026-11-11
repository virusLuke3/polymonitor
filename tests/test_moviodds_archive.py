import asyncio
import json
import time
from datetime import datetime, timezone

import pytest

from scripts.api.services.bookmaker_panels.movi_archive import Archive, encode, unpack
from scripts.api.services.bookmaker_panels.movi_history import run_job, parse_closing, parse_results
from scripts.api.services.bookmaker_panels.movi_reads import read
from scripts.api.services.bookmaker_panels.movi_stream import Stream, catalog, read_stream, NAMESPACE, KEY
from scripts.runtime.snapshot_store import SnapshotStore

NOW = 1700000000.0


def stamp(at=NOW):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def price(**changes):
    return dict(group_id='1510001', market_id='m', sel_id='h', group_name='Match Lines',
                line='To Win', side='Alpha', odds_dec=1.8, ts=stamp(), **changes)


def frame(kind='snapshot', rows=None, **changes):
    return dict(type=kind, fixture='f', server_time=stamp(), quotes=rows if rows is not None else [price()], **changes)


def meta():
    return {'id': 'f', 'sport': 'esports', 'league': 'CS2 - Test', 'home': 'Alpha', 'away': 'Beta', 'kickoff_utc': stamp(NOW+3600)}


@pytest.fixture
def archive(tmp_path):
    a = Archive(tmp_path/'movi.sqlite3'); a.initialize()
    a.catalog(encode({'fixtures': [meta()]}), [meta()], NOW, 7)
    return a


def test_snapshot_delta_removal_and_resync_are_not_merges():
    s = Stream(['esports']); s.begin()
    s.apply(frame(rows=[price(suspended=True)]), NOW)
    s.apply(frame('delta'), NOW+1)
    assert 'suspended' not in next(iter(s.matches['f']['quotes'].values()))
    s.apply({'type': 'lagged'}, NOW+2)
    s.apply(frame('delta'), NOW+3)
    assert not s.matches['f']['ready']
    s.apply(frame(rows=[]), NOW+4)
    assert s.matches['f']['ready'] and not s.matches['f']['quotes']
    s.apply(frame(), NOW+5)
    s.apply(frame('remove', [{'group_id': '1510001', 'market_id': 'm', 'sel_id': 'h'}]), NOW+6)
    assert not s.matches['f']['quotes']
    s.apply(frame(), NOW+7)
    s.apply({'type': 'remove', 'fixture': 'f', 'server_time': stamp()}, NOW+8)
    assert 'f' not in s.matches


def test_remove_tombstone_empty_fixture_and_zero_suspended_price(archive):
    s = Stream(['esports']); s.begin(); s.apply(frame(), NOW)
    tombstone = {'fixture_id': '', 'group_id': '1510001', 'market_id': 'm', 'sel_id': 'h',
                 'odds_dec': 0, 'ts': '0001-01-01T00:00:00Z'}
    s.apply(frame('remove', [tombstone]), NOW+1)
    assert not s.matches['f']['quotes']
    msg = frame(rows=[{**price(), 'odds_dec': 0, 'suspended': True}])
    archive.frames([(encode(msg), msg, NOW)])
    with archive.connection() as db:
        saved = unpack(db.execute('SELECT data FROM points').fetchone()[0])
    assert saved['odds_dec'] is None and saved['suspended'] is True
    closing = {'fixture_id': 'f', 'closed': True, 'pre_close_basis': 'omitted', 'selection_count': 1,
               'selections': [{**price(), 'last': {**price(), 'odds_dec': 0, 'suspended': True}}]}
    assert parse_closing(encode(closing), 'f')['selections'][0]['last']['odds_dec'] is None


def test_connection_and_per_market_clocks_require_new_baseline():
    s = Stream(['esports']); s.set_catalog([meta()], NOW); s.begin()
    s.apply(frame(), NOW)
    s.apply({'type': 'polled', 'groups': {'f': {'1510001': stamp(NOW+20), 'other': stamp(NOW+10)}}}, NOW+20)
    assert next(iter(s.matches['f']['quotes'].values()))['ts'] == stamp()
    assert s.matches['f']['groups']['1510001']['polled_at'] == stamp(NOW+20)
    s.apply({'type': 'polled', 'groups': {'f': {'1510001': stamp(NOW-1)}}}, NOW+21)
    assert s.matches['f']['groups']['1510001']['polled_at'] == stamp(NOW+20)
    s.disconnect('network'); s.begin()
    s.apply(frame('delta'), NOW+22)
    assert not s.matches['f']['ready']
    s.apply(frame(), NOW+23)
    assert s.matches['f']['ready'] and s.generation == 2
    s.apply({**frame(rows=[]), 'server_time': stamp(NOW-1)}, NOW+24)
    assert len(s.matches['f']['quotes']) == 1
    assert s.counts['outOfOrder'] == 1


def test_failed_feed_catalog_or_redis_lease_never_qualifies_prices(tmp_path):
    s = Stream(['esports']); s.set_catalog([meta()], NOW); s.begin()
    away = {**price(), 'sel_id': 'a', 'side': 'Beta', 'odds_dec': 2.1}
    s.apply(frame(rows=[price(), away]), NOW)
    s.apply({'type': 'feed', 'feed': {'state': 'ok', 'sports': {'esports': {'pre_match': {'state': 'ok'}}}}}, NOW)
    payload = s.payload(NOW)
    assert payload['fixtures'] and not payload['fixtures'][0]['quotes'][0]['sourceStale']
    assert s.payload(NOW+181)['fixtures'][0]['quotes'][0]['sourceStale']
    store = SnapshotStore(str(tmp_path/'seed.sqlite3')); store.set(NAMESPACE, KEY, payload, 60)
    fixtures, status = read_stream(store, True, NOW+46)
    assert status['stale'] and fixtures[0]['quotes'][0]['sourceStale']


def test_duplicate_frames_keep_first_receipt_and_failed_batch_is_atomic(archive):
    msg = frame(); batch = [(encode(msg), msg, NOW)]
    archive.frames(batch); archive.frames([(encode(msg), msg, NOW+100)])
    with archive.connection() as db:
        assert db.execute('SELECT count(*) FROM points').fetchone()[0] == 1
        assert db.execute('SELECT received FROM points').fetchone()[0] == NOW
    corrupt = frame(rows=[{**price(), 'odds_dec': -2}])
    with pytest.raises(ValueError):
        archive.frames([(encode(frame('resync')), frame('resync'), NOW+200), (encode(corrupt), corrupt, NOW+200)])
    with archive.connection() as db:
        assert db.execute("SELECT count(*) FROM raw WHERE kind='ws:resync'").fetchone()[0] == 0


def test_restart_history_cursor_overlap_and_no_failed_advance(archive):
    task = archive.due(NOW, 'history')
    calls = []
    def page(path, params, deadline):
        calls.append(params)
        return encode({'fixture_id': 'f', 'count': 1, 'truncated': len(calls) == 1,
                       'points': [{**price(), 'ts': stamp(NOW-100)}]})
    run_job(archive, task, 9999, read=page, now=NOW)
    resumed = Archive(archive.path).due(NOW+31, 'history')
    assert json.loads(resumed['cursor'])['complete'] is False
    run_job(archive, resumed, 9999, read=page, now=NOW+31)
    assert calls[1]['to'] == stamp(NOW-100)
    with archive.connection() as db:
        row = db.execute('SELECT * FROM tasks WHERE key=?', (task['key'],)).fetchone()
        assert json.loads(row['cursor'])['complete'] is True
        assert db.execute('SELECT count(*) FROM points').fetchone()[0] == 1
        cursor = row['cursor']
    def bad(*args):
        return encode({'fixture_id': 'wrong', 'count': 0, 'points': [], 'truncated': False})
    with pytest.raises(ValueError): run_job(archive, dict(row), 9999, read=bad, now=NOW+4000)
    with archive.connection() as db:
        assert db.execute('SELECT cursor FROM tasks WHERE key=?', (task['key'],)).fetchone()[0] == cursor


def test_full_timestamp_page_cannot_silently_skip(archive):
    task = archive.due(NOW, 'history')
    task['cursor'] = json.dumps({'scope': 'primary-groups-v1', 'groups': ['1510001'], 'groupIndex': 0, 'to': stamp(), 'from': stamp(NOW-86400)})
    def page(*args): return encode({'fixture_id': 'f', 'count': 1, 'truncated': True, 'points': [price()]})
    with pytest.raises(ValueError, match='boundary'): run_job(archive, task, 9999, read=page, now=NOW)


def test_multiple_primary_groups_must_all_complete_before_window_is_complete(archive):
    task = {**archive.due(NOW, 'history'), 'sport': 'basketball'}
    groups = []
    def page(path, params, deadline):
        groups.append(params['group'])
        return encode({'fixture_id': 'f', 'count': 0, 'points': [], 'truncated': False})
    run_job(archive, task, 9999, read=page, now=NOW)
    with archive.connection() as db:
        cursor = db.execute('SELECT cursor FROM tasks WHERE key=?', (task['key'],)).fetchone()[0]
    assert json.loads(cursor)['complete'] is False
    run_job(archive, {**task, 'cursor': cursor}, 9999, read=page, now=NOW+31)
    with archive.connection() as db:
        cursor = db.execute('SELECT cursor FROM tasks WHERE key=?', (task['key'],)).fetchone()[0]
    assert json.loads(cursor)['complete'] is True and groups == ['1453', '112']


def test_closing_semantics_results_provenance_and_read_only_views(archive):
    closing = {'fixture_id': 'f', 'closed': False, 'pre_close_basis': 'omitted', 'selection_count': 1,
               'selections': [{**price(), 'last': {'ts': stamp(), 'odds_dec': 1.8}}]}
    assert parse_closing(encode(closing), 'f')['closed'] is False
    closing['selections'][0]['pre_close'] = closing['selections'][0]['last']
    with pytest.raises(ValueError): parse_closing(encode(closing), 'f')
    data = {'date': '2023-11-14', 'sport': 'esports', 'source': 'memory', 'count': 1, 'results': [
        {'fixture_id': 'f', 'sport': 'esports', 'league': 'CS2 - Test', 'home': 'Alpha', 'away': 'Beta',
         'status': 'unknown', 'final_score': '1-0', 'finished_at': stamp()}]}
    parse_results(encode(data), data['date'])
    archive.result_tasks(['esports'], 1, NOW)
    task = archive.due(NOW+1, 'results')
    run_job(archive, task, 9999, read=lambda *args: encode(data), now=NOW)
    archive.frames([(encode(frame()), frame(), NOW)])
    query = dict(sport='cs2', fixture='f', selection='', offset=0, limit=20)
    value = read(query, archive)
    assert value['result']['data']['status'] == 'unknown'
    assert value['result']['data']['archiveSource'] == 'memory'
    assert value['points'][0]['firstReceivedAt'] == stamp()
    with pytest.raises(LookupError): read({**query, 'sport': 'nba'}, archive)
    with archive.connection() as db, pytest.raises(Exception):
        db.execute('DELETE FROM points')


def test_capacity_failure_and_retention_maintenance_are_separate(archive):
    archive.frames([(encode(frame()), frame(), NOW)])
    archive.max_bytes = 1
    with pytest.raises(ValueError, match='capacity'): archive.frames([(encode(frame()), frame(), NOW+1)])
    archive.prune(NOW+31*86400)
    with archive.connection() as db:
        assert db.execute('SELECT count(*) FROM points').fetchone()[0] == 0


def test_invalid_catalog_is_not_successful_empty():
    for value in ([], {'fixtures': [], 'count': 0, 'warming': True}, {'fixtures': [{}], 'count': 0}):
        with pytest.raises(ValueError): catalog(encode(value), ['esports'])
    assert catalog(encode({'fixtures': [], 'count': 0}), ['esports']) == []


def test_collector_does_not_apply_failed_write(monkeypatch):
    monkeypatch.setenv('POLYDATA_MOVIODDS_BASE_URL', 'https://source.example')
    from scripts.runtime.moviodds_watcher import Owner
    async def scenario():
        class Store:
            def set(self, *args): return True
        class Broken:
            def frames(self, batch): raise OSError('disk full')
        owner = Owner(Store(), Broken())
        queue = asyncio.Queue(); await queue.put((encode(frame()), frame(), NOW))
        with pytest.raises(OSError): await owner.consume(queue)
        assert owner.state.last_quote is None
    asyncio.run(scenario())
