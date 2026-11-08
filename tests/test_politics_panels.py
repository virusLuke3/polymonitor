import io
import json
import sqlite3
import zipfile

import pytest
from api.services.politics import normalizers as n
from api.services.politics import snapshots
from api.services.politics.store import SOURCE_NS, archive, collect, source
from runtime.snapshot_store import SnapshotStore


def packed(text):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        z.writestr("source.txt", text)
    return output.getvalue()


def test_poll_support_is_not_win_probability_or_undecided():
    raw = {"meta": {"count": 1}, "polls": [{"raceId": "x", "date": "2026-01-01", "results": {"a": 46, "b": 43}}]}
    data = n.polls(json.dumps(raw).encode())
    assert data["items"][0]["publishedAt"] is None
    assert data["items"][0]["results"] == [{"name": "a", "value": 46}, {"name": "b", "value": 43}]
    raw["polls"][0]["results"]["a"] = 101
    with pytest.raises(ValueError):
        n.polls(json.dumps(raw).encode())


def test_early_vote_does_not_merge_unaccepted_ballots():
    data = n.early_vote(packed("election_date,county_name,abs_sent,abs_accepted,abs_spoiled_EV,abs_received_not_counted,abs_outstanding\n11/03/2026,A,100,60,10,5,35\n"))
    assert data["totals"]["accepted"] == 60
    assert data["totals"]["receivedNotCounted"] == 5
    assert data["expectedCounties"] == 100 and len(data["items"]) == 1


def test_nc_null_party_is_empty_but_duplicate_precinct_is_rejected():
    header = "County\tElection Date\tPrecinct\tContest Group ID\tContest Name\tChoice\tChoice Party\tTotal Votes\n"
    line = "A\t11/03/2026\t01\t123\tUS SENATE\tWrite-in\t\x00\t10\n"
    result = n.nc_results(packed(header + line))["items"][0]
    assert result["choices"][0]["party"] == "" and result["certified"] is None
    with pytest.raises(ValueError, match="Duplicate"):
        n.nc_results(packed(header + line + line))


def test_fec_transfers_period_and_absent_money_remain_distinct():
    row = [""] * 30
    for i, value in {0: "H0XX00001", 1: "Candidate", 5: "100", 6: "20", 7: "50", 8: "10", 10: "0", 27: "09/30/2026"}.items():
        row[i] = value
    data = n.finance(packed("|".join(row)))["items"][0]
    assert data["receipts"] == 100 and data["transfersIn"] == 20
    assert data["cash"] == 0 and data["debt"] is None
    assert data["periodEnd"] == "2026-09-30"


def test_xml_entities_and_zip_expansion_rejected():
    with pytest.raises(ValueError):
        n.xml(b'<!DOCTYPE a [<!ENTITY x "y">]><a/>')
    with pytest.raises(ValueError):
        n.unzip(packed("x" * 100), max_bytes=50)


def test_bill_identity_text_versions_and_votes_remain_separate():
    result = n.bill_status(b'<billStatus><bill><congress>119</congress><type>HR</type><number>1</number><title>T</title><actions><item><actionDate>2026-01-01</actionDate><text>Procedural motion</text><type>Floor</type></item></actions><cosponsors><item/></cosponsors><textVersions><item><type>Introduced</type><formats><item><url>https://www.govinfo.gov/x.xml</url></item></formats></item></textVersions></bill></billStatus>')
    assert result["id"] == "119hr1" and result["cosponsors"] == 1
    assert result["laws"] == [] and result["actions"][0]["votes"] == []


def test_funding_date_does_not_invent_exact_time_or_current_coverage():
    body = '<pre>Public Law 119-103 fiscal year 2027 Sec. 101. ' + ' '.join(f'({i}) The class {i}.' for i in range(1, 13)) + ' Sec. 102. other Sec. 106. (3) &lt;&lt;NOTE: Expiration date.&gt;&gt; December 11, 2026. Sec. 107. end</pre>'
    data = n.funding_law(body.encode())
    assert data["expirationDate"] == "2026-12-11" and data["expirationTime"] is None
    assert not data["currentCoverageVerified"] and len(data["coverage"]) == 12


