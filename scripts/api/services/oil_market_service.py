"""Oil observations and Polymarket settlement rules for the commodity watcher."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from html import unescape
import json
from math import isfinite
import re
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import requests

from api.clients.source_transport import read_response_bytes, source_session
from data_sources import source_value

NAMESPACE = 'snapshot:markets:oil-context'
HORMUZ_PORT = 'chokepoint6'
HORMUZ_PAGE = 'cb5856222a5b4105adc6ee7e880a1730'
EIA_SERIES = {
    'brentSpot': ('RBRTE', 'D', 'Europe Brent Spot Price', 'USD/bbl'),
    'wtiSpot': ('RWTC', 'D', 'Cushing, OK WTI Spot Price', 'USD/bbl'),
    'inventory': ('WCESTUS1', 'W', 'Ending Stocks excluding SPR', 'million bbl'),
    'spr': ('WCSSTUS1', 'W', 'Ending Stocks of Crude Oil in SPR', 'million bbl'),
    'production': ('WCRFPUS2', 'W', 'Field Production of Crude Oil', 'million bbl/day'),
}
SOURCES = (*EIA_SERIES, 'hormuz', 'markets')
RETENTION = 21 * 86400
_ROWS = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.I | re.S)
_CELLS = re.compile(r"<td\s+class=['\"](B[356])['\"][^>]*>(.*?)</td>", re.I | re.S)


def _number(value):
    try:
        number = float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _stamp(text):
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()
    except (AttributeError, TypeError, ValueError):
        return 0


def _fetch(url, *, params, body_limit, proxy=''):
    if not url:
        raise ValueError('source endpoint missing')
    with source_session() as session:
        session.trust_env = False
        with session.get(url, params=params, timeout=(5, 12), stream=True,
                         proxies={'http': proxy, 'https': proxy} if proxy else None) as response:
            return read_response_bytes(response, body_limit).decode('utf-8', errors='replace')


def _eia(key, now):
    series, frequency, title, unit = EIA_SERIES[key]
    raw = _fetch(source_value('POLYDATA_OIL_EIA_HISTORY_URL'), params={'n': 'PET', 's': series, 'f': frequency}, body_limit=750_000)
    release = re.search(r'>Release Date:\s*(\d{1,2}/\d{1,2}/\d{4})<', raw)
    next_release = re.search(r'>Next Release Date:\s*(\d{1,2}/\d{1,2}/\d{4})<', raw)
    if title not in unescape(raw) or not release:
        raise ValueError('EIA series or release date not found')
    def release_date(match):
        return datetime.strptime(match[1], '%m/%d/%Y').date().isoformat() if match else None

    values = {}
    for row in _ROWS.findall(raw):
        cells = [(kind, unescape(value).strip()) for kind, value in _CELLS.findall(row)]
        if not cells or cells[0][0] != 'B6' or not cells[0][1][:4].isdigit():
            continue
        label = cells[0][1]
        if frequency == 'D':
            start = datetime.strptime(label.split(' to ')[0].replace('- ', '-'), '%Y %b-%d').date()
            for offset, (_, value) in enumerate(cells[1:]):
                point = _number(value)
                if point is not None:
                    values[start + timedelta(days=offset)] = point
        else:
            for (_, day), (_, value) in zip(cells[1::2], cells[2::2]):
                point = _number(value)
                if day and point is not None:
                    period = datetime.strptime(f'{label[:4]}/{day}', '%Y/%m/%d').date()
                    values[period] = point / 1000
    points = [{'period': day.isoformat(), 'value': value} for day, value in sorted(values.items())[-35:]]
    if len(points) < 2 or points[-1]['period'] > now.date().isoformat():
        raise ValueError('EIA observations missing or future dated')
    return {'series': series, 'source': 'EIA', 'unit': unit, 'releaseOn': release_date(release),
            'nextReleaseOn': release_date(next_release), 'points': points}


def _hormuz(now):
    fields = 'portid,date,n_total,n_tanker,n_container,n_dry_bulk,n_general_cargo,n_roro'
    raw = _fetch(source_value('POLYDATA_OIL_PORTWATCH_QUERY_URL'), params={
        'where': f"portid = '{HORMUZ_PORT}'", 'f': 'json', 'outFields': fields, 'returnGeometry': 'false',
        'orderByFields': 'date DESC', 'resultRecordCount': 35,
    }, body_limit=100_000)
    response = json.loads(raw)
    counts = {'n_total': 'value', 'n_tanker': 'tankers', 'n_container': 'container', 'n_dry_bulk': 'dryBulk',
              'n_general_cargo': 'generalCargo', 'n_roro': 'roRo'}
    points = {}
    for field in response.get('features') or ():
        row = field['attributes']
        period = date.fromisoformat(row['date'])
        if row.get('portid') != HORMUZ_PORT or period > now.date() or type(row.get('n_total')) is not int or row['n_total'] < 0:
            raise ValueError('Invalid PortWatch Hormuz observation')
        if period in points:
            raise ValueError('Duplicate PortWatch calendar period')
        points[period] = {'period': period.isoformat(), **{to: row.get(key) for key, to in counts.items()}}
    if not points:
        raise ValueError('PortWatch Hormuz observations missing')
    return {'series': HORMUZ_PORT, 'source': 'IMF PortWatch', 'unit': 'transits',
            'points': [row for _, row in sorted(points.items())]}


def settlement_rule(market):
    """Require rule text and source identity. A title containing 'oil' is insufficient."""
    rule = (market.get('description') or '').lower()
    raw = market.get('resolutionSource') or ''
    host = urlsplit(raw).hostname
    if host == 'data.chain.link' and all(s in rule for s in ('ny-ukoil/usd', 'midprice', 'active futures', 'contract rollover')):
        return 'brent', 'Chainlink NY-UKOIL/USD', raw, 'Active futures midPrice · window start vs end'
    if all(s in rule for s in ('app.pyth.com', 'cll', 'ice futures europe wti crude futures', '1-minute')):
        if not raw or host == 'app.pyth.com':
            return 'wti', 'Pyth CLL · ICE WTI', raw or 'https://app.pyth.com/explore?search=CLL', 'Active month · 1-minute candle high/low'
    if all(s in rule for s in ('cme crude oil (cl)', 'official daily high', '147.27', 'cmegroup.com')):
        if not raw or host in ('cmegroup.com', 'www.cmegroup.com'):
            return 'wti', 'CME CL', raw or 'https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.quotes.html', 'Active month · official daily high'
    if 'strait of hormuz' in rule and 'imf portwatch' in rule and ('transit' in rule or 'traffic' in rule):
        if host == 'portwatch.imf.org' and HORMUZ_PAGE in urlsplit(raw).path:
            return 'hormuz', 'IMF PortWatch', raw, 'Strait of Hormuz · official daily transit calls'
    if host in ('www.eia.gov', 'eia.gov') and 'energy information administration' in rule:
        params = parse_qs(urlsplit(raw).query.lower())
        for key, (series, frequency, _, _) in EIA_SERIES.items():
            if params.get('s') == [series.lower()] and params.get('f') == [frequency.lower()] and series.lower() in rule:
                return 'eia', f'EIA {series}', raw, 'U.S. Strategic Petroleum Reserve · weekly stocks' if key == 'spr' else f'EIA series · {series}'
    return None


def _markets(gamma, now):
    if not gamma:
        raise ValueError('Gamma API missing')
    output = {}
    # A capped active catalog scan, with no per-market upstream requests.
    for tag in ('oil', 'brent', 'spr'):
        raw = _fetch(gamma.rstrip('/') + '/events', params={'tag_slug': tag, 'active': 'true', 'closed': 'false', 'limit': 64},
                     body_limit=8_000_000, proxy=source_value('POLYDATA_OIL_GAMMA_PROXY_URL'))
        events = json.loads(raw)
        if not isinstance(events, list):
            raise ValueError('Invalid Gamma events response')
        for event in events:
            event_slug = event.get('slug', '')
            if not re.fullmatch(r'[a-zA-Z0-9-]+', event_slug):
                continue
            for market in event.get('markets') or ():
                slug = market.get('slug', '')
                if not re.fullmatch(r'[a-zA-Z0-9-]+', slug) or market.get('closed') or market.get('acceptingOrders') is not True:
                    continue
                end = market.get('endDate') or event.get('endDate')
                if _stamp(end) <= now.timestamp() or not (match := settlement_rule(market)):
                    continue
                group, source, source_url, basis = match
                market_id = str(market['id'])
                start = market.get('eventStartTime') or event.get('startTime')
                outcome = 'up' if group == 'brent' else 'yes'
                names = market.get('outcomes') or '[]'
                names = json.loads(names) if isinstance(names, str) else names
                primary = bool(names and names[0].lower() == outcome)
                output[market_id] = {
                    'id': market_id, 'benchmark': group, 'source': source, 'sourceUrl': source_url, 'basis': basis,
                    'eventTitle': event.get('title') or event_slug, 'title': market.get('question') or slug,
                    'label': market.get('groupItemTitle') or market.get('question') or slug, 'outcome': outcome,
                    'url': f'https://polymarket.com/event/{event_slug}/{slug}',
                    'bestBid': _number(market.get('bestBid')) if primary else None,
                    'bestAsk': _number(market.get('bestAsk')) if primary else None,
                    'endsAt': end, 'windowStartsAt': start,
                    'volume': _number(market.get('volume')),
                }
    rows = sorted(output.values(), key=lambda m: (m['benchmark'], m['endsAt'], -(m['volume'] or 0)))
    return {'items': rows[:120], 'matchedCount': len(rows)}


def refresh(store, gamma):
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo('America/New_York'))
    current = {key: store.get_stale(NAMESPACE, key) or {} for key in SOURCES}
    def refresh_one(key):
        old = current[key]
        on_release_day = old.get('nextReleaseOn') == local.date().isoformat() and local.hour >= 9
        cadence = (600 if on_release_day else 3600) if key in EIA_SERIES else 1800 if key == 'hormuz' else 300
        if now.timestamp() < max(_stamp(old.get('attemptedAt')) + (300 if old.get('attemptError') else cadence), old.get('retryAt', 0)):
            return None
        attempt = now.isoformat()
        try:
            data = _eia(key, now) if key in EIA_SERIES else _hormuz(now) if key == 'hormuz' else _markets(gamma, now)
            if 'points' in data:
                point, previous = data['points'][-1], (old.get('points') or [{}])[-1]
                if point['period'] < previous.get('period', ''):
                    raise ValueError('Source returned an older period')
                data['periodSeenAt'] = old.get('periodSeenAt', attempt) if point['period'] == previous.get('period') else attempt
            return {**data, 'checkedAt': attempt, 'attemptedAt': attempt, 'status': 'ok'}
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            response = getattr(exc, 'response', None)
            retry_at = 0
            if response is not None and response.status_code == 429:
                seconds = response.headers.get('Retry-After', '')
                retry_at = now.timestamp() + (int(seconds) if seconds.isdigit() else 900)
            return {**old, 'status': 'stale' if old.get('checkedAt') else 'unavailable', 'attemptedAt': attempt,
                    'attemptError': type(exc).__name__, 'retryAt': retry_at}

    with ThreadPoolExecutor(max_workers=3) as pool:
        for key, data in zip(SOURCES, pool.map(refresh_one, SOURCES)):
            if data is not None:
                if store.set(NAMESPACE, key, data, RETENTION, max_entries=len(SOURCES)) is False:
                    raise RuntimeError(f'Oil snapshot write rejected: {key}')
                current[key] = data
    return {key: row.get('status', 'unavailable') for key, row in current.items()}


def read(store, futures):
    now = datetime.now(timezone.utc).timestamp()
    data = {
        key: (store.get_stale(NAMESPACE, key) or {}) if store is not None else {}
        for key in SOURCES
    }
    for key, row in data.items():
        age = now - _stamp(row.get('checkedAt'))
        if age > RETENTION:
            data[key] = {'status': 'unavailable'}
        elif age > (900 if key == 'markets' else 7200 if key == 'hormuz' else 8 * 3600):
            data[key] = {**row, 'status': 'stale'}
    market_data = data['markets']
    market_data['items'] = [m for m in market_data.get('items', ()) if _stamp(m.get('endsAt')) > now]
    return {**data, 'futures': [
        {key: row.get(key) for key in ('id', 'symbol', 'price', 'changePercent', 'changeBasis', 'quoteAt', 'acquisitionState', 'marketState')}
        for row in futures if row.get('id') in {'brent', 'oil'} and row.get('instrumentType') == 'FUTURE'
    ]}
