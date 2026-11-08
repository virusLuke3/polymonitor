"""Public finance facts. Parsers never promote disclosure into settlement truth."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from urllib.parse import quote

from bs4 import BeautifulSoup
from api.services.panel_evidence_store import public_url


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def utc(value):
    n = number(value)
    return datetime.fromtimestamp(n, timezone.utc).isoformat() if n is not None and n > 0 else None


def products(body):
    raw = json.loads(body)
    if not isinstance(raw, list):
        raise ValueError('Invalid product catalog')
    rows = []
    for p in raw:
        if not isinstance(p, dict) or not all(isinstance(p.get(k), str) for k in ('id', 'base_currency', 'quote_currency', 'status')):
            continue
        flags = {k: p.get(k) if isinstance(p.get(k), bool) else None for k in ('trading_disabled', 'cancel_only', 'post_only', 'limit_only', 'auction_mode')}
        mode = ('disabled' if flags['trading_disabled'] or p['status'] != 'online' else 'cancel-only' if flags['cancel_only'] else
                'auction' if flags['auction_mode'] else 'post-only' if flags['post_only'] else 'limit-only' if flags['limit_only'] else
                'online' if all(v is False for v in flags.values()) else 'unknown')
        rows.append({'id': p['id'], 'base': p['base_currency'], 'quote': p['quote_currency'], 'status': p['status'], 'mode': mode, **flags})
    if raw and not rows:
        raise ValueError('No valid products')
    usd = sorted((p for p in rows if p['quote'] == 'USD'), key=lambda p: (p['mode'] == 'online', p['id']))
    return {'products': usd[:300], 'availableProducts': len(rows), 'usdProducts': len(usd), 'truncated': len(usd) > 300,
            'coverage': 'Coinbase Exchange USD product modes; listing announcement, deposit, withdrawal and first-trade dates are not provided.'}


def releases(body, project):
    raw = json.loads(body)
    if not isinstance(raw, list):
        raise ValueError('Invalid release list')
    rows = []
    for r in raw:
        if r.get('draft') or not r.get('published_at') or not public_url(r.get('html_url')) or not r.get('tag_name'):
            continue
        rows.append({'id': str(r['id']), 'projectId': project['id'], 'project': project['name'], 'version': r['tag_name'],
                     'title': r.get('name') or r['tag_name'], 'publishedAt': r['published_at'], 'url': r['html_url'],
                     'prerelease': bool(r.get('prerelease')), 'executionStatus': 'not-verified'})
    return {'releases': rows[:20], 'coverage': 'Published repository releases; mainnet execution and governance approval require separate evidence.'}


def protocol(body, item):
    raw = json.loads(body)
    if not isinstance(raw, dict) or not isinstance(raw.get('tvl'), list) or not raw.get('name'):
        raise ValueError('Invalid protocol metrics')
    history = [{'at': utc(v.get('date')), 'value': number(v.get('totalLiquidityUSD'))} for v in raw['tvl'][-90:]]
    history = [v for v in history if v['at'] and v['value'] is not None and v['value'] >= 0]
    if not history:
        raise ValueError('Missing TVL observations')
    chain_values = raw.get('currentChainTvls', {})
    chains = [{'name': k, 'value': number(v)} for k, v in chain_values.items()
              if '-' not in k and k not in {'staking', 'pool2', 'borrowed', 'vesting', 'offers', 'treasury'} and number(v) is not None and number(v) >= 0]
    return {'id': item['id'], 'name': raw['name'], 'tvl': history[-1]['value'], 'observedAt': history[-1]['at'],
            'history': history, 'chains': sorted(chains, key=lambda v: v['value'], reverse=True)[:20],
            'url': public_url(raw.get('url')), 'methodology': 'DeFiLlama reported TVL in USD; borrowed, staking and pool2 aggregates excluded from chain mix.'}


def fees(body):
    raw = json.loads(body)
    if not isinstance(raw, dict) or not isinstance(raw.get('totalDataChart'), list):
        raise ValueError('Invalid fee summary')
    points = []
    for v in raw['totalDataChart'][-30:]:
        if isinstance(v, list) and len(v) == 2 and number(v[1]) is not None and utc(v[0]):
            points.append({'at': utc(v[0]), 'value': number(v[1])})
    return {'reported24h': number(raw.get('total24h')), 'reported7d': number(raw.get('total7d')), 'history': points,
            'methodology': raw.get('methodology', {}).get('Fees') if isinstance(raw.get('methodology'), dict) else None}


def fiscal_cash(body):
    raw = json.loads(body)
    rows = raw.get('data')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Missing daily treasury rows')
    date = max(str(r.get('record_date', '')) for r in rows)
    selected = [r for r in rows if r.get('record_date') == date]
    out = {'date': date, 'unit': 'USD', 'opening': None, 'deposits': None, 'withdrawals': None, 'closing': None}
    for r in selected:
        name = str(r.get('account_type', '')).lower()
        value = number(r.get('open_today_bal'))
        if value is None:
            value = number(r.get('close_today_bal'))
        key = 'opening' if 'opening balance' in name else 'closing' if 'closing balance' in name else 'deposits' if 'total tga deposits' in name else 'withdrawals' if 'total tga withdrawals' in name else None
        if key:
            out[key] = value * 1_000_000 if value is not None else None
    if all(out[k] is None for k in ('opening', 'closing', 'deposits', 'withdrawals')):
        raise ValueError('No treasury cash fields')
    return out


def fiscal_monthly(body):
    raw = json.loads(body)
    data = raw.get('data')
    if not isinstance(data, list) or not data:
        raise ValueError('Missing monthly treasury rows')
    date = max(str(r.get('record_date', '')) for r in data)
    headers = [(int(m[1]), str(r.get('classification_id'))) for r in data
               if r.get('record_date') == date and (m := re.fullmatch(r'FY\s+(20\d{2})', str(r.get('classification_desc', ''))))]
    if not headers:
        raise ValueError('Missing fiscal-year hierarchy')
    fiscal_year, parent_id = max(headers)
    month_order = ['October', 'November', 'December', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September']
    result = []
    for r in data:
        if r.get('record_date') != date or r.get('record_type_cd') != 'MTH' or str(r.get('parent_id')) != parent_id:
            continue
        receipts, outlays = number(r.get('current_month_gross_rcpt_amt')), number(r.get('current_month_gross_outly_amt'))
        if receipts is None or outlays is None:
            continue
        result.append({'month': r.get('classification_desc'), 'fiscalYear': str(fiscal_year),
                       'receipts': receipts, 'outlays': outlays, 'balance': receipts - outlays,
                       'sequence': month_order.index(r['classification_desc']) if r.get('classification_desc') in month_order else 99})
    return {'reportDate': date, 'unit': 'USD', 'months': sorted(result, key=lambda r: r['sequence'] or 0)}


def tax_brackets(body):
    soup = BeautifulSoup(body, 'html.parser', from_encoding='utf-8')
    tables = []
    for table in soup.find_all('table'):
        heading = table.find_previous(['h2', 'h3', 'h4'])
        title = heading.get_text(' ', strip=True) if heading else ''
        cells = [[c.get_text(' ', strip=True) for c in r.find_all(['td', 'th'])] for r in table.find_all('tr')]
        if cells and any('%' in c for row in cells for c in row):
            year = next((m[0] for h in table.find_all_previous(['h2', 'h3', 'h4'])
                         if (m := re.search(r'20\d{2}', h.get_text(' ', strip=True)))), None)
            if year and year not in title:
                title = year + ' · ' + title
            tables.append({'heading': title, 'taxYear': int(year) if year else None, 'rows': cells[:10]})
    if not tables:
        raise ValueError('No tax bracket table')
    return {'tables': tables[:8], 'title': soup.title.get_text(' ', strip=True) if soup.title else 'IRS federal income tax rates'}


def capital_filings(body, company, archive_base):
    raw = json.loads(body)
    if str(raw.get('cik', '')).zfill(10) != str(company['cik']).zfill(10):
        raise ValueError('SEC issuer identity mismatch')
    recent = raw.get('filings', {}).get('recent', {})
    if not isinstance(recent.get('accessionNumber'), list):
        raise ValueError('Invalid SEC filings')
    rows = []
    for i, accession in enumerate(recent['accessionNumber']):
        def field(k):
            values = recent.get(k, [])
            return values[i] if i < len(values) else None
        form, items = field('form'), str(field('items') or '')
        if form not in {'S-4', 'S-4/A', 'DEFM14A', 'PREM14A', 'SC TO-T', 'SC TO-T/A', 'D', 'D/A'} and not (form in {'8-K', '8-K/A'} and set(items.split(',')).intersection({'1.01', '1.02', '2.01'})):
            continue
        doc, date = field('primaryDocument'), field('acceptanceDateTime') or field('filingDate')
        if not doc or not date:
            continue
        url = public_url(f"{archive_base.rstrip('/')}/{int(company['cik'])}/{accession.replace('-', '')}/{quote(doc, safe='')}") if archive_base else ''
        rows.append({'id': accession, 'issuer': raw.get('name') or company['name'], 'symbol': company.get('symbol'),
                     'cik': str(company['cik']).zfill(10), 'form': form, 'items': items.split(',') if items else [],
                     'publishedAt': date, 'url': url, 'closingStatus': 'not-verified', 'consideration': None})
    return {'filings': rows[:40], 'issuer': raw.get('name'), 'cik': company['cik'], 'availableFilings': len(rows)}


def financing_announcement(body, company):
    soup = BeautifulSoup(body, 'html.parser', from_encoding='utf-8')
    article = soup.find('article') or soup.find('main') or soup
    text = article.get_text(' ', strip=True)
    title = soup.title.get_text(' ', strip=True) if soup.title else company['name']
    publication = None
    meta = soup.find('meta', attrs={'property': 'article:published_time'})
    if meta:
        publication = meta.get('content')
    if not publication:
        timed = soup.find('time', attrs={'datetime': True})
        publication = timed.get('datetime') if timed else None
    if not publication:
        matched = re.search(r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}\b', text)
        if matched:
            publication = datetime.strptime(matched.group(), '%B %d, %Y').date().isoformat()
    # Only explicit post-money wording is accepted. Revenue, investment size,
    # enterprise value and secondary quotes cannot silently become valuation.
    valuation = re.search(r'\$([\d,.]+)\s*(billion|million|B|M)\s+(?:post[\s-]money)(?:\s+valuation)?', text, re.I)
    financing = re.search(r'(?:funding[—\s:–-]*|fundraising\s+of\s*|raised\s+|raises\s+|completed\s+a\s+)\$([\d,.]+)\s*(billion|million|B|M)\b', text, re.I)
    def amount(match):
        if not match:
            return None
        return float(match[1].replace(',', '')) * (1_000_000_000 if match[2].lower() in ('billion', 'b') else 1_000_000)
    if not publication or not valuation:
        raise ValueError('No dated explicit post-money statement')
    start = max(0, valuation.start() - 110)
    return {'id': company['id'], 'company': company['name'], 'title': title, 'publishedAt': publication,
            'postMoney': amount(valuation), 'raised': amount(financing), 'unit': 'USD', 'securityClass': None,
            'round': company.get('round'), 'url': public_url(company['url']), 'claimType': 'company-announcement',
            'evidenceExcerpt': text[start:valuation.end() + 100], 'currentValuation': None}
