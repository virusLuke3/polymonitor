from datetime import datetime, timezone
from types import SimpleNamespace
from flask import Flask
import pytest
from api.context import RuntimeResources
from api.routes.system import create_system_blueprint, SystemRouteDependencies
from api.services.global_weather_map_service import query_map_weather
from api.services.global_transport_shipping_service import parse_faa_status
from api.services.natural_hazards.providers import eccc
from api.services.natural_hazards.service import _fetch_provider_results, NaturalHazardDependencies
from api.services.natural_hazards.snapshots import SNAPSHOT_NAMESPACE

class Store:
    def __init__(self): self.values = {}
    def get(self, ns, key): return self.values.get((ns, key))
    def get_stale(self, ns, key): return self.get(ns, key)
    def set(self, ns, key, value, ttl): self.values[ns,key] = value


@pytest.mark.parametrize('source', ['faa', 'ioda', 'gpsjam'])
@pytest.mark.parametrize('state', ['retained', 'published', 'expired', 'missing'])
def test_map_source_lock_contention_uses_bounded_snapshots(monkeypatch, source, state):
    from contextlib import contextmanager
    from datetime import timedelta
    from api.services import global_transport_shipping_service as transport, map_infrastructure_service as signals

    now = datetime.now(timezone.utc)
    retained = {'status': 'partial', 'events': [{'id': 'native-record'}], 'message': 'Limited coverage',
                'fetchedAt': (now - timedelta(seconds=10000 if state == 'expired' else 400)).isoformat()}
    fresh = {**retained, 'fetchedAt': now.isoformat()}

    class ContendedStore:
        fresh = None
        def get(self, *args): return self.fresh
        def get_stale(self, *args): return None if state == 'missing' else retained
        @contextmanager
        def fetch_lock(self, *args, **kwargs):
            if state == 'published': self.fresh = fresh
            # Raised by __enter__, before the old inner provider try/except.
            raise TimeoutError('shared-source-acquisition-deadline')
            yield  # pragma: no cover
        def set(self, *args): raise AssertionError('A waiting reader must not rewrite snapshot freshness')

    store = ContendedStore()
    def unexpected(*args, **kwargs): raise AssertionError('A waiting reader must not duplicate acquisition')
    monkeypatch.setattr(transport, '_dependencies', lambda context: SimpleNamespace(snapshot_store=store))
    monkeypatch.setattr(transport, '_http_text', unexpected)
    context = {'SNAPSHOT_STORE': store, 'http_json_get': unexpected, 'http_text_get': unexpected}
    fetch = lambda: transport.get_transport_map_source(context, source=source) if source == 'faa' else signals.spatial_signal_snapshot(context, source=source)
    if state in {'expired', 'missing'} and source != 'faa':
        with pytest.raises(TimeoutError): fetch()
        return
    result = fetch()
    if state in {'expired', 'missing'}:
        assert result['status'] == 'unavailable' and result['events'] == []
    elif state == 'published':
        assert result == fresh
    else:
        assert result['status'] == 'degraded'
        assert result['events'] == retained['events']
        assert result['fetchedAt'] == retained['fetchedAt']


def test_liveness_does_not_touch_unavailable_dependencies():
    def fail(*a, **k): raise AssertionError('must not query dependencies')
    app = Flask(__name__)
    app.register_blueprint(create_system_blueprint(SystemRouteDependencies(fail, fail, fail, fail, fail)))
    assert app.test_client().get('/health/live').json == {'status': 'ok'}


def test_weather_lookup_caches_and_uses_real_selected_coordinates():
    calls = []; resources = RuntimeResources()
    def get(url, **kwargs):
        calls.append((url, kwargs))
        if 'geocoding' in url:
            return {'results': [{'id': 1, 'name': 'London', 'latitude': 51.5, 'longitude': -.12, 'country': 'UK'}]}
        return {'current': {'temperature_2m': 12.5, 'time': '2026-10-02T08:00'}, 'daily': {}, 'hourly': {}}
    ctx = {'_resources': resources, 'SETTINGS': SimpleNamespace(open_meteo_api_url='https://api.open-meteo.com/v1/forecast'),
        'SNAPSHOT_STORE': Store(), 'http_json_get': get}
    try:
        assert query_map_weather(ctx, query='London')['places'][0]['lat'] == 51.5
        assert query_map_weather(ctx, query='London')['status'] == 'ok'
        result = query_map_weather(ctx, latitude=51.5, longitude=-.12)
        assert result['current']['temperature_2m'] == 12.5
        assert calls[-1][1]['params']['latitude'] == 51.5
        assert len(calls) == 2
        with pytest.raises(ValueError): query_map_weather(ctx, latitude=float('nan'), longitude=0)
    finally: resources.close()


