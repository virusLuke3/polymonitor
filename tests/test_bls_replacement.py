"""Isolated fixtures: transport, source identity, archive and schedule boundaries."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from api.services import bls_calendar as calendar, bls_release_archive as archive
from api.services.free_content import collector, fraser, public, store
from api.services.free_content.registry import source_map
from api.services.macro_cpi_registry_service import _period_from_release
from runtime.snapshot_store import SnapshotStore
from test_free_content import storage  # noqa: F401 -- shared isolated database fixture

TEXT = """Transmission of material in this release is embargoed until USDL-26-1574
8:30 a.m. (ET) Wednesday, October 14, 2026
CONSUMER PRICE INDEX – SEPTEMBER 2026
The U.S. Bureau of Labor Statistics reported the index today.
The Consumer Price Index news release for October 2026 is scheduled to be published on
Tuesday, November 10, 2026, at 8:30 a.m. (ET).
"""
PDF_URL = "https://fraser.stlouisfed.org/docs/fixture.pdf"
ITEM_URL = "https://fraser.stlouisfed.org/title/consumer-price-index-6838/september-2026-738026"


def fred(kind="cpi", date="November 10, 2026", clock="7:30 am"):
    return f'<table class="table-standard-theme"><tr><td>{date}</td></tr><tr><td>{clock}</td><td><a href="/release?rid={calendar.RELEASE_IDS[kind]}">Release</a></td></tr></table>'


def nyfed(day=10):
    return f'<div>November 2026</div><table class="research-table-1col"><tr><td><div>{day}<span><a href="https://www.bls.gov/news.release/cpi.toc.htm">Consumer Price Index</a><br/>(08:30)</span></div></td></tr></table>'


def fake_get(url, **kwargs):
    if url == calendar.NYFED_URL:
        return nyfed()
    kind = next(k for k, rid in calendar.RELEASE_IDS.items() if f"rid={rid}&" in url)
    return fred(kind)


def test_calendar_timezones_and_year_rollover():
    assert calendar.parse_fred(fred(), "cpi", 2026)[0]["releaseAt"] == "2026-11-10T13:30:00Z"
    assert calendar.parse_nyfed(nyfed())[0]["releaseAt"] == "2026-11-10T13:30:00Z"
    summer = calendar.parse_fred(fred(date="July 14, 2026"), "cpi", 2026)[0]
    assert summer["releaseAt"] == "2026-07-14T12:30:00Z"
    january = calendar.parse_fred(fred(date="January 12, 2027"), "cpi", 2027)[0]
    assert january["releaseAt"] == "2027-01-12T13:30:00Z"
    with pytest.raises(ValueError, match="wrong-year"):
        calendar.parse_fred(fred(date="January 12, 2027"), "cpi", 2026)


def test_unknown_period_is_not_fabricated_from_release_date():
    assert _period_from_release({"releaseAt": "2026-11-10T13:30:00Z"}) is None
    row = calendar.parse_fred(fred(), "cpi", 2026)[0]
    assert calendar.bind_period(row, {})["referencePeriod"] is None


def test_original_pdf_supplies_reference_period_and_dst():
    record = {**archive.parse_release(TEXT, "cpi"), "pdfUrl": PDF_URL}
    assert record["published_at"] == "2026-10-14T12:30:00Z"
    assert record["next_release"] == {"referencePeriod": "October 2026", "releaseAt": "2026-11-10T13:30:00Z"}
    row = calendar.bind_period(calendar.parse_fred(fred(), "cpi", 2026)[0], record)
    assert row["referencePeriod"] == "October 2026"
    assert row["referencePeriodSourceUrl"] == PDF_URL
    with pytest.raises(ValueError, match="identity-missing"):
        archive.parse_release(TEXT, "ppi")
    with pytest.raises(ValueError, match="not-pdf"):
        archive.extract_text(b"<html>Access Denied</html>")


def test_fred_failure_uses_nyfed_without_inventing_success():
    def get(url, **kwargs):
        if url != calendar.NYFED_URL:
            raise TimeoutError("fixture")
        return nyfed()
    rows, states, errors, conflicts = calendar.build(get, None, datetime(2026, 11, 4, tzinfo=timezone.utc))
    assert len(rows) == 1 and rows[0]["sourceUrl"] == calendar.NYFED_URL
    assert states["fredCpi"] == "error" and states["cpiSchedule"] == "ok"
    assert errors and not conflicts


def test_conflicting_calendars_do_not_select_an_arbitrary_date():
    def get(url, **kwargs):
        return nyfed(11) if url == calendar.NYFED_URL else fake_get(url)
    rows, states, errors, conflicts = calendar.build(get, None, datetime(2026, 11, 4, tzinfo=timezone.utc))
    assert not [r for r in rows if r["kind"] == "cpi"]
    assert states["cpiSchedule"] == "conflict"
    assert {r["releaseAt"] for r in conflicts[0]["candidates"]} == {"2026-11-10T13:30:00Z", "2026-11-11T13:30:00Z"}


def test_failed_calendar_keeps_original_verified_time_with_seven_day_bound():
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)
    old = {**calendar.parse_fred(fred(), "cpi", 2026)[0], "verifiedAt": "2026-11-03T00:00:00Z"}
    def fail(*args, **kwargs):
        raise TimeoutError("fixture")
    rows, *_ = calendar.build(fail, None, now, {"items": [old]})
    assert rows[0]["verifiedAt"] == old["verifiedAt"] and rows[0]["retained"]
    assert calendar.build(fail, None, now + timedelta(days=8), {"items": [old]})[0] == []


@pytest.mark.parametrize("routed", [False, True])
def test_archive_transport_ingestion_restart_and_news_window(storage, tmp_path, monkeypatch, routed):
    source = source_map()["bls-cpi"]
    snapshots = SnapshotStore(str(tmp_path / "snapshots.sqlite"))
    calls = []
    session_type = requests.Session
    def configured_session():
        session = session_type()
        if routed:
            session.routes = {"fraser.stlouisfed.org": ["http://127.0.0.1:17890", ""]}
        return session
    monkeypatch.setattr(requests, "Session", configured_session)
    def fetch(session, url, configured, state, **kwargs):
        assert session.trust_env is False and not session.proxies
        calls.append((url, state))
        meta = {"http_status": 200, "final_url": url, "etag": '"v1"'}
        if url == source["feed_url"]:
            return f'<a class="list-item" data-type="item" data-id="738026" href="{ITEM_URL}">September 2026</a>'.encode(), meta
        if url == ITEM_URL:
            return f'<meta name="citation_pdf_url" content="{PDF_URL}">'.encode(), meta
        if state.get("etag"):
            return b"", {**meta, "http_status": 304}
        return b"%PDF-fixture-original", meta
    monkeypatch.setattr(fraser, "fetch", fetch)
    monkeypatch.setattr(fraser, "extract_text", lambda *args, **kwargs: TEXT)
    legacy = {"title": "Previous official RSS title", "url": "https://www.bls.gov/news.release/archives/cpi_10142026.htm",
              "published_at": "2026-10-14T11:50:31.200000Z", "summary": "Old feed excerpt",
              "source_kind": "official_release", "topics": ["cpi"]}
    store.persist(storage, source, [legacy], "2026-10-14T12:00:00Z")
    first = collector.collect_one(storage, snapshots, source, {})
    assert first["status"] == "ok" and first["updated"] == 1 and first["new"] == 0 and first["public"] == 1
    assert first["proxy_mode"] == ("configured-routes" if routed else "direct")
    record = archive.read_latest(snapshots, "cpi")
    assert (archive.archive_root(snapshots) / "cpi" / record["pdfFile"]).read_bytes() == b"%PDF-fixture-original"
    second = collector.collect_one(storage, SnapshotStore(snapshots.db_path), source, first)
    assert second["duplicate"] == 1 and second["reused_archive"]
    assert len(calls) == 5  # Directory and item checked; unchanged PDF stays local.
    assert second["pdf_checked_at"] == first["pdf_checked_at"]
    assert second["updated"] == 0
    assert datetime.fromisoformat(second["next_check_at"].replace("Z", "+00:00")) - datetime.fromisoformat(second["checked_at"].replace("Z", "+00:00")) == timedelta(hours=6)
    rows = storage.query_all("SELECT raw_payload FROM content_items")
    assert len(rows) == 1
    item = json.loads(rows[0]["raw_payload"])
    assert item["published_at"] == "2026-10-14T12:30:00Z"
    assert item["first_seen_at"] == "2026-10-14T12:00:00Z"
    assert public.eligible_item(rows[0]["raw_payload"], source_map(), "2026-10-28T00:00:00Z", datetime(2026, 11, 4, tzinfo=timezone.utc))[1] == "window"
    assert archive.read_latest(snapshots, "cpi")["receivedAt"] == record["receivedAt"]
    # Restarted owners still revalidate the same URL for upstream revisions.
    third = collector.collect_one(storage, snapshots, source,
                                  {**second, "pdf_checked_at": "2000-01-01T00:00:00Z"})
    assert third["pdf_http_status"] == 304 and not third["reused_archive"]
    assert len(calls) == 8
    assert archive.read_latest(snapshots, "cpi")["receivedAt"] == record["receivedAt"]
    # A news-retention cleanup cannot remove the formal original-document archive.
    store.prune(storage, {"retention_days": 90, "max_items": 20000, "max_versions_per_item": 12}, "2028-01-01T00:00:00Z")
    assert storage.query_all("SELECT id FROM content_items") == []
    assert (archive.archive_root(snapshots) / "cpi" / record["pdfFile"]).exists()


def test_archive_revision_does_not_overwrite_original_or_receipt(tmp_path):
    snapshots = SnapshotStore(str(tmp_path / "snapshot.sqlite"))
    meta = {**archive.parse_release(TEXT, "cpi"), "receivedAt": "2026-11-04T03:00:00Z"}
    first = archive.save_document(snapshots, "cpi", b"%PDF-one", TEXT, meta)
    repeated = archive.save_document(snapshots, "cpi", b"%PDF-one", TEXT, {**meta, "receivedAt": "2026-11-05T03:00:00Z"})
    second = archive.save_document(snapshots, "cpi", b"%PDF-two", TEXT, meta)
    assert repeated["receivedAt"] == first["receivedAt"]
    assert first["sha256"] != second["sha256"]
    assert len(list((archive.archive_root(snapshots) / "cpi").glob("*.pdf"))) == 2


def test_archive_revalidation_without_http_validators_skips_unchanged_pdf_extraction(tmp_path, monkeypatch):
    import time
    snapshots = SnapshotStore(str(tmp_path / "snapshot.sqlite"))
    metadata = {**archive.parse_release(TEXT, "cpi"), "archiveUrl": ITEM_URL, "pdfUrl": PDF_URL,
                "receivedAt": "2026-11-04T03:00:00Z", "distributor": "FRASER", "pdfHttp": {}}
    record = archive.save_document(snapshots, "cpi", b"%PDF-same", TEXT, metadata)
    source = source_map()["bls-cpi"]
    calls = []
    def fetch(session, url, configured, state, **kwargs):
        calls.append(url)
        body = (f'<a class="list-item" data-type="item" href="{ITEM_URL}">September 2026</a>'.encode()
                if url == source["feed_url"] else f'<meta name="citation_pdf_url" content="{PDF_URL}">'.encode()
                if url == ITEM_URL else b"%PDF-same")
        return body, {"http_status": 200, "etag": None, "last_modified": None}
    monkeypatch.setattr(fraser, "fetch", fetch)
    monkeypatch.setattr(fraser, "extract_text", lambda *a, **kw: pytest.fail("Unchanged PDF extracted again"))
    with requests.Session() as session:
        items, meta = fraser.collect(session, snapshots, source, deadline=time.monotonic()+45)
        assert len(calls) == 3 and not meta["reused_archive"]
        _, reused = fraser.collect(session, snapshots, source, deadline=time.monotonic()+45, source_state=meta)
        assert len(calls) == 5 and reused["reused_archive"]
    assert items[0]["archive_received_at"] == record["receivedAt"]


def test_archive_domain_queue_wait_does_not_consume_next_release_io_allowance(monkeypatch):
    clock = [100.]
    deadlines = []
    class QueuedLock:
        def acquire(self, timeout):
            assert timeout == 45
            clock[0] = 140.
            return True
        def release(self):
            pass
    def failed_fetch(session, url, source, state, deadline):
        deadlines.append(deadline)
        raise ValueError("fixture-stop")
    monkeypatch.setattr(fraser, "DOMAIN_LOCK", QueuedLock())
    monkeypatch.setattr(fraser.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(fraser, "_checked_fetch", failed_fetch)
    with requests.Session() as session, pytest.raises(ValueError, match="fixture-stop"):
        fraser.collect(session, None, source_map()["bls-cpi"], deadline=145.)
    assert deadlines == [185.]


def test_old_source_error_does_not_advance_on_bad_archive(storage, tmp_path, monkeypatch):
    monkeypatch.setattr(fraser, "collect", lambda *a, **k: (_ for _ in ()).throw(ValueError("invalid-pdf")))
    old = {"last_success_at": "2026-11-01T00:00:00Z"}
    result = collector.collect_one(storage, SnapshotStore(str(tmp_path / "snapshot.sqlite")), source_map()["bls-cpi"], old)
    assert result["status"] == "error" and result["last_success_at"] == old["last_success_at"]
    assert storage.query_all("SELECT id FROM content_items") == []
