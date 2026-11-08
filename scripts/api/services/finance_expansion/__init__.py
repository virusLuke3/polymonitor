"""Finance / token-event projections over scheduled, durable public evidence."""
from __future__ import annotations

import json
import time
from functools import partial

from data_sources import source_value
from api.services.panel_evidence_store import SourceSpec, collect_one, fetch_bytes, payload, read_source
from . import parsers

PANEL_IDS = ('crypto-listing-watch', 'crypto-project-milestones', 'chain-metrics-monitor',
             'fiscal-tax-monitor', 'merger-progress', 'private-valuation-watch')


def catalog(name):
    value = source_value(name)
    if not value:
        return []
    try:
        result = json.loads(value)
    except (ValueError, TypeError):
        return []
    if not isinstance(result, list) or len(result) > 20:
        return []
    return [r for r in result if isinstance(r, dict) and isinstance(r.get('id'), str) and isinstance(r.get('name'), str)]


def specs():
    result = []
    def add(key, label, env, parse, cadence=3600, *, url=None, stale=None, retention=7*86400, max_bytes=8*1024**2, headers=None):
        result.append((SourceSpec(key, label, env, parse, cadence, stale or cadence*3, retention, max_bytes, 45, headers), url))
    add('token-events:products', 'Coinbase Exchange products', 'POLYMONITOR_TOKEN_PRODUCTS_URL', parsers.products, 300, stale=900, retention=1800)
    for project in catalog('POLYMONITOR_TOKEN_RELEASES_JSON'):
        add('token-events:release:'+project['id'], project['name']+' releases', 'POLYMONITOR_TOKEN_RELEASES_JSON',
            partial(parsers.releases, project=project), 1800, url=project.get('url'))
    for protocol in catalog('POLYMONITOR_CHAIN_METRICS_JSON'):
        add('chain-metrics:tvl:'+protocol['id'], protocol['name']+' TVL', 'POLYMONITOR_CHAIN_METRICS_JSON',
            partial(parsers.protocol, item=protocol), 3600, url=protocol.get('tvlUrl'), retention=86400, max_bytes=16*1024**2)
        if protocol.get('feesUrl'):
            add('chain-metrics:fees:'+protocol['id'], protocol['name']+' fees', 'POLYMONITOR_CHAIN_METRICS_JSON',
                parsers.fees, 3600, url=protocol['feesUrl'], retention=86400)
    add('fiscal:cash', 'Treasury daily cash statement', 'POLYMONITOR_FISCAL_DTS_URL', parsers.fiscal_cash, 21600, stale=86400)
    add('fiscal:budget', 'Treasury monthly budget statement', 'POLYMONITOR_FISCAL_MTS_URL', parsers.fiscal_monthly, 86400, stale=3*86400, retention=60*86400)
    add('fiscal:tax', 'IRS federal income tax brackets', 'POLYMONITOR_IRS_TAX_TABLE_URL', parsers.tax_brackets, 86400, stale=3*86400)
    archive_base = source_value('POLYMONITOR_URL_WWW_SEC_GOV_ARCHIVES_EDGAR_DATA_69AE63')
    for company in catalog('POLYMONITOR_CAPITAL_SUBMISSIONS_JSON'):
        if not str(company.get('cik', '')).isdecimal():
            continue
        add('company-capital:sec:'+company['id'], company['name']+' SEC filings', 'POLYMONITOR_CAPITAL_SUBMISSIONS_JSON',
            partial(parsers.capital_filings, company=company, archive_base=archive_base), 1800, url=company.get('url'),
            stale=5400, retention=86400, headers={'User-Agent': source_value('POLYMONITOR_SEC_USER_AGENT')})
    for company in catalog('POLYMONITOR_COMPANY_CAPITAL_SOURCE_CATALOG_JSON'):
        add('company-capital:announcement:'+company['id'], company['name']+' official financing announcement',
            'POLYMONITOR_COMPANY_CAPITAL_SOURCE_CATALOG_JSON', partial(parsers.financing_announcement, company=company),
            21600, url=company.get('url'), stale=43200)
    return result