def test_refresh_failure_and_restart_keep_last_good(tmp_path):
    store = SnapshotStore(str(tmp_path / "snapshots.sqlite3"))
    good = collect(store, "test", lambda: (b'{"x":1}', {"x": 1}), 30, now=1000)
    def failure():
        raise TimeoutError("URL containing secret must not be persisted")
    bad = collect(store, "test", failure, 30, now=1031)
    assert bad["data"] == {"x": 1} and bad["lastSuccessAt"] == good["lastSuccessAt"]
    assert bad["error"] == "TimeoutError"
    restart = SnapshotStore(store.db_path)
    assert collect(restart, "test", lambda: pytest.fail("backoff lost"), 30, now=1040) == bad
    with sqlite3.connect(tmp_path / "politics.sqlite3") as db:
        assert db.execute("select count(*) from evidence").fetchone()[0] == 1


def test_archive_capacity_failure_cannot_publish_success(tmp_path):
    store = SnapshotStore(str(tmp_path / "snapshots.sqlite3"))
    archive(store, "x", b"x", {}, 1000)
    with pytest.raises(ValueError, match="capacity"):
        archive(store, "x", b"y", {}, 1001, budget=1)


def test_public_read_has_no_writes_and_rechecks_source_age(tmp_path, monkeypatch):
    store = SnapshotStore(str(tmp_path / "snapshots.sqlite3"))
    collect(store, "house-roster", lambda: (b"ok", {"items": [], "counts": {}}), 1800, now=1000)
    monkeypatch.setattr(store, "set", lambda *a, **kw: pytest.fail("public read wrote state"))
    read = snapshots.get_snapshot(store, "politics-seats")
    assert read["sources"][0]["stale"]
    assert read["sources"][0]["lastSuccessAt"].startswith("1970")


def test_all_politics_routes_registered_without_extra_visible_legislation_panel():
    from api.runtime_panels.registry import DEFAULT_WORKSPACE_PANEL_IDS, get_panel_ids
    # The legislation API is consumed inside the existing Policy Progress panel.
    assert "politics-legislation" not in DEFAULT_WORKSPACE_PANEL_IDS
    assert all(p in DEFAULT_WORKSPACE_PANEL_IDS for p in snapshots.PANELS if p != "politics-legislation")
    assert all(p in get_panel_ids() for p in snapshots.PANELS)


