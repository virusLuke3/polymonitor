from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from api.services.natural_hazards import service, snapshots
from api.services.natural_hazards.providers import eonet, firms, nws, usgs


class FakeSnapshotStore:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], dict] = {}

    def get(self, namespace: str, key: str):
        return self.values.get((namespace, key))

    def get_stale(self, namespace: str, key: str):
        return self.values.get((namespace, key))

    def set(self, namespace: str, key: str, payload: dict, _ttl: int) -> None:
        self.values[(namespace, key)] = payload


class FakeLogger:
    def exception(self, *_args, **_kwargs) -> None:
        return None


class StaleOnlySnapshotStore(FakeSnapshotStore):
    def get(self, namespace: str, key: str):
        return None


def test_usgs_provider_uses_native_identity_and_evidence() -> None:
    payload = {
        "metadata": {"generated": 1_788_000_000_000},
        "features": [
            {
                "id": "us-test-1",
                "properties": {
                    "mag": 7.1,
                    "place": "Test trench",
                    "time": 1_788_000_000_000,
                    "updated": 1_788_000_060_000,
                    "url": "https://earthquake.usgs.gov/test",
                    "detail": "https://earthquake.usgs.gov/test.geojson",
                    "sig": 1100,
                    "alert": "red",
                    "tsunami": 1,
                    "status": "reviewed",
                },
                "geometry": {"type": "Point", "coordinates": [140.2, 35.1, 18.5]},
            }
        ],
    }
    result = usgs.fetch(lambda *_args, **_kwargs: payload)
    event = result["events"][0]
    assert event["id"] == "earthquake:usgs:us-test-1"
    assert event["severity"] == "critical"
    assert event["metrics"]["magnitude"] == 7.1
    assert event["metrics"]["tsunami"] is True
    assert event["revision"]["nativeEventId"] == "us-test-1"


def test_eonet_provider_preserves_observed_storm_track() -> None:
    payload = {
        "events": [
            {
                "id": "EONET_1",
                "title": "Tropical Cyclone Test",
                "description": "Pacific Ocean",
                "link": "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_1",
                "categories": [{"id": "severeStorms", "title": "Severe Storms"}],
                "sources": [{"id": "JTWC", "url": "https://example.test/storm"}],
                "geometry": [
                    {"date": "2026-07-28T00:00:00Z", "type": "Point", "coordinates": [140, 15]},
                    {
                        "date": "2026-07-29T00:00:00Z",
                        "type": "Point",
                        "coordinates": [142, 16],
                        "magnitudeValue": 80,
                        "magnitudeUnit": "kts",
                    },
                ],
            }
        ]
    }
    event = eonet.fetch(lambda *_args, **_kwargs: payload)["events"][0]
    assert event["hazardKind"] == "tropical-cyclone"
    assert event["geometry"]["type"] == "LineString"
    assert event["geometry"]["coordinates"] == [[140.0, 15.0], [142.0, 16.0]]
    assert event["metrics"]["maximumWind"] == {"value": 80.0, "unit": "kt"}
    assert event["severity"] == "warning"


def test_nws_provider_keeps_polygon_and_does_not_fabricate_missing_geometry() -> None:
    base_properties = {
        "id": "urn:test:flood",
        "event": "Flash Flood Warning",
        "headline": "Flash Flood Warning for Test County",
        "areaDesc": "Test County",
        "sent": "2026-07-29T10:00:00Z",
        "effective": "2026-07-29T10:00:00Z",
        "onset": "2026-07-29T10:00:00Z",
        "expires": "2026-07-29T12:00:00Z",
        "status": "Actual",
        "messageType": "Alert",
        "severity": "Severe",
        "certainty": "Likely",
        "urgency": "Immediate",
        "references": [],
    }
    payload = {
        "updated": "2026-07-29T10:00:00Z",
        "features": [
            {
                "id": "https://api.weather.gov/alerts/urn:test:flood",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-90, 35], [-89, 35], [-89, 36], [-90, 35]]],
                },
                "properties": base_properties,
            },
            {
                "id": "https://api.weather.gov/alerts/urn:test:heat",
                "geometry": None,
                "properties": {
                    **base_properties,
                    "id": "urn:test:heat",
                    "event": "Excessive Heat Warning",
                    "headline": "Excessive Heat Warning",
                },
            },
        ],
    }
    events = nws.fetch(lambda *_args, **_kwargs: payload)["events"]
    assert events[0]["hazardKind"] == "flood"
    assert events[0]["geometry"]["type"] == "Polygon"
    assert events[1]["hazardKind"] == "extreme-heat"
    assert events[1]["geometry"] is None
    assert events[1]["locationPrecision"] == "region"
    assert any("no point location was fabricated" in item for item in events[1]["limitations"])


