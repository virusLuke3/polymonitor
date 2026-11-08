import json
from contextlib import contextmanager
import pytest
from api.services import panel_evidence_store as evidence
from api.services import weather_expansion as weather
from runtime.snapshot_store import SnapshotStore


def test_failed_refresh_preserves_original_clock_and_expires(tmp_path, monkeypatch):
    monkeypatch.setenv('POLYMONITOR_EXTERNAL_EVIDENCE_SQLITE_PATH', str(tmp_path/'archive.db'))
    monkeypatch.setenv('TEST_SOURCE_URL','https://example.invalid/source')
    store=SnapshotStore(str(tmp_path/'snapshot.db'))
    spec=evidence.SourceSpec('test','Test','TEST_SOURCE_URL',json.loads,cadence=300,stale_after=600,retain_for=1200)
    state=evidence.collect_one(store,spec,acquire=lambda:(b'{"value":4}',{'value':4}),now=10000)
    assert state['lastSuccessAt']==10000
    def fail(): raise ConnectionError('a proxy secret must never leak')
    state=evidence.collect_one(store,spec,acquire=fail,now=10700)
    data,meta=evidence.read_source(store,spec,now=10700)
    assert data=={'value':4} and meta['stale'] and state['lastSuccessAt']==10000
    assert state['error']=='ConnectionError' and state['nextAttemptAt']>10700
    assert evidence.read_source(store,spec,now=11201)[0]=={}


def test_healthy_empty_replaces_old_data_and_write_failure_is_not_success(tmp_path, monkeypatch):
    monkeypatch.setenv('POLYMONITOR_EXTERNAL_EVIDENCE_SQLITE_PATH', str(tmp_path/'archive.db'))
    store=SnapshotStore(str(tmp_path/'snapshot.db')); spec=evidence.SourceSpec('test','Test','X',json.loads)
    evidence.collect_one(store,spec,acquire=lambda:(b'1',{'items':[1]}),now=10000)
    state=evidence.collect_one(store,spec,acquire=lambda:(b'2',{'items':[]}),now=15000)
    assert state['data']=={'items':[]}
    monkeypatch.setattr(store,'set',lambda *args,**kw:False)
    with pytest.raises(RuntimeError,match='persisted'):
        evidence.collect_one(store,spec,acquire=lambda:(b'3',{'items':[3]}),now=20000)


def test_lock_contention_defers_source_without_dropping_next(tmp_path,monkeypatch):
    store=SnapshotStore(str(tmp_path/'snapshot.db'))
    specs=[evidence.SourceSpec(x,x,'X',json.loads) for x in ['a','b']]
    def collect(_store,spec,**kw):
        if spec.key=='a':raise TimeoutError()
        return {'error':None}
    monkeypatch.setattr(evidence,'collect_one',collect)
    assert evidence.collect_sources(store,specs)=={'a':'deferred-lock','b':'stored-or-not-due'}


def test_usdm_cumulative_not_added_and_regions_are_separate():
    row={'mapDate':'2026-11-03','areaOfInterest':'CONUS','none':30,'d0':70,'d1':40,'d2':20,'d3':8,'d4':2,'statisticFormatID':1}
    result=weather.parse_drought(json.dumps([row,{**row,'areaOfInterest':'US'}]).encode())
    assert result['weeks'][0]['shares']==[30,30,20,12,6,2]
    assert {w['region'] for w in result['weeks']}=={'US','CONUS'}
    with pytest.raises(ValueError):weather.parse_drought(json.dumps([{**row,'d2':50}]).encode())


def test_public_weather_read_does_not_fetch_or_renew(tmp_path,monkeypatch):
    store=SnapshotStore(str(tmp_path/'snapshot.db'))
    monkeypatch.setattr(weather,'fetch_bytes',lambda *args,**kw:pytest.fail('GET must not acquire'))
    store.set('snapshot:world:natural-hazards','nhc',{'fetchedAt':'2020-01-01T00:00:00Z','events':[]},100)
    value=weather.get_snapshot(store,'weather-storm-advisory')
    assert value['status']=='unavailable' and value['events']==[] and value['generatedAt'] is None


def test_custom_acquisition_obeys_raw_budget_and_rebuilds_normalization(tmp_path, monkeypatch):
    import sqlite3
    import zlib
    path=tmp_path/'archive.db'
    monkeypatch.setenv('POLYMONITOR_EXTERNAL_EVIDENCE_SQLITE_PATH',str(path))
    store=SnapshotStore(str(tmp_path/'snapshot.db'))
    spec=evidence.SourceSpec('bounded','Bounded','X',json.loads,max_bytes=4)
    state=evidence.collect_one(store,spec,acquire=lambda:(b'12345',{}),now=10000)
    assert 'lastSuccessAt' not in state and state['error']=='ValueError'
    evidence.collect_one(store,spec,acquire=lambda:(b'raw',{'corrected':False}),force=True,now=11000)
    evidence.collect_one(store,spec,acquire=lambda:(b'raw',{'corrected':True}),force=True,now=12000)
    with sqlite3.connect(path) as db:
        first,last,normalized=db.execute('SELECT first_received,last_received,normalized FROM evidence').fetchone()
    assert first==11000 and last==12000 and json.loads(zlib.decompress(normalized))=={'corrected':True}


def test_not_due_source_never_contends_for_an_acquisition_lock(tmp_path, monkeypatch):
    store=SnapshotStore(str(tmp_path/'snapshot.db'))
    spec=evidence.SourceSpec('daily','Daily','X',json.loads,cadence=86400)
    previous={'nextAttemptAt':20000,'lastSuccessAt':10000,'data':{'value':1}}
    store.set(evidence.NAMESPACE,'daily',previous,86400)
    monkeypatch.setattr(store,'fetch_lock',lambda *a,**kw:pytest.fail('A not-due source must not lock'))
    assert evidence.collect_one(store,spec,now=11000)==previous
