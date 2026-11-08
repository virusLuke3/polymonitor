"""Weather views reuse forecast/hazard owners; only USDM adds acquisition."""
from datetime import datetime, timedelta, timezone
import json
import math
from api.services.panel_evidence_store import SourceSpec, collect_one, fetch_bytes, read_source, payload
from api.services.seed_recovery import age_seconds
from data_sources import source_value

PANEL_IDS = ('weather-precipitation', 'weather-drought', 'weather-extremes', 'weather-storm-advisory')


def parse_drought(raw):
    records = json.loads(raw)
    if not isinstance(records, list) or not records:
        raise ValueError('USDM rows missing')
    weeks = []
    for row in records[:30]:
        cumulative = [row.get(f'd{i}') for i in range(5)]
        if row.get('statisticFormatID') != 1 or not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 100 for v in cumulative):
            raise ValueError('USDM cumulative schema')
        if any(a < b for a, b in zip(cumulative, cumulative[1:])):
            raise ValueError('USDM non-monotonic cumulative area')
        none = row.get('none')
        if not isinstance(none, (int, float)) or abs(none + cumulative[0] - 100) > .03:
            raise ValueError('USDM denominator mismatch')
        shares = [none, *[round(a-b, 3) for a,b in zip(cumulative, cumulative[1:])], cumulative[-1]]
        weeks.append({'date': str(row['mapDate'])[:10], 'region': str(row['areaOfInterest']),
                      'cumulative': cumulative, 'shares': shares, 'validEnd': row.get('validEnd')})
    return {'weeks': sorted(weeks, key=lambda row: row['date'], reverse=True)}


DROUGHT = SourceSpec('weather-usdm', 'U.S. Drought Monitor', 'POLYMONITOR_DROUGHT_STATISTICS_URL', parse_drought,
                     cadence=86400, stale_after=3*86400, retain_for=14*86400, max_bytes=1024**2)


def collect(store, *, force=False):
    now = datetime.now(timezone.utc)
    def acquire():
        url = source_value(DROUGHT.url_env).format(start_date=(now-timedelta(days=60)).strftime('%m/%d/%Y'), end_date=now.strftime('%m/%d/%Y'))
        raw = fetch_bytes(url, headers={'Accept': 'application/json'}, max_bytes=DROUGHT.max_bytes)
        return raw, parse_drought(raw)
    state = collect_one(store, DROUGHT, acquire=acquire, force=force)
    return {DROUGHT.key: state.get('error') or 'stored-or-not-due'}


def read_owner(store, namespace, key, label, fresh, retain):
    data = store.get_stale(namespace, key) or {}
    timestamp = data.get('fetchedAt') or data.get('generatedAt')
    age = age_seconds(timestamp, datetime.now(timezone.utc).isoformat())
    usable = age <= retain and data.get('status') not in ('error', 'unavailable', 'warming')
    meta = {'id': namespace+':'+key, 'label': label, 'lastSuccessAt': timestamp,
            'usable': usable, 'stale': age > fresh,
            'error': 'source-expired' if not usable else 'partial-coverage' if data.get('isPartial') else None,
            'staleAfterSeconds': fresh, 'maxRetentionSeconds': retain}
    return data if usable else {}, meta


def get_snapshot(store, panel_id, *, limit=100):
    if panel_id not in PANEL_IDS:
        raise ValueError('Unknown weather panel')
    if panel_id == 'weather-drought':
        data, meta = read_source(store, DROUGHT)
        return payload(panel_id, [meta], weeks=data.get('weeks', []), coverage='USDM source region; cumulative and mutually exclusive area percentages')
    if panel_id == 'weather-precipitation':
        data, meta = read_owner(store, 'snapshot:weather:global-map', 'panel-v1', 'Existing weather forecast owner', 7200, 21600)
        now = datetime.now(timezone.utc).isoformat()
        cities = []
        for row in data.get('items', [])[:60]:
            if age_seconds(row.get('forecastFetchedAt'), now) > 21600:
                continue
            cities.append({**{k: row.get(k) for k in ('cityId','city','country','timezone','source','sourceUrl','forecastFetchedAt')},
                'hourly': [{k: h.get(k) for k in ('time','precipitation','precipitationProbability')} for h in row.get('hourly', [])[:24]],
                'daily': [{k: d.get(k) for k in ('date','precipitationSum','precipitationProbabilityMax')} for d in row.get('daily', [])[:7]]})
        return payload(panel_id, [meta], cities=cities, coverage='Model precipitation forecasts in mm; not rain-gauge observations')
    key = 'nws' if panel_id == 'weather-extremes' else 'nhc'
    data, meta = read_owner(store, 'snapshot:world:natural-hazards', key, 'NWS official alerts' if key=='nws' else 'NHC official advisories', 600 if key=='nws' else 1800, 900 if key=='nws' else 3600)
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for event in data.get('events', []):
        if key == 'nws' and (event.get('revision', {}).get('cancelled') or event.get('lifecycle') == 'ended' or event.get('expiresAt') and event['expiresAt'] < now):
            continue
        rows.append({k: event.get(k) for k in ('id','title','summary','severity','updatedAt','occurredAt','expiresAt','locationLabel','metrics','sources','revision','limitations','hazardKind')})
    return payload(panel_id, [meta], events=rows[:min(100,limit)], total=len(rows), coverage='NWS responsibility areas' if key=='nws' else 'NHC Atlantic, eastern and central Pacific; current advisory facts')