def test_transport_accepts_only_verified_fec_redirect(monkeypatch):
    from api.services.politics import collector
    class Response:
        def __init__(self, status, location=None):
            self.status_code = status
            self.headers = {"Location": location} if location else {}
        def close(self): pass
        def raise_for_status(self): pass
        def iter_content(self, chunk_size): yield b"source"
        def __enter__(self): return self
        def __exit__(self, *args): self.close()
    class Session:
        trust_env = True
        def __init__(self, destination): self.destination, self.calls = destination, []
        def request(self, method, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response(302, self.destination) if len(self.calls) == 1 else Response(200)
        def close(self): pass
    destination = "https://cg-519a459a-0ea3-42c2-b7bc-fa1143481f74.s3-us-gov-west-1.amazonaws.com/bulk-downloads/2026/weball26.zip"
    session = Session(destination)
    monkeypatch.setattr(collector, "source_session", lambda: session)
    transport = collector.Transport()
    assert transport.get("https://www.fec.gov/files/bulk-downloads/2026/weball26.zip") == b"source"
    assert len(session.calls) == 2 and all(call[1]["allow_redirects"] is False for call in session.calls)
    session = Session("http://127.0.0.1/private")
    transport = collector.Transport()
    with pytest.raises(ValueError, match="redirected"):
        transport.get("https://www.fec.gov/files/bulk-downloads/2026/weball26.zip")
    assert len(session.calls) == 1


def test_bill_404_backoff_survives_restart_and_does_not_erase_success(tmp_path):
    import requests
    store = SnapshotStore(str(tmp_path / 'snapshots.sqlite3'))
    response = requests.Response()
    response.status_code = 404
    def missing():
        raise requests.HTTPError('private URL', response=response)
    first = collect(store, 'bill:119hres1648', missing, 1800, now=1000)
    assert first['error'] == 'HTTP 404' and first['nextAttemptAt'] == 4600
    restarted = SnapshotStore(store.db_path)
    assert collect(restarted, 'bill:119hres1648', lambda: pytest.fail('404 retried early'), 1800, now=2000) == first
    second = collect(restarted, 'bill:119hres1648', missing, 1800, now=4601)
    assert second['nextAttemptAt'] == 11801 and second.get('lastSuccessAt') is None


def test_legislation_reports_failed_details_and_funding_isolates_unrelated_bill(tmp_path, monkeypatch):
    from api.services.politics import store as storage
    from api.services.politics.catalog import catalog
    store = SnapshotStore(str(tmp_path / 'snapshots.sqlite3'))
    monkeypatch.setattr(storage.time, 'time', lambda: 1000)
    feed_key = next(spec.key for spec in catalog() if spec.key.startswith('bills-'))
    for key, data in [(feed_key, {'items': [{'id': '119hres1648', 'title': 'An unrelated resolution'}]}),
                      ('funding-law-119-103', {'title': 'Current law'}),
                      ('bill:119hr6500', {'id': '119hr6500', 'title': 'Appropriations'})]:
        collect(store, key, lambda data=data: (b'data', data), 1800, now=900)
    store.set(SOURCE_NS, 'bill:119hres1648', {'lastAttemptAt': 950, 'error': 'HTTP 404'}, 1000)
    store.set(SOURCE_NS, 'bill-index', {'ids': ['119hres1648', '119hr6500'],
              'targetIds': ['119hres1648', '119hr6500'], 'targetCount': 2}, 1000)
    legislation = snapshots.get_snapshot(store, 'politics-legislation')
    assert legislation['status'] == 'degraded' and legislation['failedCount'] == 1
    assert legislation['acquiredCount'] == 1 and legislation['pendingCount'] == 1
    assert legislation['generatedAt'] == storage.iso(900)
    assert snapshots.get_snapshot(store, 'politics-funding')['status'] == 'ok'


def test_bill_freshness_accounts_for_bounded_rotation_without_more_fetches(tmp_path):
    from api.services.politics.store import bill_refresh_interval
    store = SnapshotStore(str(tmp_path / 'snapshots.sqlite3'))
    collect(store, 'bill:119hr1', lambda: (b'body', {'id': '119hr1'}), 1800, now=1000)
    store.set(SOURCE_NS, 'bill-index', {'targetCount': 101}, 1000)
    assert bill_refresh_interval(101) == 6300
    _, meta = source(store, 'bill:119hr1', 'url', now=1000 + 6300)
    assert not meta['stale'] and meta['expectedIntervalSeconds'] == 6300
    assert meta['staleAfterSeconds'] == 18900
    assert source(store, 'bill:119hr1', 'url', now=1000 + 18901)[1]['stale']
    assert store.get_stale(SOURCE_NS, 'bill:119hr1')['nextAttemptAt'] == 2800
    state = store.get_stale(SOURCE_NS, 'bill:119hr1')
    store.set(SOURCE_NS, 'bill:119hr1', {**state, 'error': 'HTTP 404', 'nextAttemptAt': 999999}, 1000)
    assert source(store, 'bill:119hr1', 'url', now=1000 + 18901)[1]['stale']
    assert bill_refresh_interval(5) == 1800
