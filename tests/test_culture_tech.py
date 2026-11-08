import io
import json
import zipfile

import pytest

from api.services.culture_tech import parsers, get_snapshot, SPECS
from api.services.panel_evidence_store import collect_one
from runtime.snapshot_store import SnapshotStore


def encode(value):
    return json.dumps(value).encode()


def test_arena_keeps_source_rank_and_score_interval_separate():
    data = parsers.arena(encode({"rows": [{"row": {"model_name": "A", "rank": 3, "rating": 1200,
        "rating_lower": 1180, "rating_upper": 1220, "category": "overall", "vote_count": 90,
        "leaderboard_publish_date": "2026-01-01"}}, {"row": {"model_name": "B", "rank": 1,
        "rating": 1400, "category": "coding"}}]}))
    assert len(data["items"]) == 1
    assert data["items"][0]["rank"] == 3
    assert data["items"][0]["lower"] == 1180
    assert data["items"][0]["subset"] == "text"


def test_steam_preserves_minor_units_and_does_not_invent_release_date():
    data = parsers.steam(encode({"new_releases": {"items": [{"id": 5, "name": "Game", "final_price": 499, "currency": "USD"}]}}))
    assert data["items"][0]["priceMinor"] == 499
    assert data["items"][0]["releasedAt"] is None


def test_auction_calendar_cannot_manufacture_lot_results():
    data = parsers.auctions(b'<script type="application/ld+json">{"@graph":[{"@type":"Event","url":"https://example.org/sale/1","name":"Sale","startDate":"2026-01-02"}]}</script>')
    assert data["items"][0]["eventTime"] == "2026-01-02"
    assert data["items"][0]["hammer"] is None
    assert data["items"][0]["estimateLow"] is None


def test_social_excludes_reposts_and_non_public_labels():
    rows = [
        {"post": {"uri": "one", "author": {"handle": "a", "labels": []}, "record": {"text": "Public"}, "likeCount": 0}},
        {"reason": {"$type": "repost"}, "post": {"uri": "two", "record": {"text": "Reposted"}}},
        {"post": {"uri": "three", "author": {"labels": [{"val": "!no-unauthenticated"}]}, "record": {"text": "Restricted"}}},
    ]
    result = parsers.social(encode({"feed": rows, "cursor": "more"}))
    assert [r["id"] for r in result["items"]] == ["one"]
    assert result["items"][0]["likes"] == 0
    assert result["hasMore"] is True


def test_box_office_reads_numeric_cells_preserving_unknown_comparator():
    cells = [('string', 'BFI Weekend Box Office 01/01/2026 - 03/01/2026', None)]
    def row(values):
        return '<t:table-row>' + ''.join(f'<t:table-cell o:value-type="{kind}"' + (f' o:value="{value}"' if value is not None else '') + f'><p>{title}</p></t:table-cell>' for kind, title, value in values) + '</t:table-row>'
    values = [('float','1','1'),('string','Film',None),('string','UK',None),('currency','£100','100'),('string','Studio',None),('string','-',None),('float','1','1'),('float','5','5'),('currency','£20','20'),('currency','£100','100')]
    xml = '<root xmlns:t="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:o="urn:oasis:names:tc:opendocument:xmlns:office:1.0">'+row(cells)+row(values)+'</root>'
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('content.xml', xml)
    result = parsers.box_office(stream.getvalue())
    assert result["territory"] == "UK"
    assert result["items"][0]["currency"] == "GBP"
    assert result["items"][0]["gross"] == 100
    assert result["items"][0]["change"] is None


def test_source_failure_preserves_business_clock_and_api_never_collects(tmp_path, monkeypatch):
    store = SnapshotStore(str(tmp_path / 'snapshots.sqlite3'))
    monkeypatch.setenv('POLYMONITOR_APPLE_MUSIC_CHART_URL','https://example.org/chart')
    monkeypatch.setenv('POLYMONITOR_EXTERNAL_EVIDENCE_SQLITE_PATH',str(tmp_path / 'evidence.sqlite3'))
    spec = SPECS['music']
    data = {'items': [{'id': 'song', 'title': 'Song'}]}
    collect_one(store, spec, acquire=lambda: (b'first', data), now=1000)
    def fail():
        raise TimeoutError('unavailable')
    collect_one(store, spec, acquire=fail, now=22000, force=True)
    monkeypatch.setattr('api.services.panel_evidence_store.time.time',lambda: 22000)
    result = get_snapshot(store,'culture-music-charts')
    assert result['items'] == data['items']
    assert result['status'] == 'degraded'
    assert result['sources'][0]['lastSuccessAt'].startswith('1970-01-01T00:16:40')


def test_invalid_nonfinite_arena_is_rejected():
    with pytest.raises(ValueError):
        parsers.arena(encode({'rows':[{'row':{'model_name':'bad','category':'overall','rating':'NaN'}}]}))


def test_research_rejects_future_publisher_errors_and_unrelated_fuzzy_matches():
    rows = [
        {'DOI':'a', 'title':['Artificial intelligence in surgery'], 'published':{'date-parts':[[2025,1,2]]}},
        {'DOI':'b', 'title':['Artificial intelligence in surgery'], 'published':{'date-parts':[[2121,1,2]]}},
        {'DOI':'c', 'title':['Spiritual intelligence'], 'published':{'date-parts':[[2025,1,2]]}},
    ]
    assert [r['id'] for r in parsers.research(encode({'message':{'items':rows}}))['items']] == ['a']


def test_speech_parser_reads_article_not_short_heading_grid():
    paragraph = 'The official speech discusses inflation and monetary policy. ' * 8
    raw = ('<div id="article"><div class="heading col-xs-12 col-sm-8 col-md-8"><p>A title</p></div>'
        '<div class="col-xs-12 col-sm-8 col-md-8"><p>'+paragraph+'</p></div></div>').encode()
    assert parsers.transcript(raw) == [paragraph.strip()]
