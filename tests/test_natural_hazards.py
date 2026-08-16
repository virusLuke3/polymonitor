from __future__ import annotations

import sys
import time
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from api.services.natural_hazards import map_feed, service, snapshots
from api.services.natural_hazards.providers import eonet, firms, gdacs, nws, usgs


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


def test_eonet_provider_does_not_turn_wildfire_observations_into_a_track() -> None:
    payload = {
        "events": [{
            "id": "EONET_FIRE_1",
            "title": "Named Fire",
            "categories": [{"id": "wildfires", "title": "Wildfires"}],
            "sources": [{"id": "source", "url": "https://example.test/fire"}],
            "geometry": [
                {"date": "2026-07-28T00:00:00Z", "type": "Point", "coordinates": [10, 20]},
                {"date": "2026-07-29T00:00:00Z", "type": "Point", "coordinates": [11, 21]},
            ],
        }],
    }
    event = eonet.fetch(lambda *_args, **_kwargs: payload)["events"][0]
    assert event["hazardKind"] == "wildfire"
    assert event["geometry"] == {"type": "Point", "coordinates": [11.0, 21.0]}


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


def test_nws_provider_resolves_official_affected_zone_geometry() -> None:
    alert_payload = {
        "updated": "2026-08-02T10:00:00Z",
        "features": [{
            "id": "https://api.weather.gov/alerts/urn:test:heat-zone",
            "geometry": None,
            "properties": {
                "id": "urn:test:heat-zone",
                "event": "Excessive Heat Warning",
                "headline": "Excessive Heat Warning",
                "areaDesc": "Test Forecast Zone",
                "sent": "2026-08-02T10:00:00Z",
                "effective": "2026-08-02T10:00:00Z",
                "expires": "2026-08-03T00:00:00Z",
                "status": "Actual",
                "messageType": "Alert",
                "severity": "Severe",
                "certainty": "Likely",
                "urgency": "Expected",
                "affectedZones": ["https://api.weather.gov/zones/forecast/ZZZ001"],
                "references": [],
            },
        }],
    }
    zone_payload = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-100, 35], [-99, 35], [-99, 36], [-100, 35]]],
        },
    }

    def fake_get(url: str, **_kwargs):
        return zone_payload if "/zones/" in url else alert_payload

    event = nws.fetch(fake_get)["events"][0]
    assert event["geometry"]["type"] == "Polygon"
    assert event["locationPrecision"] == "region"
    assert event["properties"]["geometrySource"] == "nws-affected-zones"
    assert event["properties"]["resolvedZoneCount"] == 1
    assert event["properties"]["unresolvedZoneCount"] == 0


def test_nws_zone_queue_prioritizes_one_official_zone_per_alert() -> None:
    features = [
        {
            "geometry": None,
            "properties": {"affectedZones": [
                "https://api.weather.gov/zones/forecast/AAA001",
                "https://api.weather.gov/zones/forecast/AAA002",
                "https://api.weather.gov/zones/forecast/AAA003",
            ]},
        },
        {
            "geometry": None,
            "properties": {"affectedZones": [
                "https://api.weather.gov/zones/forecast/BBB001",
                "https://api.weather.gov/zones/forecast/BBB002",
            ]},
        },
    ]
    assert nws._prioritized_zone_urls(features) == [
        "https://api.weather.gov/zones/forecast/AAA001",
        "https://api.weather.gov/zones/forecast/BBB001",
        "https://api.weather.gov/zones/forecast/AAA002",
        "https://api.weather.gov/zones/forecast/BBB002",
        "https://api.weather.gov/zones/forecast/AAA003",
    ]


def test_nws_provider_rejects_untrusted_zone_urls() -> None:
    calls: list[str] = []
    payload = {
        "updated": "2026-08-02T10:00:00Z",
        "features": [{
            "geometry": None,
            "properties": {
                "id": "urn:test:flood-untrusted",
                "event": "Flood Warning",
                "sent": "2026-08-02T10:00:00Z",
                "effective": "2026-08-02T10:00:00Z",
                "expires": "2026-08-03T00:00:00Z",
                "severity": "Severe",
                "affectedZones": ["https://example.test/internal"],
                "references": [],
            },
        }],
    }

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        return payload

    event = nws.fetch(fake_get)["events"][0]
    assert calls == [nws.DEFAULT_URL]
    assert event["geometry"] is None
    assert event["properties"]["affectedZones"] == []