def collect(store):
    """One bounded family task, source clocks survive retries and process restarts."""
    definitions = specs()
    # Independent source clocks prevent a failed five-minute source accelerating
    # monthly statistics or blocking later sources forever.
    from api.services.panel_evidence_store import NAMESPACE
    definitions.sort(key=lambda pair: (store.get_stale(NAMESPACE, pair[0].key) or {}).get('lastAttemptAt', 0))
    deadline = time.monotonic() + 720
    result = {}
    for spec, url in definitions:
        if deadline-time.monotonic() < spec.timeout:
            result[spec.key] = 'deferred-budget'
            continue
        def acquire(spec=spec, url=url):
            if spec.key.startswith('company-capital:sec:') and not source_value('POLYMONITOR_SEC_USER_AGENT'):
                raise ValueError('SEC contact User-Agent is not configured')
            if spec.key.startswith('company-capital:sec:'):
                # SEC retains the existing contact identity and dedicated env proxy.
                from api.clients.source_transport import source_session
                from runtime.official_disclosures_watcher import Transport
                with source_session() as session:
                    session.trust_env = False
                    transport = Transport(session, deadline=deadline, user_agent=source_value('POLYMONITOR_SEC_USER_AGENT'))
                    body = json.dumps(transport.fetch(url), separators=(',', ':')).encode()
            else:
                body = fetch_bytes(url or source_value(spec.url_env), deadline=deadline, max_bytes=spec.max_bytes,
                                   timeout=spec.timeout, headers=spec.headers)
            return body, spec.parse(body)
        try:
            state = collect_one(store, spec, acquire=acquire, deadline=deadline)
            result[spec.key] = state.get('error') or 'stored-or-not-due'
        except TimeoutError:
            result[spec.key] = 'deferred-lock'
    return result


def get_snapshot(store, panel_id, *, limit=100):
    if panel_id not in PANEL_IDS:
        raise ValueError('Unknown finance expansion panel')
    prefix = {'crypto-listing-watch': 'token-events:products', 'crypto-project-milestones': 'token-events:release:',
              'chain-metrics-monitor': 'chain-metrics:', 'fiscal-tax-monitor': 'fiscal:',
              'merger-progress': 'company-capital:sec:', 'private-valuation-watch': 'company-capital:announcement:'}[panel_id]
    reads = {spec.key: read_source(store, spec) for spec, _ in specs() if spec.key.startswith(prefix)}
    sources = [meta for _, meta in reads.values()]
    limit = min(100, max(1, int(limit)))
    if panel_id == 'crypto-listing-watch':
        data = reads.get('token-events:products', ({}, {}))[0]
        return payload(panel_id, sources, **data)
    if panel_id == 'crypto-project-milestones':
        rows = sorted([r for data, _ in reads.values() for r in data.get('releases', [])], key=lambda r: r['publishedAt'], reverse=True)
        return payload(panel_id, sources, releases=rows[:limit], coverage='Configured public repository releases; governance, testnet and mainnet execution are not inferred.')
    if panel_id == 'chain-metrics-monitor':
        protocols = []
        for key, (data, meta) in reads.items():
            if not key.startswith('chain-metrics:tvl:') or not data:
                continue
            fee_key = 'chain-metrics:fees:'+data['id']
            fee_data, fee_meta = reads.get(fee_key, ({}, {}))
            protocols.append({**data, 'fees': fee_data or None, 'sourceId': key, 'feesSourceId': fee_key if fee_meta else None})
        return payload(panel_id, sources, protocols=protocols, coverage='Configured protocol TVL and fees. No address-count, transaction-count, gas or validator inference.')
    if panel_id == 'fiscal-tax-monitor':
        return payload(panel_id, sources, cash=reads.get('fiscal:cash', ({}, {}))[0] or None,
                       budget=reads.get('fiscal:budget', ({}, {}))[0] or None, tax=reads.get('fiscal:tax', ({}, {}))[0] or None,
                       coverage='US Treasury cash and monthly budget statements, IRS published income-tax brackets; publication periods remain separate.')
    if panel_id == 'merger-progress':
        rows = sorted([r for data, _ in reads.values() for r in data.get('filings', []) if r.get('form') not in {'D', 'D/A'}], key=lambda r: r['publishedAt'], reverse=True)
        return payload(panel_id, sources, filings=rows[:limit], issuers=[data.get('issuer') for data, _ in reads.values() if data.get('issuer')],
                       coverage='Configured issuers, merger proxy/registration and material agreement/completion disclosures. Filing type is not a verified deal or closing state.')
    return payload(panel_id, sources, financings=[data for data, _ in reads.values() if data],
                   coverage='Dated company financing announcements; not a current valuation feed. Equity class, cap table and secondary transaction data remain undisclosed.')