def test_faa_preserves_restriction_conditions_and_missing_coordinates():
    xml = '<AIRPORT_STATUS_INFORMATION><Update_Time>Fri Oct 2 08:00:00 2026 GMT</Update_Time><Delay_type><Name>Airport Closures</Name><Airport_Closure_List><Airport><ARPT>LAX</ARPT><Reason>Closed to non scheduled GA except prior permission</Reason></Airport><Airport><ARPT>XYZ</ARPT><Reason>Partial runway restriction</Reason></Airport></Airport_Closure_List></Delay_type></AIRPORT_STATUS_INFORMATION>'
    result = parse_faa_status(xml, {'LAX': {'name':'Los Angeles', 'lat':33.94, 'lon':-118.4}})
    first, second = result['events']
    assert first['geometry']['coordinates'] == [-118.4,33.94]
    assert 'except prior permission' in first['summary']
    assert second['geometry'] is None and second['locationPrecision'] == 'unknown'
    assert result['status'] == 'partial'


def test_eccc_cancellation_expiry_and_native_geometry():
    shape = {'type':'Polygon','coordinates':[[[-100,40],[-99,40],[-99,41],[-100,40]]]}
    props = {'publication_datetime':'2026-10-02T06:00:00Z','expiration_datetime':'2026-10-02T10:00:00Z',
        'alert_name_en':'storm surge warning','alert_type':'warning','status_en':'continued','feature_name_en':'Coast'}
    payload = {'features': [
        {'id':'active','geometry':shape,'properties':props},
        {'id':'cancelled','geometry':shape,'properties':{**props,'status_en':'ended'}},
        {'id':'expired','geometry':shape,'properties':{**props,'expiration_datetime':'2026-10-02T07:00:00Z'}}]}
    result = eccc.fetch(lambda *a, **k: payload, now=datetime(2026,10,2,8,tzinfo=timezone.utc))
    assert len(result['events']) == 1
    assert result['events'][0]['geometry'] is shape
    assert result['events'][0]['countryCode'] == 'CA'


def test_fresh_source_cache_does_not_schedule_provider():
    resources = RuntimeResources(); store = Store()
    store.set(SNAPSHOT_NAMESPACE, 'usgs', {'events':[], 'fetchedAt':'2026-10-02T00:00:00Z'},60)
    deps = NaturalHazardDependencies.from_context({'_resources':resources,'SNAPSHOT_STORE':store,'http_json_get':lambda *a, **k: None})
    try:
        result = _fetch_provider_results(dependencies=deps, source_specs={'usgs':(60, lambda: (_ for _ in ()).throw(AssertionError('cached')))})
        assert result['usgs']['status'] == 'ok'
        assert resources.hazard_pending == {}
    finally: resources.close()


def test_swr_preserves_throttle_and_original_success_time():
    from api.services.natural_hazards.snapshots import cached_source_result, CONDITION_NAMESPACE, utc_now
    class StaleStore(Store):
        def get(self, ns, key): return None
        def get_stale(self, ns, key): return self.values.get((ns,key))
    store=StaleStore(); now=utc_now()
    store.set(SNAPSHOT_NAMESPACE,'usgs',{'events':[], 'fetchedAt':now.isoformat()},60)
    store.set(CONDITION_NAMESPACE,'usgs',{'retryAt':now.timestamp()+100,'condition':'throttled','errorCode':'usgs-http-429'},100)
    result=cached_source_result(store,'usgs')
    assert result['condition']=='throttled' and result['retryAfterSeconds']>99
    assert result['fetchedAt']==now.isoformat() and result['status']=='degraded'


def test_infrastructure_uses_native_way_geometry_and_rejects_invalid_coordinates():
    from api.services.map_infrastructure_service import infrastructure_snapshot
    store=Store();calls=[]
    def get(*args,**kwargs):
        calls.append(kwargs)
        return {'elements':[
            {'type':'way','id':1,'tags':{'waterway':'river'},'geometry':[{'lat':1,'lon':2},{'lat':2,'lon':3}]},
            {'type':'way','id':2,'tags':{'waterway':'river'},'geometry':[{'lat':91,'lon':2},{'lat':2,'lon':3}]}]}
    context={'SNAPSHOT_STORE':store,'http_json_get':get}
    result=infrastructure_snapshot(context,bbox=[0,0,4,4])
    assert result['events'][0]['geometry']['coordinates']==[[2,1],[3,2]]
    assert result['rejectedCount']==1 and result['status']=='partial'
    assert infrastructure_snapshot(context,bbox=[0,0,4,4])==result and len(calls)==1
    assert infrastructure_snapshot(context,bbox=[-180,-80,180,80])['status']=='zoom-required'