def test_firms_provider_aggregates_pixels_without_upgrading_them_to_wildfires() -> None:
    csv_payload = "\n".join([
        "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight",
        "10.10,20.10,340,0.4,0.4,2026-07-29,0315,N20,VIIRS,h,2.0NRT,300,12.5,D",
        "10.20,20.20,345,0.4,0.4,2026-07-29,0320,N20,VIIRS,n,2.0NRT,301,17.5,D",
        "11.20,21.20,350,0.4,0.4,2026-07-29,0410,N20,VIIRS,l,2.0NRT,302,4.0,N",
    ])
    captured: dict[str, str] = {}

    def fake_text(url: str, **_kwargs) -> str:
        captured["url"] = url
        return csv_payload

    events = firms.fetch(fake_text, map_key="secret-key", source="VIIRS_NOAA20_NRT")["events"]
    assert len(events) == 2
    aggregate = next(event for event in events if event["metrics"]["detectionCount"] == 2)
    assert aggregate["hazardKind"] == "fire-detection"
    assert aggregate["properties"]["observationType"] == "satellite-thermal-anomaly"
    assert aggregate["metrics"]["fireRadiativePowerMw"] == 30.0
    assert aggregate["geometry"]["coordinates"] == [20.15, 10.15]
    assert aggregate["locationPrecision"] == "region"
    assert "secret-key" in captured["url"]
    assert all(event["hazardKind"] != "wildfire" for event in events)


def test_firms_provider_rejects_missing_map_key() -> None:
    try:
        firms.fetch(lambda *_args, **_kwargs: "", map_key="")
    except ValueError as exc:
        assert str(exc) == "firms-map-key-required"
    else:
        raise AssertionError("missing FIRMS MAP_KEY must fail closed")


def test_provider_snapshot_lock_prevents_same_process_cache_stampede() -> None:
    store = FakeSnapshotStore()
    calls: list[int] = []

    def fetcher():
        calls.append(1)
        time.sleep(0.03)
        return {"events": [], "data_updated_at": "2026-07-29T00:00:00Z"}

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(
            lambda _index: snapshots.fetch_with_snapshot(
                key="usgs",
                snapshot_store=store,
                fetcher=fetcher,
                ttl_seconds=60,
            ),
            range(5),
        ))
    assert len(calls) == 1
    assert {result["status"] for result in results} == {"ok"}


def test_provider_deadline_returns_partial_error_without_waiting_for_slow_source() -> None:
    store = FakeSnapshotStore()
    settings = SimpleNamespace(
        natural_hazards_usgs_url="usgs",
        natural_hazards_eonet_url="eonet",
        natural_hazards_nws_url="nws",
    )
    dependencies = service.NaturalHazardDependencies.from_context({
        "http_json_get": lambda *_args, **_kwargs: {},
        "SNAPSHOT_STORE": store,
        "SETTINGS": settings,
        "app": SimpleNamespace(logger=FakeLogger()),
    })

    def slow_fetcher():
        time.sleep(0.15)
        return {"events": [], "data_updated_at": None}

    started = time.monotonic()
    results = service._fetch_provider_results(
        dependencies=dependencies,
        source_specs={"nws": (60, slow_fetcher)},
        deadline_seconds=0.01,
    )
    assert time.monotonic() - started < 0.1
    assert results["nws"]["status"] == "error"
    assert results["nws"]["errorCode"] == "nws-provider-deadline-exceeded"


def test_provider_deadline_retains_last_successful_snapshot() -> None:
    store = StaleOnlySnapshotStore()
    store.values[(snapshots.SNAPSHOT_NAMESPACE, "nws")] = {
        "events": [{"id": "flood:nws:stale"}],
        "fetchedAt": "2026-07-29T00:00:00Z",
        "dataUpdatedAt": "2026-07-29T00:00:00Z",
        "staleAfter": "2026-07-29T00:01:00Z",
    }
    settings = SimpleNamespace(
        natural_hazards_usgs_url="usgs",
        natural_hazards_eonet_url="eonet",
        natural_hazards_nws_url="nws",
    )
    dependencies = service.NaturalHazardDependencies.from_context({
        "http_json_get": lambda *_args, **_kwargs: {},
        "SNAPSHOT_STORE": store,
        "SETTINGS": settings,
        "app": SimpleNamespace(logger=FakeLogger()),
    })
    results = service._fetch_provider_results(
        dependencies=dependencies,
        source_specs={"nws": (60, lambda: (time.sleep(0.15), {})[1])},
        deadline_seconds=0.01,
    )
    assert results["nws"]["status"] == "degraded"
    assert results["nws"]["events"] == [{"id": "flood:nws:stale"}]
    assert results["nws"]["lastSuccessAt"] == "2026-07-29T00:00:00Z"


def test_service_returns_partial_data_when_one_provider_fails(monkeypatch) -> None:
    store = FakeSnapshotStore()
    settings = SimpleNamespace(
        natural_hazards_usgs_url="usgs",
        natural_hazards_eonet_url="eonet",
        natural_hazards_nws_url="nws",
    )

    def fake_get(url: str, **_kwargs):
        if url == "usgs":
            return {"metadata": {"generated": 1_788_000_000_000}, "features": []}
        if url == "eonet":
            return {"events": []}
        raise TimeoutError("nws timeout")

    monkeypatch.delenv("POLYDATA_FIRMS_MAP_KEY", raising=False)
    context = {
        "http_json_get": fake_get,
        "SNAPSHOT_STORE": store,
        "SETTINGS": settings,
        "app": SimpleNamespace(logger=FakeLogger()),
    }
    payload = service.get_natural_hazards_snapshot(context)
    assert payload["schemaVersion"] == "natural-hazards.v1"
    assert payload["isPartial"] is True
    statuses = {source["key"]: source["status"] for source in payload["sources"]}
    assert statuses["usgs"] == "ok"
    assert statuses["eonet"] == "ok"
    assert statuses["nws"] == "error"
    assert statuses["firms"] == "degraded"
    assert statuses["climate-anomaly"] == "degraded"