def test_nws_provider_keeps_best_previous_official_zone_geometry() -> None:
    alert_payload = {
        "updated": "2026-08-02T10:00:00Z",
        "features": [{
            "geometry": None,
            "properties": {
                "id": "urn:test:heat-retained",
                "event": "Excessive Heat Warning",
                "sent": "2026-08-02T10:00:00Z",
                "effective": "2026-08-02T10:00:00Z",
                "expires": "2026-08-03T00:00:00Z",
                "severity": "Severe",
                "affectedZones": [
                    "https://api.weather.gov/zones/forecast/ZZZ901",
                    "https://api.weather.gov/zones/forecast/ZZZ902",
                ],
                "references": [],
            },
        }],
    }
    previous_geometry = {
        "type": "Polygon",
        "coordinates": [[[-100, 35], [-99, 35], [-99, 36], [-100, 35]]],
    }
    previous_events = [{
        "id": "extreme-heat:nws:urn:test:heat-retained",
        "geometry": previous_geometry,
        "properties": {"resolvedZoneCount": 2},
    }]

    def fake_get(url: str, **_kwargs):
        if "/zones/" in url:
            raise TimeoutError("bounded refresh")
        return alert_payload

    event = nws.fetch(fake_get, previous_events=previous_events)["events"][0]
    assert event["geometry"] == previous_geometry
    assert event["properties"]["resolvedZoneCount"] == 2
    assert event["properties"]["unresolvedZoneCount"] == 0
    assert event["properties"]["geometryReusedFromSnapshot"] is True


def test_gdacs_provider_adds_only_actionable_global_disasters() -> None:
    payload = {
        "features": [
            {
                "geometry": {"type": "Point", "coordinates": [120.5, 18.2]},
                "properties": {
                    "eventtype": "TC",
                    "eventid": 1001,
                    "episodeid": 2,
                    "alertlevel": "Red",
                    "name": "Typhoon Test",
                    "description": "Tropical cyclone alert",
                    "fromdate": "2026-08-01T00:00:00Z",
                    "todate": "2026-08-02T00:00:00Z",
                    "country": "Philippines",
                    "url": {"report": "https://www.gdacs.org/report.aspx?eventid=1001"},
                    "severitydata": {"severitytext": "Maximum wind 120 kt"},
                },
            },
            {
                "geometry": {"type": "Point", "coordinates": [30, 5]},
                "properties": {
                    "eventtype": "DR",
                    "eventid": 1002,
                    "alertlevel": "Orange",
                    "name": "Drought Test",
                    "fromdate": "2026-07-20T00:00:00Z",
                },
            },
            {
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {"eventtype": "FL", "eventid": 1003, "alertlevel": "Green"},
            },
            {
                "geometry": {"type": "Point", "coordinates": [1, 1]},
                "properties": {"eventtype": "EQ", "eventid": 1004, "alertlevel": "Red"},
            },
        ]
    }
    events = gdacs.fetch(lambda *_args, **_kwargs: payload)["events"]
    assert [event["hazardKind"] for event in events] == ["tropical-cyclone", "other-weather-anomaly"]
    assert events[0]["severity"] == "critical"
    assert events[1]["severity"] == "warning"
    assert all(event["sources"][0]["provider"] == "GDACS" for event in events)


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


def test_default_provider_deadline_fits_inside_browser_request_budget() -> None:
    assert service.PROVIDER_DEADLINE_SECONDS < 25
    assert service.SOURCE_PROVIDER_DEADLINE_SECONDS < 10


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