def test_gpsjam_uses_official_denoising_and_real_h3_boundary():
    import h3
    from api.services.map_infrastructure_service import parse_gpsjam
    cell=h3.latlng_to_cell(50,30,4)
    result=parse_gpsjam(f'hex,count_good_aircraft,count_bad_aircraft\n{cell},90,10\n84005e1ffffffff,0,1\n','2026-10-01')
    event=result['events'][0]
    assert event['properties']['percent']==9
    assert event['properties']['totalAircraft']==100
    assert event['geometry']['coordinates'][0][0]==list(reversed(h3.cell_to_boundary(cell)[0]))
    assert result['belowThresholdCount']==1 and result['recordCount']==2
    assert 'not real-time jamming' in event['summary']


def test_infrastructure_timeout_is_not_a_successful_empty_catalog():
    from api.services.map_infrastructure_service import infrastructure_snapshot
    failed = infrastructure_snapshot({'http_json_get': lambda *a, **kw: {
        'elements': [], 'remark': 'runtime error: Query timed out after 8 seconds.'}}, bbox=[0,0,1,1])
    assert failed['status'] == 'unavailable' and not failed['events']
    assert 'zoom in' in failed['message']
    empty = infrastructure_snapshot({'http_json_get': lambda *a, **kw: {'elements': []}}, bbox=[0,0,1,1])
    assert empty['status'] == 'partial' and not empty['events']


def test_ioda_retains_country_measurement_without_fabricated_point():
    from api.services.map_infrastructure_service import parse_ioda
    result=parse_ioda({'data':[{'entity':{'type':'country','code':'US','name':'United States'},'from':1000000000,'until':1000000100,'score':123,'datasource':'bgp','method':'median'}]})
    event=result['events'][0]
    assert event['geometry'] is None and event['countryCode']=='US'
    assert event['properties']['score']==123 and event['severity']=='info'
    assert 'not a confirmed nationwide outage' in event['summary']


def test_healthcheck_readiness_failure_does_not_restart_live_api(monkeypatch):
    from ops import gcp_serving_healthcheck as hc
    monkeypatch.setattr(hc,'_unit_active',lambda _:True)
    def probe(path,**kwargs):
        if path=='/content/latest':raise TimeoutError('dependency busy')
        return {'status':'ok'}
    monkeypatch.setattr(hc,'_probe_json',probe)
    assert hc._api_healthy()[:2]==(True,False)


def test_healthcheck_restart_budget_written_before_systemctl(tmp_path,monkeypatch):
    import json
    from ops import gcp_serving_healthcheck as hc
    monkeypatch.setattr(hc,'STATE_DIR',tmp_path);monkeypatch.setattr(hc,'STATE_PATH',tmp_path/'state.json')
    monkeypatch.setattr(hc,'FAILURE_THRESHOLD',1)
    def restart(*args):
        assert json.loads(hc.STATE_PATH.read_text())['units']['api']['restart_attempts']==[1000]
        raise TimeoutError('process terminated')
    monkeypatch.setattr(hc,'_systemctl',restart)
    with pytest.raises(TimeoutError):hc._recover(key='api',unit='polydata-api.service',reason='dead',now=1000,state={'units':{}},warmup_seconds=1)


def test_ais_sampler_retains_observed_positions_without_expanding_sampling(monkeypatch):
    import asyncio, json, websockets
    from api.services.global_transport_shipping_service import _sample_aisstream
    sent=[]
    class Socket:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def send(self,text):sent.append(json.loads(text))
        async def recv(self):return json.dumps({'MetaData':{'ShipName':'Test vessel','time_utc':'2026-10-02 06:00:00.123 +0000 UTC'},'Message':{'PositionReport':{'UserID':123456789,'Latitude':22.5,'Longitude':114.1,'Sog':10,'Cog':30}}})
    monkeypatch.setattr(websockets,'connect',lambda *a,**k:Socket())
    monkeypatch.delenv('POLYDATA_AISSTREAM_BBOX_JSON',raising=False)
    monkeypatch.setenv('POLYDATA_AISSTREAM_SAMPLE_LIMIT','1')
    result=asyncio.run(_sample_aisstream('fixture-key',timeout_seconds=1))
    assert sent[0]['BoundingBoxes']==[[[-90,-180],[90,180]]]
    assert result['messageCount']==1 and len(result['vessels'])==1
    assert result['vessels'][0]['lat']==22.5 and result['vessels'][0]['lon']==114.1
    assert result['vessels'][0]['observedAt']=='2026-10-02T06:00:00.123000+00:00'


