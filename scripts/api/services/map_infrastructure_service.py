"""Viewport-scoped OSM infrastructure, using native way geometry (ODbL)."""
from contextlib import nullcontext
from math import isfinite
from api.context import resolve_service_callable

NAMESPACE = 'snapshot:map:infrastructure'
URL = 'https://overpass-api.de/api/interpreter'


def infrastructure_snapshot(context, *, bbox):
    west, south, east, north = bbox
    if not all(isfinite(x) for x in bbox) or not (-180 <= west < east <= 180 and -85 <= south < north <= 85):
        raise ValueError('invalid-infrastructure-bbox')
    if (east-west)*(north-south) > 25:
        return {'status':'zoom-required', 'events':[], 'message':'Zoom in to inspect waterways, mapped submarine cables and pipelines (maximum query area 25 square degrees).'}
    store = context.get('SNAPSHOT_STORE'); key = ','.join(f'{x:.3f}' for x in bbox)
    cached = store.get(NAMESPACE,key) if store else None
    if cached is not None:return cached
    locker = getattr(store,'fetch_lock',None)
    with locker(NAMESPACE,key,timeout=2) if locker else nullcontext():
        cached = store.get(NAMESPACE,key) if store else None
        if cached is not None:return cached
        box = ','.join(str(v) for v in (south,west,north,east))
        query = f'[out:json][timeout:7][maxsize:134217728];(way["waterway"~"^(river|canal)$"]({box});way["man_made"="pipeline"]({box});way["man_made"="submarine_cable"]({box});way["man_made"="cable"]["location"="underwater"]({box}););out geom;'
        raw = resolve_service_callable(context,'http_json_get')(URL,params={'data':query},timeout=9,headers={'Accept':'application/json','User-Agent':'Polymonitor/1.0 (+https://polymonitor.club; research map)'})
        if not isinstance(raw,dict) or not isinstance(raw.get('elements'),list):raise ValueError('invalid-overpass-response')
        events = []; rejected = 0
        updated = (raw.get('osm3s') or {}).get('timestamp_osm_base')
        for way in raw['elements']:
            if way.get('type') != 'way':continue
            coords = [[p.get('lon'),p.get('lat')] for p in way.get('geometry',[])]
            if len(coords)<2 or not all(isinstance(x,(int,float)) and isfinite(x) for p in coords for x in p) or not all(-180<=p[0]<=180 and -90<=p[1]<=90 for p in coords):
                rejected += 1;continue
            tags = way.get('tags') or {}; kind = 'waterways' if tags.get('waterway') else 'pipelines' if tags.get('man_made')=='pipeline' else 'submarine-cables'
            events.append({'id':f'osm:way:{way["id"]}', 'category':'infrastructure', 'title':tags.get('name') or f'{kind} · OSM {way["id"]}',
                'summary':' · '.join(f'{k}: {v}' for k,v in tags.items()), 'severity':'info', 'geometry':{'type':'LineString','coordinates':coords},
                'locationPrecision':'exact', 'sources':[{'provider':'OpenStreetMap contributors','url':f'https://www.openstreetmap.org/way/{way["id"]}',
                    'nativeId':str(way['id']), 'ingestedAt':updated, 'freshness':'unknown','status':'partial'}],
                'limitations':['Mapped infrastructure reference, not operational status. OSM coverage is incomplete; the database timestamp is not an observation time.'],
                'relatedMarketIds':[], 'properties':{'mapLayer':kind,'datasetUpdatedAt':updated,'attribution':'© OpenStreetMap contributors · ODbL'}})
        failed_empty = bool(raw.get('remark')) and not events
        payload = {'status':'unavailable' if failed_empty else 'partial','events':events,'updatedAt':updated,'rejectedCount':rejected,
            'message':('OSM query failed; zoom in to reduce the area or retry later. ' + str(raw['remark'])) if failed_empty
                else raw.get('remark') or 'OSM mapped infrastructure in the current viewport; incomplete coverage, not operational status.'}
        if store:store.set(NAMESPACE,key,payload,86400 if not raw.get('remark') else 60)
        return payload


def _signal_event(identity, title, summary, source, url, updated, properties, geometry=None, country=None, severity='info'):
    return {'id': identity, 'category': 'infrastructure', 'title': title, 'summary': summary,
        'severity': severity, 'occurredAt': updated, 'updatedAt': updated, 'geometry': geometry,
        'countryCode': country, 'locationPrecision': 'region' if geometry else 'country' if country else 'unknown',
        'sources': [{'provider': source, 'url': url, 'nativeId': identity, 'observedAt': updated, 'freshness': 'unknown', 'status': 'partial'}],
        'limitations': ['Measurement coverage is incomplete. The signal does not establish its cause.'],
        'relatedMarketIds': [], 'properties': properties}