def test_cached_service_mode_never_calls_live_providers(monkeypatch) -> None:
    store = StaleOnlySnapshotStore()
    store.values[(snapshots.SNAPSHOT_NAMESPACE, "usgs")] = {
        "events": [{"id": "earthquake:usgs:cached", "hazardKind": "earthquake"}],
        "fetchedAt": "2026-07-29T00:00:00Z",
        "dataUpdatedAt": "2026-07-29T00:00:00Z",
        "staleAfter": "2026-07-29T00:01:00Z",
    }
    settings = SimpleNamespace(
        natural_hazards_usgs_url="usgs",
        natural_hazards_eonet_url="eonet",
        natural_hazards_nws_url="nws",
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("cached mode must not call a live provider")

    monkeypatch.delenv("POLYDATA_FIRMS_MAP_KEY", raising=False)
    payload = service.get_natural_hazards_snapshot(
        {
            "http_json_get": fail_if_called,
            "SNAPSHOT_STORE": store,
            "SETTINGS": settings,
            "app": SimpleNamespace(logger=FakeLogger()),
        },
        allow_provider_fetch=False,
    )

    assert payload["events"] == [{"id": "earthquake:usgs:cached", "hazardKind": "earthquake"}]
    statuses = {source["key"]: source["status"] for source in payload["sources"]}
    assert statuses["usgs"] == "degraded"
    assert statuses["eonet"] == "error"
    assert statuses["nws"] == "error"


def _map_feed_context(store: FakeSnapshotStore):
    return {
        "http_json_get": lambda *_args, **_kwargs: {},
        "SNAPSHOT_STORE": store,
        "SETTINGS": SimpleNamespace(
            natural_hazards_usgs_url="usgs",
            natural_hazards_eonet_url="eonet",
            natural_hazards_gdacs_url="gdacs",
            natural_hazards_nws_url="nws",
        ),
        "app": SimpleNamespace(logger=FakeLogger()),
    }


def test_map_feed_is_source_scoped_compact_and_keeps_detail_out_of_first_paint() -> None:
    store = FakeSnapshotStore()
    coordinates = [[-125 + index * 0.01, 35 + (index % 7) * 0.01] for index in range(1400)]
    coordinates.append(coordinates[0])
    full_event = {
        "id": "flood:nws:large-polygon",
        "category": "weather",
        "title": "Large flood warning",
        "summary": "S" * 2000,
        "severity": "warning",
        "occurredAt": "2026-08-16T00:00:00Z",
        "updatedAt": "2026-08-16T00:01:00Z",
        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
        "locationPrecision": "region",
        "locationLabel": "Test region",
        "confidence": 0.9,
        "sources": [{
            "provider": "NWS",
            "nativeId": "large-polygon",
            "url": "https://example.test/full-source-link",
            "freshness": "fresh",
            "status": "ok",
        }],
        "limitations": ["L" * 1200],
        "relatedMarketIds": [1, 2, 3],
        "properties": {
            "geometrySource": "nws-alert",
            "instruction": "I" * 4000,
            "affectedZones": [f"zone-{index}" for index in range(1000)],
        },
        "hazardKind": "flood",
        "lifecycle": "active",
        "coverage": {
            "scope": "provider-area",
            "label": "NWS responsibility areas",
            "isComplete": False,
            "gaps": ["Outside coverage"],
        },
        "severityEvidence": {
            "provider": "NWS",
            "rawLevel": "Severe",
            "mappingVersion": "hazard-severity.v1",
            "reason": "R" * 1000,
        },
        "revision": {"nativeEventId": "large-polygon", "revisionAt": "2026-08-16T00:01:00Z"},
        "metrics": {
            "kind": "weather-alert",
            "urgency": "Immediate",
            "certainty": "Likely",
            "providerSeverity": "Severe",
            "instruction": "I" * 4000,
        },
    }
    store.values[(snapshots.SNAPSHOT_NAMESPACE, "nws")] = {
        "events": [full_event],
        "fetchedAt": "2026-08-16T00:02:00Z",
        "dataUpdatedAt": "2026-08-16T00:01:00Z",
        "staleAfter": "2026-08-16T00:03:00Z",
    }

    payload = map_feed.get_natural_hazard_map_snapshot(
        _map_feed_context(store),
        source="nws",
        zoom=2,
    )
    compact = payload["events"][0]
    assert payload["schemaVersion"] == "natural-hazards-map.v1"
    assert payload["meta"]["geometryZoom"] == 2
    assert [source["key"] for source in payload["sources"]] == ["nws"]
    assert len(compact["geometry"]["coordinates"][0]) <= 65
    assert compact["geometry"]["coordinates"][0][0] == compact["geometry"]["coordinates"][0][-1]
    assert compact["properties"] == {
        "geometrySource": "nws-alert",
        "detailAvailable": True,
        "geometryMode": "simplified",
        "geometryZoom": 2,
    }
    assert compact["relatedMarketIds"] == []
    assert compact["sources"][0].get("url") is None
    assert len(json.dumps(compact)) < len(json.dumps(full_event)) * 0.2

    detailed_payload = map_feed.get_natural_hazard_map_snapshot(
        _map_feed_context(store),
        source="nws",
        zoom=6,
    )
    assert detailed_payload["meta"]["geometryZoom"] == 6
    assert len(detailed_payload["events"][0]["geometry"]["coordinates"][0]) > len(
        compact["geometry"]["coordinates"][0]
    )

    detail = map_feed.get_natural_hazard_event_detail(
        _map_feed_context(store),
        event_id=full_event["id"],
    )
    assert detail is not None
    assert detail["schemaVersion"] == "natural-hazard-detail.v1"
    assert detail["event"]["metrics"]["instruction"] == "I" * 4000
    assert detail["event"]["sources"][0]["url"] == "https://example.test/full-source-link"


def test_map_feed_rejects_unknown_source() -> None:
    try:
        map_feed.get_natural_hazard_map_snapshot(
            _map_feed_context(FakeSnapshotStore()),
            source="invented",
        )
    except ValueError as exc:
        assert str(exc) == "unsupported-natural-hazard-source"
    else:  # pragma: no cover - explicit contract failure branch
        raise AssertionError("unknown provider must be rejected")


def test_map_feed_bounds_large_multipolygon_by_zoom() -> None:
    polygons = []
    for polygon_index in range(240):
        x = float(polygon_index % 24)
        y = float(polygon_index // 24)
        ring = [
            [x, y],
            [x + 0.4, y],
            [x + 0.4, y + 0.4],
            [x, y + 0.4],
            [x, y],
        ]
        polygons.append([ring])

    global_geometry = map_feed.simplify_geometry(
        {"type": "MultiPolygon", "coordinates": polygons},
        zoom=2,
    )
    detail_geometry = map_feed.simplify_geometry(
        {"type": "MultiPolygon", "coordinates": polygons},
        zoom=6,
    )

    assert global_geometry is not None
    assert detail_geometry is not None
    assert len(global_geometry["coordinates"]) <= 8
    assert sum(len(ring) for polygon in global_geometry["coordinates"] for ring in polygon) <= 256
    assert len(detail_geometry["coordinates"]) > len(global_geometry["coordinates"])


def test_map_feed_fetches_only_the_requested_provider_on_cache_miss() -> None:
    calls: list[str] = []

    def get_json(url: str, **_kwargs):
        calls.append(url)
        return {
            "metadata": {"generated": 1_788_000_000_000},
            "features": [{
                "id": "source-scoped",
                "properties": {
                    "mag": 5.4,
                    "place": "Scoped trench",
                    "time": 1_788_000_000_000,
                    "updated": 1_788_000_060_000,
                    "url": "https://earthquake.usgs.gov/scoped",
                    "detail": "https://earthquake.usgs.gov/scoped.geojson",
                    "sig": 500,
                    "status": "reviewed",
                },
                "geometry": {"type": "Point", "coordinates": [140.2, 35.1, 18.5]},
            }],
        }

    store = FakeSnapshotStore()
    context = _map_feed_context(store)
    context["http_json_get"] = get_json

    payload = map_feed.get_natural_hazard_map_snapshot(context, source="usgs")

    assert payload["counts"]["events"] == 1
    assert len(calls) == 1
    assert calls == ["usgs"]
    assert (snapshots.SNAPSHOT_NAMESPACE, "usgs") in store.values
    assert (snapshots.SNAPSHOT_NAMESPACE, "eonet") not in store.values