def test_swic_retains_country_only_warnings_without_geocoding_and_drops_expired():
    from api.services.natural_hazards.providers import swic
    item={'id':'native-1','event':'Fog','headline':'Dense fog warning','sent':'2026-10-02 06:00:00',
        'expires':'2026-10-02 09:00:00','s':3,'u':4,'c':3,'capURL':'th-tmd-en/alert.xml','areaDesc':'Coast'}
    payload={'items':[item,{**item,'id':'us','capURL':'us-noaa-nws/alert.xml'},
        {**item,'id':'old','expires':'2026-10-02 07:00:00'}, {**item,'id':'cancel','msgType':'Cancel'}],
        'lastUpdated':'2026-10-02 08:00:00'}
    result=swic.fetch(lambda *a,**k:payload,now=datetime(2026,10,2,8,tzinfo=timezone.utc))
    assert len(result['events'])==1
    event=result['events'][0]
    assert event['countryCode']=='TH' and event['geometry'] is None
    assert event['hazardKind']=='weather-alert' and event['severity']=='warning'
    assert result['is_partial'] is True


def test_faa_retains_nested_delay_measurements():
    xml='<AIRPORT_STATUS_INFORMATION><Update_Time>Fri Oct 2 08:00:00 2026 GMT</Update_Time><Delay_type><Name>Arrival/Departure Delay</Name><Arrival_Departure_Delay_List><Delay><ARPT>LAX</ARPT><Reason>Weather</Reason><Arrival_Delay><Min>15 minutes</Min><Max>45 minutes</Max><Trend>Increasing</Trend></Arrival_Delay></Delay></Arrival_Departure_Delay_List></Delay_type></AIRPORT_STATUS_INFORMATION>'
    event=parse_faa_status(xml, {})['events'][0]
    assert event['properties']['conditions']['Arrival_Delay/Max']=='45 minutes'
    assert 'Increasing' in event['summary']


def test_worker_startup_keeps_public_api_alive_during_auth_db_timeout(monkeypatch,caplog):
    from api.services import auth_service as auth
    from db.db import psycopg
    monkeypatch.setenv('POLYDATA_AUTH_ENABLED','1');monkeypatch.setenv('POLYDATA_AUTH_AUDIT_PEPPER','x'*32)
    monkeypatch.setattr(auth,'get_backend',lambda:'postgres')
    monkeypatch.setattr(auth,'get_connection',lambda: (_ for _ in ()).throw(psycopg.OperationalError('connection timeout')))
    auth.validate_runtime_config()
    assert 'protected operations remain fail-closed' in caplog.text
    # Validation does not turn authentication off or grant a principal.
    assert auth.auth_enabled() is True
    with pytest.raises(psycopg.OperationalError):
        auth.login('researcher', 'unused-test-password', {})
    monkeypatch.setenv('POLYDATA_AUTH_AUDIT_PEPPER','short')
    with pytest.raises(RuntimeError,match='32 characters'):auth.validate_runtime_config()


def test_worker_startup_still_rejects_missing_auth_schema(monkeypatch):
    from api.services import auth_service as auth
    monkeypatch.setenv('POLYDATA_AUTH_ENABLED','1');monkeypatch.setenv('POLYDATA_AUTH_AUDIT_PEPPER','x'*32)
    monkeypatch.setattr(auth,'get_backend',lambda:'postgres')
    closed=[]
    monkeypatch.setattr(auth,'get_connection',lambda:SimpleNamespace(close=lambda:closed.append(True)))
    monkeypatch.setattr(auth,'schema_is_ready',lambda conn:False)
    with pytest.raises(RuntimeError,match='schema is missing'):auth.validate_runtime_config()
    assert closed==[True]

def test_weather_provider_throttle_uses_independent_forecast_and_shared_cooldown():
    import requests
    calls = []
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    def get(url, **kwargs):
        calls.append((url, kwargs))
        if 'open-meteo' in url:
            response = requests.Response(); response.status_code = 429; response.headers['Retry-After'] = '3600'
            raise requests.HTTPError(response=response)
        return {'properties': {'timeseries': [{'time': now.isoformat(), 'data': {'instant': {'details': {
            'air_temperature': 12.4, 'wind_speed': 2, 'relative_humidity': 61}}}}]}}
    resources = RuntimeResources(); store = Store()
    ctx = {'_resources': resources, 'SETTINGS': SimpleNamespace(), 'SNAPSHOT_STORE': store, 'http_json_get': get}
    try:
        result = query_map_weather(ctx, latitude=51.50853, longitude=-.12574)
        assert result['source'] == 'MET Norway' and result['status'] == 'partial'
        assert result['current']['wind_speed_10m'] == 7.2
        assert result['dailySampled'] and result['daily']['temperature_2m_min'] == [12.4]
        assert calls[-1][1]['params'] == {'lat': '51.5085', 'lon': '-0.1257'}
        assert 'polymonitor.club' in calls[-1][1]['headers']['User-Agent']
        query_map_weather(ctx, latitude=48.8566, longitude=2.3522)
        assert len([u for u,_ in calls if 'open-meteo' in u]) == 1
        count = len(calls)
        query_map_weather(ctx, latitude=51.50853, longitude=-.12574)
        assert len(calls) == count
    finally: resources.close()