def parse_gpsjam(csv_text, date):
    """Official GPSJAM denoised percentage; retain the source denominator."""
    import csv, io, h3
    events = []; rows = 0; invalid = 0; below = 0
    reader = csv.DictReader(io.StringIO(csv_text))
    if not {'hex','count_good_aircraft','count_bad_aircraft'} <= set(reader.fieldnames or []):
        raise ValueError('invalid-gpsjam-schema')
    for row in reader:
        rows += 1
        try:
            cell = row['hex']; good = int(row['count_good_aircraft']); bad = int(row['count_bad_aircraft'])
            total = good + bad
            if min(good,bad) < 0 or total <= 0 or not h3.is_valid_cell(cell): raise ValueError('invalid-cell')
            percent = 100 * max(0, bad - 1) / total
            if percent < 2: below += 1; continue  # layer is explicitly >=2% degraded navigation, not all air traffic
            ring = [[lon,lat] for lat,lon in h3.cell_to_boundary(cell)]; ring.append(ring[0])
            event = _signal_event('gpsjam:'+date+':'+cell, 'GNSS accuracy · '+format(percent,'.1f')+'%',
                f'{bad} bad / {total} aircraft; GPSJAM denoised fraction {percent:.2f}%. Daily UTC aggregate, not real-time jamming confirmation.',
                'GPSJAM · airplanes.live / ADS-B Exchange', 'https://gpsjam.org/?date='+date, date+'T00:00:00Z',
                {'mapLayer':'gnss-interference','h3':cell,'goodAircraft':good,'badAircraft':bad,'totalAircraft':total,'percent':percent},
                {'type':'Polygon','coordinates':[ring]}, severity='warning' if percent>10 else 'watch')
            events.append(event)
        except (ValueError,TypeError): invalid += 1
    return {'status':'partial','events':events,'updatedAt':date+'T00:00:00Z', 'recordCount':rows,
        'belowThresholdCount':below,'rejectedCount':invalid,
        'message':f'GPSJAM daily UTC aggregate: {rows} cells, {below} below the 2% degraded-navigation threshold; {invalid} invalid. All source cells: https://gpsjam.org/data/{date}-h3_4.csv'}


def parse_ioda(payload):
    from datetime import datetime, timezone
    if not isinstance(payload,dict) or not isinstance(payload.get('data'),list): raise ValueError('invalid-ioda-schema')
    events = []
    for item in payload['data']:
        entity = item.get('entity') or {}; country = str(entity.get('code') or '').upper()
        if entity.get('type') != 'country' or len(country)!=2: continue
        start = datetime.fromtimestamp(float(item['from']),timezone.utc).isoformat()
        end = datetime.fromtimestamp(float(item['until']),timezone.utc).isoformat()
        datasource = str(item.get('datasource') or 'unknown')
        events.append(_signal_event(f'ioda:{country}:{datasource}:{item["from"]}', f'{entity.get("name") or country} · Internet signal',
            f'{datasource} / {item.get("method")} · score {item.get("score")} · {start} → {end}. Country-level measurement, not a confirmed nationwide outage.',
            'IODA · Georgia Tech', 'https://ioda.inetintel.cc.gatech.edu/country/'+country, start,
            {'mapLayer':'internet-outages','datasource':datasource,'score':item.get('score'),'periodEnd':end}, country=country))
    return {'status':'partial','events':events,'message':'IODA country-level signals in the past 24 hours. BGP / active-probing measurements are not confirmed nationwide outages.'}


def spatial_signal_snapshot(context, *, source):
    from datetime import datetime, timezone
    import csv, io, time
    if source not in {'gpsjam','ioda'}: raise ValueError('unsupported-spatial-source')
    store=context.get('SNAPSHOT_STORE'); key='signal:'+source
    cached=store.get(NAMESPACE,key) if store else None
    if cached is not None:return cached
    lock=getattr(store,'fetch_lock',None)
    with lock(NAMESPACE,key,timeout=2) if lock else nullcontext():
        cached=store.get(NAMESPACE,key) if store else None
        if cached is not None:return cached
        try:
            if source=='gpsjam':
                get=resolve_service_callable(context,'http_text_get')
                manifest=list(csv.DictReader(io.StringIO(get('https://gpsjam.org/data/manifest.csv',timeout=4))))
                # A suspect publication is still displayed as partial; never silently claim complete data.
                latest=manifest[-1]; date=latest.get('date') or next(iter(latest.values()))
                observed=datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=timezone.utc)
                if not 0 <= (datetime.now(timezone.utc)-observed).total_seconds() <= 3*86400:raise ValueError('gpsjam-date-outside-retention')
                result=parse_gpsjam(get(f'https://gpsjam.org/data/{date}-h3_4.csv',timeout=6),date)
                result['message'] += ' · manifest suspect: '+str(latest.get('suspect','unknown'))
                ttl=3600
            else:
                now=int(time.time())
                result=parse_ioda(resolve_service_callable(context,'http_json_get')('https://api.ioda.inetintel.cc.gatech.edu/v2/outages/events',
                    params={'entityType':'country','from':now-86400,'until':now,'limit':10000,'format':'ioda'},timeout=7))
                if len(result['events'])>=10000:result['message']+=' · API result limit reached; partial catalog.'
                ttl=300
            result['fetchedAt']=datetime.now(timezone.utc).isoformat()
            if store:store.set(NAMESPACE,key,result,ttl)
            return result
        except Exception:
            retained=store.get_stale(NAMESPACE,key) if store else None
            try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(retained['fetchedAt'])).total_seconds()
            except (TypeError,KeyError,ValueError):age=float('inf')
            if 0<=age<=(7200 if source=='gpsjam' else 900):return {**retained,'status':'degraded','message':retained['message']+' · Refresh failed; retained snapshot.'}
            raise
