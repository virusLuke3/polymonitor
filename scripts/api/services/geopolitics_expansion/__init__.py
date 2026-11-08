"""Official claims and depositary records; no inferred territorial or legal verdicts."""
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from api.services.panel_evidence_store import SourceSpec, collect_sources, read_source, payload, public_url
from api.services.weather_expansion import read_owner
from data_sources import source_value

PANEL_IDS = ('geo-conflict-watch','geo-ceasefire-watch','geo-territory-control','geo-diplomacy-calendar','geo-treaty-tracker')
PATTERNS = {
 'geo-conflict-watch': r'\b(war|attack|conflict|strike|military|violence|missile|killed)\b',
 'geo-ceasefire-watch': r'\b(ceasefire|cease-fire|truce|peace agreement|peace plan|peace process|hostage|negotiation)\b',
 'geo-territory-control': r'\b(occupation|occupied|territory|territories|territorial|annexation|sovereignty|settlements)\b',
 'geo-diplomacy-calendar': r'\b(meet|meeting|talks|summit|visit|dialogue|bilateral|delegation)\b',
}


def clean(value):
    return re.sub(r'\s+', ' ', BeautifulSoup(str(value or ''), 'html.parser').get_text(' ', strip=True)).strip()


def claim(title, summary, url, timestamp, source):
    return {'id': hashlib.sha256((url+title).encode()).hexdigest()[:24],
            'title': title[:500], 'summary': summary[:1400], 'url': public_url(url),
            'claim_source': source, 'independent_confirmation_count': None,
            'event_time': None, 'reported_time': timestamp,
            'geographic_scope': None, 'verification_status': 'official-publication',
            'legalStage': None, 'controlVerdict': None}


def parse_govuk(raw):
    body = json.loads(raw)
    if not isinstance(body.get('results'), list):
        raise ValueError('GOV.UK response schema')
    rows = []
    for row in body['results'][:200]:
        title, url = clean(row.get('title')), urljoin(source_value('POLYMONITOR_GEO_GOVUK_SEARCH_URL'), str(row.get('link') or ''))
        if title and row.get('link'):
            rows.append(claim(title, clean(row.get('description')), url, row.get('public_timestamp'), 'UK Foreign, Commonwealth & Development Office'))
    return {'items': rows}


def parse_treaty(raw):
    soup = BeautifulSoup(raw, 'html.parser')
    table = soup.select_one('[id$=tblgrid]')
    if table is None:
        raise ValueError('UN depositary participant table unavailable')
    rows = []
    for tr in table.select('tr'):
        cells = [clean(td.get_text(' ', strip=True)) for td in tr.find_all('td', recursive=False)]
        if len(cells) == 3 and cells[0] and 'Participant' not in cells[0]:
            rows.append({'country': cells[0], 'signature': cells[1] or None, 'deposit': cells[2] or None})
    text = clean(soup.get_text(' ', strip=True))
    counts = re.search(r'Signatories\s*:\s*(\d+)\s*\.\s*Parties\s*:\s*(\d+)', text, re.I)
    status = re.search(r'STATUS AS AT\s*:\s*(.{0,45}?)(?:CHAPTER|$)', text)
    if len(rows) < 10 or not counts:
        raise ValueError('UN depositary summary missing')
    return {'title': 'Paris Agreement', 'signatories': int(counts[1]), 'parties': int(counts[2]),
            'statusAt': status[1].strip() if status else None, 'participants': rows,
            'url': public_url(source_value('POLYMONITOR_GEO_TREATY_STATUS_URL')),
            'scope': 'Depositary signature and deposit entries, including footnotes. Historical deposit does not alone prove current party status; withdrawals and territorial declarations must be read in the source.'}


SPECS = (
 SourceSpec('geo:govuk', 'FCDO official publications', 'POLYMONITOR_GEO_GOVUK_SEARCH_URL', parse_govuk, cadence=3600, stale_after=10800),
 SourceSpec('geo:un-treaty', 'UN Treaty Collection depositary', 'POLYMONITOR_GEO_TREATY_STATUS_URL', parse_treaty, cadence=86400, stale_after=3*86400, retain_for=14*86400),
)


def collect(store, *, force=False):
    return collect_sources(store, SPECS, force=force, budget=300)


def get_snapshot(store, panel_id, *, limit=100):
    if panel_id not in PANEL_IDS:
        raise KeyError(panel_id)
    if panel_id == 'geo-treaty-tracker':
        data, source = read_source(store, SPECS[1])
        return payload(panel_id, [source], treaty=data or None, coverage='Paris Agreement official depositary status')
    reads = [read_source(store, spec) for spec in SPECS[:1]]
    pattern = re.compile(PATTERNS[panel_id], re.I)
    rows = {row['id']: row for data, _ in reads for row in data.get('items', []) if pattern.search(row['title']+' '+row['summary'])}
    rows = sorted(rows.values(), key=lambda r: r.get('reported_time') or '', reverse=True)[:min(100,limit)]
    sources = [source for _, source in reads]
    historical = []
    if panel_id == 'geo-conflict-watch':
        data, source = read_owner(store, 'snapshot:world:geo-sanctions-shock', 'panel-v1', 'Existing conflict owner · historical UCDP / configured ACLED', 3600, 86400)
        sources.append(source)
        for row in data.get('items', []):
            if row.get('kind') == 'conflict':
                record = {k: row.get(k) for k in ('id','headline','country','locationLabel','occurredAt','source','sideA','sideB','deathsBest','deathsLow','deathsHigh')}
                low, best, high = (record[k] for k in ('deathsLow', 'deathsBest', 'deathsHigh'))
                if not all(isinstance(v, (int, float)) for v in (low, best, high)) or not 0 <= low <= best <= high:
                    record.update(deathsLow=None, deathsHigh=None, casualtyRangeIssue='inconsistent-or-missing-upstream-bounds')
                historical.append(record)
            if len(historical) >= 60:
                break
    return payload(panel_id, sources, items=rows, historical=historical,
        coverage='FCDO official statements; topic selection is not event confirmation. No automatic legal-stage, territorial-control or market-settlement determination.')
