"""WMO member CAP catalog, retaining country-only records without fake points."""
import re
from datetime import datetime, timezone
from ..contracts import SEVERITY_MAPPING_VERSION
from ..normalize import iso_timestamp
from ..source_health import SOURCE_COVERAGE

URL = 'https://severeweather.wmo.int/json/wmo_all.json'


def fetch(http_json_get, *, now=None):
    now = now or datetime.now(timezone.utc)
    payload = http_json_get(URL, timeout=6)
    if not isinstance(payload, dict) or not isinstance(payload.get('items'), list):
        raise ValueError('swic-schema-items')
    events = {}
    for item in payload['items']:
        if not isinstance(item, dict): continue
        native = str(item.get('id') or '')
        sent = iso_timestamp(item.get('sent')); expires = iso_timestamp(item.get('expires'))
        if not native or not sent or not expires or datetime.fromisoformat(expires.replace('Z','+00:00')) <= now: continue
        # Current SWIC uses capURL, older rows use url. Do not infer a location
        # from a member's office/capital: the catalog has no hazard geometry.
        match = re.match(r'^([a-z]{2})-', str(item.get('capURL') or item.get('url') or ''), re.I)
        country = match.group(1).upper() if match else None
        if country in {'US','CA'}: continue  # native NWS / ECCC own these alerts
        if str(item.get('msgType') or '').lower() == 'cancel': continue
        event = str(item.get('event') or 'Weather warning'); lowered = event.lower()
        kind = 'extreme-heat' if 'heat' in lowered else 'extreme-cold' if any(s in lowered for s in ('cold','frost','freeze')) else 'flood' if 'flood' in lowered else 'tornado' if 'tornado' in lowered else 'severe-storm' if any(w in lowered for w in ('storm','wind','snow','blizzard')) else 'weather-alert'
        severity = {4:'critical',3:'warning',2:'watch',1:'info',0:'info'}.get(item.get('s'),'info')
        occurred = iso_timestamp(item.get('effective')) or sent
        row = {'id':'weather-alert:swic:'+native,'category':'weather','hazardKind':kind,
            'title':str(item.get('headline') or event), 'summary':str(item.get('areaDesc') or event),
            'severity':severity,'occurredAt':occurred,'updatedAt':sent,'expiresAt':expires,
            'geometry':None,'countryCode':country,'locationPrecision':'country' if country else 'unknown',
            'locationLabel':item.get('areaDesc'),'relatedMarketIds':[],
            'sources':[{'provider':'WMO SWIC','url':URL,'nativeId':native,'observedAt':sent,'freshness':'fresh','status':'partial'}],
            'coverage':SOURCE_COVERAGE['swic'],
            'lifecycle':'forecast' if datetime.fromisoformat(occurred.replace('Z','+00:00')) > now else 'active',
            'metrics':{'kind':'weather-alert','providerSeverity':str(item.get('s')),'urgency':str(item.get('u')),'certainty':str(item.get('c'))},
            'revision':{'provider':'WMO SWIC','nativeEventId':native,'revisionAt':sent,'replaces':[],'cancelled':False},
            'severityEvidence':{'provider':'WMO SWIC','rawLevel':str(item.get('s')),'mappingVersion':SEVERITY_MAPPING_VERSION,
                'reason':'WMO CAP catalog severity: 0 unknown, 1 minor, 2 moderate, 3 severe, 4 extreme.'},
            'limitations':['WMO member catalog coverage is partial. This record has no native hazard geometry; available in the event list and country brief, not drawn at an invented point.'],
            'properties':{'mapEntity':'hazard-event','memberId':item.get('mid'),'capReference':item.get('capURL') or item.get('url')}}
        if native not in events or sent >= events[native]['updatedAt']: events[native] = row
    return {'events':list(events.values()), 'data_updated_at':iso_timestamp(payload.get('lastUpdated')), 'is_partial':True}
