import csv
import io
import json
import sqlite3

import pytest

from api.services.politics import evidence as e
from api.services.politics import snapshots
from api.services.politics.catalog import catalog
from api.services.politics.collector import collect_hearings
from api.services.politics.store import SOURCE_NS, collect
from runtime.snapshot_store import SnapshotStore


def fec(rows):
    fields = ['cand_id', 'cand_name', 'spe_id', 'spe_nam', 'exp_amo', 'sup_opp', 'file_num',
              'amndt_ind', 'tran_id', 'prev_file_num', 'receipt_dat', 'exp_date', 'dissem_dt']
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for extra in rows:
        writer.writerow({**dict.fromkeys(fields, ''), 'cand_id': 'H0XX00001', 'cand_name': 'Candidate',
                         'spe_id': 'C00000001', 'spe_nam': 'Committee', 'exp_amo': '10', 'sup_opp': 'S',
                         'amndt_ind': 'N', 'receipt_dat': '01-NOV-26', **extra})
    return out.getvalue().encode()


def test_fec_replaces_entire_filing_and_preserves_amendment_evidence():
    data = e.independent_expenditures(fec([
        {'file_num': '100', 'tran_id': 'A'}, {'file_num': '100', 'tran_id': 'B'},
        {'file_num': '200', 'tran_id': 'A', 'prev_file_num': '100', 'amndt_ind': 'A1', 'exp_amo': '12'},
        {'file_num': '300', 'tran_id': 'A', 'prev_file_num': '200', 'amndt_ind': 'A2', 'exp_amo': '14'},
    ]))
    assert [row['filingId'] for row in data['items']] == ['300']
    assert data['supersededTransactionCount'] == 3
    assert data['filingRevisionCount'] == 2
    assert data['filingRevisions'][1]['superseded']
    assert data['filingRevisions'][0]['predecessorAvailable']
    assert data['aggregation'] == 'not-aggregated'


def test_fec_unknown_direction_is_counted_not_zero_or_whole_source_failure():
    data = e.independent_expenditures(fec([
        {'file_num': '100', 'tran_id': 'A', 'sup_opp': ''},
        {'file_num': '200', 'tran_id': 'B', 'exp_amo': '0'},
        {'file_num': '300', 'tran_id': 'C', 'prev_file_num': '999', 'amndt_ind': 'A1'},
    ]))
    assert data['rawCount'] == 3 and data['availableCount'] == 2
    assert data['missingDirectionCount'] == 1 and data['partial']
    assert data['items'][1]['amount'] == 0
    assert not data['filingRevisions'][0]['predecessorAvailable']
    assert e.independent_expenditures(fec([]))['items'] == []


def test_multiple_amendments_referencing_original_do_not_double_count():
    data = e.independent_expenditures(fec([
        {'file_num': '100', 'tran_id': 'A'},
        {'file_num': '200', 'tran_id': 'A', 'prev_file_num': '100', 'amndt_ind': 'A1'},
        {'file_num': '300', 'tran_id': 'A', 'prev_file_num': '100', 'amndt_ind': 'A2'},
    ]))
    assert [r['filingId'] for r in data['items']] == ['300']
    assert data['supersededTransactionCount'] == 2


def test_fec_conflicting_transaction_is_rejected():
    with pytest.raises(ValueError, match='Conflicting'):
        e.independent_expenditures(fec([{'file_num': '100', 'tran_id': 'A'},
                                       {'file_num': '100', 'tran_id': 'A', 'exp_amo': '20'}]))


def test_fec_public_projection_bound_keeps_true_denominator():
    data = e.independent_expenditures(fec([{'file_num': str(i+1), 'tran_id': 'A'} for i in range(201)]))
    assert data['availableCount'] == 201 and len(data['items']) == 200


def test_certification_schedule_is_pending_not_certified():
    body = b'<main>Finalizing 2026 Midterm Elections results on Election Day are unofficial state canvass, scheduled for 11 a.m. November 24</main>'
    row = e.nc_certification(body)['items'][0]
    assert row['status'] == 'pending' and row['certifiedAt'] is None
    assert row['scheduledDate'] == '2026-11-24' and row['timeZone'] == 'America/New_York'
    with pytest.raises(ValueError):
        e.nc_certification(b'<main>Results certified</main>')


def test_delegate_votes_do_not_claim_state_allocation_or_threshold():
    row = e.dnc_roll_call(b'August 5, 2024 Results of the electronic roll call 4,567 delegates from across the country cast their vote for Vice President Harris')['items'][0]
    assert row['delegates'] == 4567 and row['year'] == 2024
    assert row['historical'] and row['jurisdiction'] == 'US'
    assert row['threshold'] is None and row['unallocated'] is None


