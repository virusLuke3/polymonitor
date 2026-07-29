from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from api.services.natural_hazards import service
from api.services.natural_hazards.providers import eonet, nws, usgs


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
