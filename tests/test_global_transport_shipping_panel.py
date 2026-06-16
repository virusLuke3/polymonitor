from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from api.runtime_panels import get_panel_by_id
from api.services import global_transport_shipping_service
from runtime.snapshot_store import SnapshotStore


AIRPORTS = """1,"Alpha Hub","Alpha City","United States","AAA","KAAA",40.0,-74.0,10,-5,A,America/New_York,airport,OurAirports
2,"Bravo Field","Bravo City","France","BBB","LBBB",48.0,2.0,20,1,E,Europe/Paris,airport,OurAirports
3,"Cargo Port","Cargo City","Japan","CCC","RJCC",35.0,139.0,30,9,U,Asia/Tokyo,airport,OurAirports
"""

AIRLINES = """10,"Fixture Air",\\N,"FX","FXA","Fixture","United States","Y"
11,"Transit Jet",\\N,"TJ","TJA","Transit","France","Y"
"""

ROUTES = """FX,10,AAA,1,BBB,2,,0,320
FX,10,AAA,1,CCC,3,,0,777
TJ,11,BBB,2,AAA,1,,0,320
TJ,11,CCC,3,AAA,1,,0,787
"""

TRANSITLAND = {
    "feeds": [
        {
            "id": "f-us-alpha",
            "spec": "gtfs",
            "urls": {"static_current": "https://example.test/alpha.zip"},
            "operators": [{"onestop_id": "o-alpha", "name": "Alpha Transit"}],
        },
        {
            "id": "f-fr-bravo",
            "spec": "gtfs",
            "authorization": {"type": "api_key"},
            "operators": [{"onestop_id": "o-bravo", "name": "Bravo Metro"}],
        },
    ]
}


def _write_openflights_fixture(root: Path) -> None:
    data = root / "data"
    data.mkdir(parents=True)
    (data / "airports.dat").write_text(AIRPORTS, encoding="utf-8")
    (data / "airlines.dat").write_text(AIRLINES, encoding="utf-8")
    (data / "routes.dat").write_text(ROUTES, encoding="utf-8")


def test_build_global_transport_shipping_payload_from_structured_sources(tmp_path, monkeypatch):
    openflights_root = tmp_path / "openflights"
    _write_openflights_fixture(openflights_root)
    monkeypatch.setenv("POLYDATA_OPENFLIGHTS_ROOT", str(openflights_root))
    monkeypatch.setenv("POLYDATA_TRANSITLAND_ATLAS_URL", "https://example.test/transitland.dmfr.json")
    monkeypatch.delenv("POLYDATA_TRANSITLAND_ATLAS_URLS", raising=False)
    monkeypatch.delenv("POLYDATA_AISSTREAM_API_KEY", raising=False)

    def http_text_get(url: str, **_: object) -> str:
        assert url == "https://example.test/transitland.dmfr.json"
        return json.dumps(TRANSITLAND)

    payload = global_transport_shipping_service.build_global_transport_shipping_payload(
        {
            "http_text_get": http_text_get,
            "utc_now_iso": lambda: "2026-06-16T01:00:00Z",
            "search_markets": lambda query, limit=3: [{"id": "pm-1", "slug": "transport-disruption", "question": query}],
        },
        limit=8,
    )

    assert payload["panelId"] == "global-transport-shipping"
    assert payload["status"] == "ok"
    assert payload["summary"]["airports"] == 3
    assert payload["summary"]["routes"] == 4
    assert payload["summary"]["transitFeeds"] == 2
    assert payload["summary"]["transitCatalogFiles"] == 1
    assert payload["summary"]["transitScannedFiles"] == 1
    assert payload["summary"]["aisStatus"] == "missing-key"
    assert any(item["evidenceType"] == "OPENFLIGHTS" and item["entity"] == "AAA" for item in payload["items"])
    assert any(item["evidenceType"] == "TRANSITLAND" and item["metric"] == 2 for item in payload["items"])
    assert any(item["evidenceType"] == "AISSTREAM" and item["severity"] == "watch" for item in payload["items"])
    assert payload["items"][0]["relatedPolymarketMarketIds"]


def test_get_global_transport_shipping_snapshot_returns_seed_miss_without_live_build(tmp_path):
    store = SnapshotStore(str(tmp_path / "snapshots.sqlite3"))
    payload = global_transport_shipping_service.get_global_transport_shipping_snapshot(
        {
            "SNAPSHOT_STORE": store,
            "utc_now_iso": lambda: "2026-06-16T01:00:00Z",
        },
        allow_live_build=False,
    )

    assert payload["status"] == "warming"
    assert payload["cacheMode"] == "seed-miss"
    assert payload["items"] == []


def test_transitland_catalog_defaults_to_index_sampling(monkeypatch):
    monkeypatch.delenv("POLYDATA_TRANSITLAND_ATLAS_URL", raising=False)
    monkeypatch.delenv("POLYDATA_TRANSITLAND_ATLAS_URLS", raising=False)
    monkeypatch.setenv("POLYDATA_TRANSITLAND_ATLAS_FILE_LIMIT", "2")
    index = [
        {"name": "a.dmfr.json", "download_url": "https://raw.test/a.dmfr.json"},
        {"name": "b.dmfr.json", "download_url": "https://raw.test/b.dmfr.json"},
        {"name": "c.dmfr.json", "download_url": "https://raw.test/c.dmfr.json"},
    ]
    payloads = {
        "https://raw.test/a.dmfr.json": {"feeds": [{"id": "f-us-a", "spec": "gtfs", "operators": [{"onestop_id": "o-a", "name": "A"}]}]},
        "https://raw.test/c.dmfr.json": {"feeds": [{"id": "f-fr-c", "spec": "gtfs-rt", "operators": [{"onestop_id": "o-c", "name": "C"}]}]},
    }

    def http_text_get(url: str, **_: object) -> str:
        if "api.github.com" in url:
            return json.dumps(index)
        return json.dumps(payloads[url])

    stats, source_url = global_transport_shipping_service._fetch_transitland_catalog({"http_text_get": http_text_get})

    assert source_url.endswith("/contents/feeds")
    assert stats["catalogFileCount"] == 3
    assert stats["scannedFileCount"] == 2
    assert stats["feedCount"] == 2
    assert stats["specCounts"] == {"gtfs": 1, "gtfs-rt": 1}


def test_global_transport_shipping_runtime_panel_registered():
    panel = get_panel_by_id("global-transport-shipping")

    assert panel is not None
    assert panel.route == "/runtime/transport/global-shipping"