def test_judicial_confirmation_count_and_confirmation_not_taking_office():
    body = b'<p>Update as of 11/06/2026 Total Confirmations: 1</p><table><tr><th>Confirmation Date</th></tr><tr><td>Person</td><td>06/15/2026</td><td>09/15/2026</td><td>OHS</td><td>Former</td><td>Senior</td><td></td></tr></table>'
    data = e.judicial_confirmations(body)
    assert data['publishedAt'] == '2026-11-06'
    assert data['items'][0]['confirmedAt'] == '2026-09-15'
    assert data['items'][0]['vote'] is None and data['items'][0]['nominationId'] is None
    with pytest.raises(ValueError, match='coverage'):
        e.judicial_confirmations(body.replace(b'Confirmations: 1', b'Confirmations: 2'))


def metadata(identity='CHRG-119shrg123'):
    return f'''<mods xmlns="http://www.loc.gov/mods/v3"><recordInfo><recordIdentifier>{identity}</recordIdentifier></recordInfo><titleInfo><title>Nomination hearing</title></titleInfo><extension><heldDate>2026-03-05</heldDate><dateIngested>2026-09-29</dateIngested><congress>119</congress><witness>Person, nominee to Office</witness><congCommittee><name type="authority-standard">Committee</name></congCommittee></extension><location><url displayLabel="Content Detail">https://example.test/hearing</url></location></mods>'''.encode()


def test_hearing_uses_held_date_not_publication_or_announcement_date():
    row = e.hearing_metadata(metadata())
    assert row['heldDates'] == ['2026-03-05'] and row['publishedAt'] == '2026-09-29'
    assert row['stage'] == 'held' and row['nominationIds'] == []
    with pytest.raises(ValueError):
        e.hearing_metadata(metadata().replace(b'<heldDate>2026-03-05</heldDate>', b''))


def test_hearing_link_cannot_escape_configured_publisher(monkeypatch):
    monkeypatch.setenv('POLYMONITOR_POLITICS_HEARINGS_FEED_URL', 'https://example.test/rss/chrg.xml')
    assert e.hearings_feed(b'<rss><channel/></rss>')['items'] == []
    body = b'<rss><channel><item><guid>CHRG-119shrg123</guid><title>Nomination</title><description>&lt;a href="https://evil.test/metadata/pkg/CHRG-119shrg123/mods.xml"&gt;Metadata&lt;/a&gt;</description></item></channel></rss>'
    with pytest.raises(ValueError, match='Unexpected'):
        e.hearings_feed(body)


def test_hearing_collection_is_bounded_and_identity_checked(tmp_path):
    store = SnapshotStore(str(tmp_path / 'panel.sqlite3'))
    items = [{'id': f'CHRG-119shrg{i}', 'metadataUrl': str(i)} for i in range(5)]
    store.set(SOURCE_NS, 'nomination-hearings', {'data': {'items': items}}, 1000)
    class Transport:
        calls = []
        def get(self, url):
            self.calls.append(url)
            return metadata('CHRG-119shrg'+url)
    transport = Transport()
    collect_hearings(store, transport)
    assert len(transport.calls) == 3
    assert len([i for i in items if store.get_stale(SOURCE_NS, 'hearing:'+i['id'])]) == 3


def test_new_source_failure_first_and_lastgood_clocks_and_true_empty(tmp_path):
    store = SnapshotStore(str(tmp_path / 'panel.sqlite3'))
    def fail():
        raise ValueError('bad provider response')
    first = collect(store, 'new', fail, 3600, now=1000)
    assert first.get('lastSuccessAt') is None
    good = collect(store, 'new', lambda: (b'1', {'items': [1]}), 3600, now=1400)
    failed = collect(store, 'new', fail, 3600, now=5001)
    assert failed['lastSuccessAt'] == good['lastSuccessAt'] and failed['data']['items'] == [1]
    empty = collect(store, 'new', lambda: (b'0', {'items': []}), 3600, now=5400)
    assert empty['data']['items'] == []
    with sqlite3.connect(tmp_path / 'politics.sqlite3') as db:
        assert db.execute('select count(*) from evidence').fetchone()[0] == 2


def test_nomination_scopes_and_optional_source_failure_isolation(tmp_path):
    store = SnapshotStore(str(tmp_path / 'panel.sqlite3'))
    collect(store, 'nc-primary-20260303', lambda: (b'1', {'items': []}), 86400)
    result = snapshots.get_snapshot(store, 'politics-nomination')
    assert result['delegateApplicability'] == 'not-applicable-congressional-primary'
    assert result['delegates'] is None and result['delegateContests'] == []
    assert result['status'] == 'degraded'
    assert next(s for s in result['sources'] if s['id']=='dnc-roll-call-2024')['lastSuccessAt'] is None
    json.dumps(result, allow_nan=False)


def test_only_ie_gets_larger_body_budget():
    specs = catalog()
    assert all(s.max_bytes == (32 if s.key.startswith('fec-independent-') else 8)*1024**2 for s in specs)
    assert next(s for s in specs if s.key.startswith('fec-independent-')).cadence == 21600
