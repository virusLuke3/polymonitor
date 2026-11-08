"""Real domain boundaries: source modes, units, fiscal periods and evidence types."""
import json
import pytest
from api.services.finance_expansion import parsers, get_snapshot
from api.services.panel_evidence_store import SourceSpec, collect_one, read_source
from runtime.snapshot_store import SnapshotStore


def blob(value):
    return json.dumps(value).encode()


def test_product_mode_is_not_first_trade_or_deposit_status():
    base={'id':'T-USD','base_currency':'T','quote_currency':'USD','status':'online','trading_disabled':False,'cancel_only':False,'post_only':False,'limit_only':False,'auction_mode':False}
    p=parsers.products(blob([base]))['products'][0]
    assert p['mode']=='online'
    assert 'firstTradeAt' not in p and 'depositEnabled' not in p
    assert parsers.products(blob([{**base,'post_only':True}]))['products'][0]['mode']=='post-only'
    assert parsers.products(blob([{**base,'trading_disabled':None}]))['products'][0]['mode']=='unknown'
    assert parsers.products(blob([]))['availableProducts']==0


def test_release_not_automatic_mainnet_execution():
    rows=parsers.releases(blob([{'id':4,'tag_name':'v2','published_at':'2026-11-08T00:00:00Z','html_url':'https://example.test/release/v2','prerelease':True}]),{'id':'p','name':'Project'})['releases']
    assert rows[0]['prerelease'] is True
    assert rows[0]['executionStatus']=='not-verified'
    assert rows[0]['publishedAt']=='2026-11-08T00:00:00Z'


def test_tvl_chain_mix_excludes_borrowed_and_preserves_source_time():
    v=parsers.protocol(blob({'name':'Protocol','tvl':[{'date':1735689600,'totalLiquidityUSD':100}], 'currentChainTvls':{'Ethereum':80,'Base':20,'Ethereum-borrowed':50,'borrowed':50,'staking':10}}),{'id':'p'})
    assert v['tvl']==100
    assert sum(x['value'] for x in v['chains'])==100
    assert v['observedAt'].startswith('2025-01-01')
    with pytest.raises(ValueError):parsers.protocol(blob({'name':'P','tvl':[{'date':1735689600,'totalLiquidityUSD':None}]}),{'id':'p'})


def test_cash_million_units_and_missing_is_not_zero():
    rows=[{'record_date':'2026-11-05','account_type':'Treasury General Account (TGA) Opening Balance','open_today_bal':'100'}, {'record_date':'2026-11-05','account_type':'Total TGA Deposits (Table II)','open_today_bal':'20'}, {'record_date':'2026-11-05','account_type':'Treasury General Account (TGA) Closing Balance','open_today_bal':'null','close_today_bal':'105'}]
    p=parsers.fiscal_cash(blob({'data':rows}))
    assert p['opening']==100_000_000 and p['deposits']==20_000_000
    assert p['closing']==105_000_000 and p['withdrawals'] is None


def test_monthly_budget_selects_fiscal_year_parent_and_not_decimal_sequence():
    rows=[{'record_date':'2026-09-30','classification_desc':'FY 2025','classification_id':'a'}, {'record_date':'2026-09-30','classification_desc':'FY 2026','classification_id':'b'}]
    for parent,month,seq in [('a','September','1.12'),('b','September','2.12'),('b','October','2.1'),('b','July','2.10')]:
        rows.append({'record_date':'2026-09-30','parent_id':parent,'record_type_cd':'MTH','classification_desc':month,'sequence_number_cd':seq,'current_month_gross_rcpt_amt':'100','current_month_gross_outly_amt':'120','record_fiscal_year':'2026'})
    result=parsers.fiscal_monthly(blob({'data':rows}))
    assert [r['month'] for r in result['months']]==['October','July','September']
    assert result['months'][0]['balance']==-20
    assert all(r['fiscalYear']=='2026' for r in result['months'])


def test_tax_year_carried_into_other_filing_status_tables():
    body=b'<h2>2025 tax rates for a single taxpayer</h2><table><tr><td>10%</td><td>$0</td></tr></table><h3>Married filing jointly</h3><table><tr><td>10%</td><td>$0</td></tr></table>'
    rows=parsers.tax_brackets(body)['tables']
    assert rows[1]['taxYear']==2025 and rows[1]['heading'].startswith('2025')


def test_merger_filing_not_inferred_deal_closing():
    v={'cik':12,'name':'Issuer','filings':{'recent':{'accessionNumber':['x','y'],'form':['8-K','10-Q'],'items':['2.01',''],'primaryDocument':['doc.htm','q.htm'],'filingDate':['2026-11-08','2026-11-07']}}}
    p=parsers.capital_filings(blob(v),{'cik':'0000000012','name':'Issuer'},'https://example.test/archives')['filings']
    assert len(p)==1 and p[0]['items']==['2.01']
    assert p[0]['closingStatus']=='not-verified' and p[0]['consideration'] is None
    with pytest.raises(ValueError):parsers.capital_filings(blob(v),{'cik':'13','name':'Other'},'')


def test_financing_requires_dated_explicit_post_money_not_funding_or_revenue():
    company={'id':'c','name':'Company','url':'https://example.test/funding','round':'Series B'}
    body=b'<meta property="article:published_time" content="2025-09-02"><main>Announcing new funding\xe2\x80\x94$40 billion at a $300 billion post-money valuation.</main>'
    p=parsers.financing_announcement(body,company)
    assert p['postMoney']==300e9 and p['raised']==40e9 and p['publishedAt']=='2025-09-02'
    assert p['currentValuation'] is None and p['securityClass'] is None
    with pytest.raises(ValueError):parsers.financing_announcement(body.replace(b'post-money valuation',b'annual revenue'),company)


def test_failed_source_keeps_last_good_and_expiry(monkeypatch,tmp_path):
    monkeypatch.setenv('TEST_FINANCE_URL','https://example.test/data')
    monkeypatch.setenv('POLYMONITOR_EXTERNAL_EVIDENCE_SQLITE_PATH',str(tmp_path/'evidence.sqlite3'))
    store=SnapshotStore(str(tmp_path/'snapshots.sqlite3'))
    spec=SourceSpec('test','Test','TEST_FINANCE_URL',lambda b:json.loads(b),cadence=300,stale_after=900,retain_for=1800)
    collect_one(store,spec,acquire=lambda:(b'{"value":3}',{'value':3}),now=1000)
    def failure():raise TimeoutError()
    collect_one(store,spec,acquire=failure,force=True,now=1400)
    data,meta=read_source(store,spec,now=1500)
    assert data=={'value':3} and meta['lastSuccessAt'].startswith('1970-01-01T00:16:40')
    assert meta['error']=='TimeoutError'
    assert read_source(store,spec,now=2801)[0]=={}


def test_api_is_read_only_and_unknown_ids_rejected(monkeypatch,tmp_path):
    monkeypatch.setattr('api.services.finance_expansion.specs',lambda:[])
    store=SnapshotStore(str(tmp_path/'snapshots.sqlite3'))
    p=get_snapshot(store,'merger-progress')
    assert p['status']=='unavailable' and p['filings']==[] and p['generatedAt'] is None
    with pytest.raises(ValueError):get_snapshot(store,'invented-panel')
