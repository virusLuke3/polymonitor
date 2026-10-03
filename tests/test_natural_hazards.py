from __future__ import annotations

import time
from datetime import datetime, timezone
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace


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

    from api.context import RuntimeResources
    from datetime import datetime, timezone
    resources = RuntimeResources()
    try:
        first = nws.fetch(fake_get, resources=resources, now=datetime(2026, 8, 2, 11, tzinfo=timezone.utc))["events"]
        # CAP never waits for geometry. Completed enrichment is merged into the same revision.
        deadline = time.monotonic() + 1
        while resources.zone_pending and time.monotonic() < deadline:
            time.sleep(0.005)
        event = nws.enrich_cached_events(first, resources, now=datetime(2026, 8, 2, 11, tzinfo=timezone.utc))[0]
    finally:
        resources.close()
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


def test_nws_slow_catalog_keeps_alert_and_cached_geometry_without_extra_network(monkeypatch) -> None:
    from api.context import RuntimeResources

    clock = [100.0]
    monkeypatch.setattr(nws, "monotonic", lambda: clock[0])
    resources = RuntimeResources()
    cached_url = "https://api.weather.gov/zones/forecast/AAA001"
    uncached_url = "https://api.weather.gov/zones/forecast/AAA002"
    geometry = {"type": "Polygon", "coordinates": [[[-100, 35], [-99, 35], [-99, 36], [-100, 35]]]}
    resources.zone_cache[cached_url] = (100.0, geometry)
    calls = []

    def get_catalog(url, **_kwargs):
        calls.append(url)
        assert "/zones/" not in url
        clock[0] += nws.PROVIDER_FETCH_BUDGET_SECONDS + 0.1
        return {"updated": "2026-09-29T12:00:00Z", "features": [{
            "geometry": None,
            "properties": {"id": "budget-alert", "event": "Flood Warning",
                           "affectedZones": [cached_url, uncached_url]},
        }]}

    try:
        result = nws.fetch(get_catalog, resources=resources)
        assert len(calls) == 1
        assert result["data_updated_at"] == "2026-09-29T12:00:00Z"
        event = result["events"][0]
        assert event["geometry"] == geometry
        assert event["properties"]["resolvedZoneCount"] == 1
        assert event["properties"]["unresolvedZoneCount"] == 1
        assert any("unavailable" in text for text in event["limitations"])
    finally:
        resources.close()


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
        "revision": {"nativeEventId": "urn:test:heat-retained"},
        "properties": {"resolvedZoneCount": 2, "affectedZones": [
            "https://api.weather.gov/zones/forecast/ZZZ901", "https://api.weather.gov/zones/forecast/ZZZ902"]},
    }]

    def fake_get(url: str, **_kwargs):
        if "/zones/" in url:
            raise TimeoutError("bounded refresh")
        return alert_payload

    from datetime import datetime, timezone
    event = nws.fetch(fake_get, previous_events=previous_events, now=datetime(2026,8,2,11,tzinfo=timezone.utc))["events"][0]
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


def test_firms_provider_rejects_empty_public_csv() -> None:
    try:
        firms.fetch(lambda *_args, **_kwargs: "", map_key="")
    except ValueError as exc:
        assert str(exc) == "firms-schema-columns"
    else:
        raise AssertionError("invalid FIRMS public download must fail closed")


def test_provider_snapshot_lock_prevents_same_process_cache_stampede() -> None:
    store = FakeSnapshotStore()
    calls: list[int] = []

    def fetcher():
        calls.append(1)
        time.sleep(0.03)
        return {"events": [], "data_updated_at": "2026-07-29T00:00:00Z"}

    from threading import Lock
    source_lock = Lock()
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(
            lambda _index: snapshots.fetch_with_snapshot(
                key="usgs",
                source_lock=source_lock,
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
    assert nws.PROVIDER_FETCH_BUDGET_SECONDS < service.SOURCE_PROVIDER_DEADLINE_SECONDS


def test_provider_deadline_uses_snapshot_published_at_wait_boundary(monkeypatch) -> None:
    store = FakeSnapshotStore()
    dependencies = service.NaturalHazardDependencies.from_context({
        "http_json_get": lambda *_args, **_kwargs: {},
        "SNAPSHOT_STORE": store,
    })

    def publication_at_deadline(futures, **_kwargs):
        for future in futures:
            future.result(timeout=1)
        # Model the race between wait's pending classification and reading the
        # store. The actual completed fetch, not the timeout, wrote freshness.
        return set(), set(futures)

    monkeypatch.setattr(service, "wait", publication_at_deadline)
    try:
        result = service._fetch_provider_results(
            dependencies=dependencies,
            source_specs={"nws": (60, lambda: {
                "events": [{"id": "new-alert"}],
                "data_updated_at": "2026-09-29T12:00:00Z",
            })},
        )["nws"]
        assert result["status"] == "ok"
        assert result["events"] == [{"id": "new-alert"}]
        assert result["errorCode"] is None
        assert result["dataUpdatedAt"] == "2026-09-29T12:00:00Z"
    finally:
        dependencies.resources.close()


def test_provider_deadline_retains_last_successful_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(snapshots, "utc_now", lambda: datetime(2026, 7, 29, 0, 5, tzinfo=timezone.utc))
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
    assert statuses["climate-anomaly"] == "error"


def test_cached_service_mode_never_calls_live_providers(monkeypatch) -> None:
    monkeypatch.setattr(snapshots, "utc_now", lambda: datetime(2026, 7, 29, 0, 5, tzinfo=timezone.utc))
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


def test_map_feed_canonical_identity_survives_source_split_and_detail_fuses_evidence() -> None:
    store = FakeSnapshotStore()
    discovery = {
        "id": "earthquake:eonet:discovery",
        "category": "natural-hazard",
        "title": "Discovery earthquake",
        "severity": "warning",
        "updatedAt": "2026-08-16T00:02:00Z",
        "properties": {},
        "limitations": ["Discovery feed."],
        "revision": {"nativeEventId": "discovery", "revisionAt": "2026-08-16T00:02:00Z"},
        "sources": [{
            "provider": "NASA EONET",
            "nativeId": "discovery",
            "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000fixture",
        }],
        "hazardKind": "earthquake",
    }
    authoritative = {
        **discovery,
        "id": "earthquake:usgs:us7000fixture",
        "title": "USGS authoritative earthquake",
        "updatedAt": "2026-08-16T00:01:00Z",
        "limitations": ["USGS preliminary solution."],
        "revision": {"nativeEventId": "us7000fixture", "revisionAt": "2026-08-16T00:01:00Z"},
        "sources": [{"provider": "USGS", "nativeId": "us7000fixture"}],
    }
    for key, events in (("eonet", [discovery]), ("usgs", [authoritative])):
        store.values[(snapshots.SNAPSHOT_NAMESPACE, key)] = {
            "events": events,
            "fetchedAt": "2026-08-16T00:03:00Z",
            "dataUpdatedAt": "2026-08-16T00:02:00Z",
            "staleAfter": "2026-08-16T00:04:00Z",
        }

    compact = map_feed.compact_hazard_event(discovery)
    assert compact["id"] == "earthquake:usgs:us7000fixture"
    assert compact["properties"]["canonicalEventId"] == compact["id"]
    detail = map_feed.get_natural_hazard_event_detail(
        _map_feed_context(store),
        event_id="earthquake:usgs:us7000fixture",
    )
    assert detail is not None
    assert detail["event"]["title"] == "USGS authoritative earthquake"
    assert {source["provider"] for source in detail["event"]["sources"]} == {"USGS", "NASA EONET"}
    assert "explicit USGS" in detail["event"]["properties"]["mergeReason"]


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


def test_nws_active_alerts_does_not_send_unsupported_limit():
    def get(url, **kwargs):
        assert "limit" not in kwargs.get("params", {})
        return {"features": []}
    assert nws.fetch(get, limit=12)["events"] == []


def test_firms_public_download_is_shared_and_viewport_is_filtered():
    store = FakeSnapshotStore()
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return "latitude,longitude,acq_date,acq_time,frp\n10,20,2026-09-29,0910,12\n40,-100,2026-09-29,0920,5\n"
    global_result = firms.fetch(get, map_key="", snapshot_store=store, limit=1)
    local = firms.fetch_viewport(get, map_key="", bbox=(19,9,21,11), snapshot_store=store)
    assert calls == [firms.PUBLIC_NOAA20_URL]
    assert len(global_result["events"]) == 1
    assert global_result["data_updated_at"] == "2026-09-29T09:20:00Z"
    assert len(local["events"]) == 1
    assert local["events"][0]["geometry"]["coordinates"] == [20,10]
    assert local["data_updated_at"] == "2026-09-29T09:10:00Z"
    # A custom product must never silently receive the NOAA20 download.
    import pytest
    with pytest.raises(ValueError, match="required-for-product"):
        firms.fetch(get, map_key="", source="VIIRS_SNPP_NRT")


def test_v3_nws_catalog_is_independent_of_blocked_geometry_and_recovers_same_revision():
    from api.context import RuntimeResources
    from datetime import datetime, timezone
    from threading import Event
    release = Event(); started = Event(); resources = RuntimeResources()
    zone = 'https://api.weather.gov/zones/forecast/VVV001'
    geometry = {'type': 'Polygon', 'coordinates': [[[-100,35],[-99,35],[-99,36],[-100,35]]]}
    catalog = {'updated':'2026-10-01T01:00:00Z','features':[{'geometry':None,'properties':{
        'id':'cap-v3','sent':'2026-10-01T01:00:00Z','event':'Tornado Warning','severity':'Extreme',
        'expires':'2026-10-02T01:00:00Z','affectedZones':[zone]}}]}
    calls=[]
    def get(url, **kwargs):
        calls.append((url, kwargs['timeout']))
        if '/zones/' in url:
            started.set(); release.wait(1);return {'geometry':geometry}
        return catalog
    try:
        start=time.monotonic();first=nws.fetch(get,resources=resources,now=datetime(2026,10,1,2,tzinfo=timezone.utc))['events'];assert time.monotonic()-start < .1
        assert first[0]['geometry'] is None;assert started.wait(.5)
        for _ in range(10):nws.fetch(get,resources=resources)
        assert sum('/zones/' in url for url,_ in calls)==1
        release.set()
        deadline=time.monotonic()+1
        while resources.zone_pending and time.monotonic()<deadline:time.sleep(.005)
        enhanced=nws.enrich_cached_events(first,resources,now=datetime(2026,10,1,2,tzinfo=timezone.utc))[0]
        assert enhanced['geometry']==geometry
        assert enhanced['id']==first[0]['id'] and enhanced['updatedAt']==first[0]['updatedAt']
        revised={**catalog['features'][0], 'properties':{**catalog['features'][0]['properties'], 'id':'cap-v4','messageType':'Cancel',
            'references':[{'identifier':'cap-v3'}],'affectedZones':['https://api.weather.gov/zones/forecast/VVV002']}}
        cancelled=nws.fetch(lambda *_a,**_k:{'features':[revised]},resources=resources,previous_events=[enhanced])['events'][0]
        assert cancelled['revision']['cancelled'] and cancelled['geometry'] is None
        assert nws.enrich_cached_events([cancelled],resources)[0]['geometry'] is None
    finally:release.set();resources.close()


def test_v3_nws_zone_queue_and_http_budgets_are_bounded():
    from api.context import RuntimeResources
    from threading import Event
    release=Event(); resources=RuntimeResources(); calls=[]
    features=[{'properties':{'id':f'alert:{i}','event':'Tornado Warning','affectedZones':[f'https://api.weather.gov/zones/forecast/ZZ{i:04}']}} for i in range(640)]
    def get(url,**kwargs):
        calls.append(kwargs['timeout'])
        if '/zones/' in url:release.wait(.2);raise TimeoutError('controlled geometry fault')
        return {'features':features}
    try:
        for _ in range(3):
            result=nws.fetch(get,resources=resources)
            assert len(result['events'])==600
            assert len(resources.zone_pending)<=nws.MAX_ZONE_FETCHES_PER_REFRESH
        assert resources.zone_executor._max_workers==6
        assert all(t.total<=nws.PROVIDER_FETCH_BUDGET_SECONDS for t in calls)
    finally:release.set();resources.close()


def test_v3_hazard_cold_callers_share_one_future_and_failure_recovers():
    from api.context import RuntimeResources
    from threading import Event
    resources=RuntimeResources(); store=FakeSnapshotStore(); release=Event(); started=Event(); count=[]
    deps=service.NaturalHazardDependencies.from_context({'_resources':resources,'SNAPSHOT_STORE':store,'http_json_get':lambda *_a,**_k:None})
    def fetch():count.append(1);started.set();release.wait(1);return {'events':[], 'data_updated_at':'2026-10-01T00:00:00Z'}
    try:
        with ThreadPoolExecutor(max_workers=8) as callers:
            first=callers.submit(service._fetch_provider_results,dependencies=deps,source_specs={'nws':(60,fetch)},deadline_seconds=.5)
            assert started.wait(.5)
            rest=[callers.submit(service._fetch_provider_results,dependencies=deps,source_specs={'nws':(60,fetch)},deadline_seconds=.5) for _ in range(6)]
            time.sleep(.02);assert len(count)==1;release.set()
            assert all(f.result()['nws']['status']=='ok' for f in [first,*rest])
        assert len(count)==1
    finally:release.set();resources.close()


def test_v3_stale_snapshot_has_source_specific_age_and_keeps_success_time(monkeypatch):
    store = StaleOnlySnapshotStore()
    monkeypatch.setattr(snapshots, 'utc_now', lambda: datetime(2026, 10, 1, 1, tzinfo=timezone.utc))
    base = {'events': [{'id': 'alert'}], 'fetchedAt': '2026-10-01T00:50:00Z', 'dataUpdatedAt': '2026-09-30T23:00:00Z'}
    store.values[(snapshots.SNAPSHOT_NAMESPACE, 'nws')] = base
    retained = snapshots.stale_source_result(store, 'nws', 'controlled-timeout')
    assert retained['fetchedAt'] == base['fetchedAt']
    assert retained['dataUpdatedAt'] == base['dataUpdatedAt']
    store.values[(snapshots.SNAPSHOT_NAMESPACE, 'nws')] = {**base, 'fetchedAt': '2026-10-01T00:44:59Z'}
    assert snapshots.stale_source_result(store, 'nws', 'controlled-timeout') is None
    store.values[(snapshots.SNAPSHOT_NAMESPACE, 'nws')] = {**base, 'fetchedAt': None}
    assert snapshots.stale_source_result(store, 'nws', 'controlled-timeout') is None
    store.values[(snapshots.SNAPSHOT_NAMESPACE, 'climate-anomaly')] = {**base, 'fetchedAt': '2026-09-30T00:00:00Z'}
    assert snapshots.stale_source_result(store, 'climate-anomaly', 'controlled-timeout') is not None


def test_v3_schema_failure_retains_snapshot_but_valid_empty_replaces_it(monkeypatch):
    from threading import Lock
    store = StaleOnlySnapshotStore()
    monkeypatch.setattr(snapshots, 'utc_now', lambda: datetime(2026, 10, 1, 1, tzinfo=timezone.utc))
    store.values[(snapshots.SNAPSHOT_NAMESPACE, 'nws')] = {'events':[{'id':'old'}], 'fetchedAt':'2026-10-01T00:59:00Z'}
    def fetch(get):
        return snapshots.fetch_with_snapshot(key='nws', snapshot_store=store, source_lock=Lock(), fetcher=get, ttl_seconds=60)
    failed = fetch(lambda: {'events':None})
    assert failed['status']=='degraded' and failed['events']==[{'id':'old'}]
    assert failed['lastSuccessAt']=='2026-10-01T00:59:00Z'
    monkeypatch.setattr(snapshots, 'utc_now', lambda: datetime(2026,10,1,1,1,tzinfo=timezone.utc))
    empty = fetch(lambda: {'events':[],'data_updated_at':'2026-10-01T00:59:30Z'})
    assert empty['status']=='ok' and empty['events']==[]
    assert empty['dataUpdatedAt']=='2026-10-01T00:59:30Z'


def test_v3_nws_expired_queued_job_releases_singleflight_entry():
    from api.context import RuntimeResources
    resources = RuntimeResources(); url='https://api.weather.gov/zones/forecast/LATE001'
    resources.zone_pending[url] = True
    try:
        assert nws._zone_geometry(resources, lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('expired task cannot request')), url, time.monotonic()-1) is None
        assert url not in resources.zone_pending
    finally: resources.close()


def test_v3_provider_auth_and_retry_after_are_explicit_without_new_success_time(monkeypatch):
    from threading import Lock
    from requests import HTTPError, Response
    store=StaleOnlySnapshotStore()
    monkeypatch.setattr(snapshots, 'utc_now', lambda: datetime(2026,10,1,1,tzinfo=timezone.utc))
    store.values[(snapshots.SNAPSHOT_NAMESPACE,'nws')]={'events':[{'id':'old'}],'fetchedAt':'2026-10-01T00:59:00Z'}
    def result(status, retry):
        response=Response();response.status_code=status;response.headers['Retry-After']=retry
        def fail(): raise HTTPError('controlled upstream fault', response=response)
        return snapshots.fetch_with_snapshot(key='nws', snapshot_store=store, source_lock=Lock(), fetcher=fail, ttl_seconds=60)
    blocked=result(403,'60')
    assert blocked['condition']=='blocked' and blocked['errorCode']=='nws-http-403'
    assert blocked['fetchedAt']=='2026-10-01T00:59:00Z'
    monkeypatch.setattr(snapshots, 'utc_now', lambda: datetime(2026,10,1,1,6,tzinfo=timezone.utc))
    throttled=result(429,'120')
    assert throttled['condition']=='throttled' and throttled['retryAfterSeconds']==120
    assert throttled['lastSuccessAt']==blocked['lastSuccessAt']


def test_v3_provider_cooldown_expiry_reprobes_and_then_recovers(monkeypatch):
    from api.context import RuntimeResources
    from requests import HTTPError, Response
    resources=RuntimeResources();store=StaleOnlySnapshotStore();clock=[100.];calls=[]
    monkeypatch.setattr(snapshots,'utc_now',lambda:datetime.fromtimestamp(clock[0], timezone.utc))
    deps=service.NaturalHazardDependencies.from_context({'_resources':resources,'SNAPSHOT_STORE':store,'http_json_get':lambda *_a,**_k:None})
    failed=[True]
    def fetch():
        calls.append(1)
        if failed[0]:
            response=Response();response.status_code=429;response.headers['Retry-After']='10'
            raise HTTPError('controlled throttle',response=response)
        return {'events':[], 'data_updated_at':'2026-10-01T00:00:00Z'}
    run=lambda:service._fetch_provider_results(dependencies=deps,source_specs={'nws':(60,fetch)})['nws']
    try:
        assert run()['condition']=='throttled'
        for _ in range(20):assert run()['status']=='error'
        assert len(calls)==1
        clock[0]+=11;assert run()['condition']=='throttled';assert len(calls)==2
        for _ in range(10):run()
        assert len(calls)==2 # The second Retry-After replaces the expired deadline.
        failed[0]=False;clock[0]+=11;assert run()['status']=='ok'
        assert store.get_stale(snapshots.CONDITION_NAMESPACE,'nws')['retryAt'] == 0
    finally:resources.close()


def test_v3_cross_process_cold_source_and_failure_have_one_owner(tmp_path):
    import multiprocessing as mp
    from runtime.snapshot_store import SnapshotStore
    from threading import Lock
    ctx = mp.get_context("fork")
    path = str(tmp_path / "shared.sqlite3")
    SnapshotStore(path)._ensure_schema()
    for failing in (False, True):
        calls = ctx.Value("i", 0)
        start = ctx.Event()
        results = ctx.Queue()
        def worker():
            store = SnapshotStore(path)
            def acquire():
                with calls.get_lock(): calls.value += 1
                time.sleep(.2)
                if failing: raise ValueError("controlled source failure")
                return {"events": [{"id": "native-shared"}], "data_updated_at": "2026-10-01T00:00:00Z"}
            start.wait(3)
            results.put(snapshots.fetch_with_snapshot(key="nws" if failing else "usgs", snapshot_store=store,
                source_lock=Lock(), fetcher=acquire, ttl_seconds=60))
        processes = [ctx.Process(target=worker) for _ in range(4)]
        for process in processes: process.start()
        start.set()
        returned = [results.get(timeout=5) for _ in processes]
        for process in processes:
            process.join(2)
            assert process.exitcode == 0
        assert calls.value == 1
        assert all(result["status"] == ("error" if failing else "ok") for result in returned)
        if not failing: assert all(result["events"] == [{"id": "native-shared"}] for result in returned)


def test_v3_shared_fetch_lock_timeout_and_process_exit_release(tmp_path):
    import multiprocessing as mp
    import pytest
    from runtime.snapshot_store import SnapshotStore
    ctx = mp.get_context("fork"); ready = ctx.Event()
    path = str(tmp_path / "shared.sqlite3")
    def hold():
        with SnapshotStore(path).fetch_lock("source", "key"):
            ready.set(); time.sleep(5)
    process = ctx.Process(target=hold); process.start()
    try:
        assert ready.wait(2)
        with pytest.raises(TimeoutError):
            with SnapshotStore(path).fetch_lock("source", "key", timeout=.1): pass
        process.terminate(); process.join(2)
        with SnapshotStore(path).fetch_lock("source", "key", timeout=.1): pass
    finally:
        if process.is_alive(): process.terminate()
        process.join(2)


def test_v3_nws_geometry_shared_cache_is_available_to_another_worker(tmp_path):
    from api.context import RuntimeResources
    from runtime.snapshot_store import SnapshotStore
    store = SnapshotStore(str(tmp_path / 'shared.sqlite3'))
    zone = 'https://api.weather.gov/zones/forecast/VVV001'
    geometry = {'type':'Polygon','coordinates':[[[-100,35],[-99,35],[-99,36],[-100,35]]]}
    worker = RuntimeResources()
    event = {'id':'native-cap', 'updatedAt':'2026-10-01T00:00:00Z', 'geometry':None,
        'expiresAt':'2026-10-02T00:00:00Z', 'revision':{'revisionAt':'2026-10-01T00:00:00Z'},
        'properties':{'affectedZones':[zone]}}
    try:
        store.set(nws.ZONE_SNAPSHOT_NAMESPACE, zone, geometry, nws.ZONE_CACHE_TTL_SECONDS)
        enriched = nws.enrich_cached_events([event], worker, snapshot_store=store,
            now=datetime(2026,10,1,1,tzinfo=timezone.utc))[0]
        assert enriched['geometry'] == geometry
        assert enriched['id'] == event['id'] and enriched['updatedAt'] == event['updatedAt']
        cancelled={**event,'revision':{'cancelled':True}}
        assert nws.enrich_cached_events([cancelled],worker,snapshot_store=store)[0]['geometry'] is None
    finally:worker.close()


def test_nws_expired_absolute_deadline_does_not_start_new_http_work():
    calls = []
    try:
        nws.fetch(http_json_get=lambda *args, **kwargs: calls.append((args, kwargs)), deadline=time.monotonic()-.01)
    except TimeoutError as exc:
        assert str(exc) == 'nws-catalog-deadline-before-acquisition'
    else:
        raise AssertionError('Expired queued work must fail before acquisition')
    assert calls == []


def test_native_nws_polygons_do_not_report_missing_alternate_zone_boundaries():
    from api.context import RuntimeResources
    geometry = {'type': 'Polygon', 'coordinates': [[[-100,35],[-99,35],[-99,36],[-100,35]]]}
    zone = 'https://api.weather.gov/zones/forecast/TEST001'
    resources = RuntimeResources(); calls = []
    def get(url, **_kwargs):
        calls.append(url)
        return {'features': [{'geometry': geometry, 'properties': {
            'id': 'native-polygon', 'event': 'Flood Warning', 'affectedZones': [zone]}}]}
    try:
        event = nws.fetch(get, resources=resources)['events'][0]
        assert event['geometry'] == geometry
        assert event['properties']['unresolvedZoneCount'] == 0
        assert event['properties']['affectedZones'] == [zone]
        previous = {**event, 'properties': {**event['properties'], 'unresolvedZoneCount': 1}}
        assert nws.enrich_cached_events([previous], resources, http_json_get=get)[0]['properties']['unresolvedZoneCount'] == 0
        assert calls == [nws.DEFAULT_URL]
    finally: resources.close()


def test_cached_nws_catalog_progresses_past_failed_zones_without_refetching_cap(monkeypatch):
    from api.context import RuntimeResources
    resources = RuntimeResources(); store = FakeSnapshotStore(); calls = []
    total = nws.MAX_ZONE_FETCHES_PER_REFRESH + 2
    geometry = {'type': 'Polygon', 'coordinates': [[[-100,35],[-99,35],[-99,36],[-100,35]]]}
    features = [{'geometry': None, 'properties': {
        'id': f'alert-{i}', 'event': 'Flood Warning',
        'affectedZones': [f'https://api.weather.gov/zones/forecast/T{i:03}']}} for i in range(total)]
    blocked = {f'https://api.weather.gov/zones/forecast/T{i:03}' for i in range(total-2)}
    def get(url, **_kwargs):
        calls.append(url)
        if url == nws.DEFAULT_URL: return {'features': features}
        if url in blocked: raise TimeoutError('controlled zone outage')
        return {'geometry': geometry}
    def settled():
        deadline = time.monotonic() + 2
        while resources.zone_pending and time.monotonic() < deadline: time.sleep(.005)
        assert not resources.zone_pending
    try:
        events = nws.fetch(get, resources=resources, snapshot_store=store)['events']; settled()
        # No new CAP request: the cached read alone advances optional work.
        for _ in range(2):
            events = nws.enrich_cached_events(events, resources, snapshot_store=store, http_json_get=get); settled()
        events = nws.enrich_cached_events(events, resources, snapshot_store=store)
        assert all(event['geometry'] == geometry for event in events[-2:])
        assert all(calls.count(url) == 1 for url in blocked)
        assert calls.count(nws.DEFAULT_URL) == 1
        # End the negative-cache cooldown, resolve the original failure, and
        # retain canonical event IDs/revisions/times throughout recovery.
        blocked.clear()
        with resources.zone_cache_lock:
            for url, (stamp, value) in list(resources.zone_cache.items()):
                if value is None: resources.zone_cache[url] = (stamp-nws.ZONE_RETRY_SECONDS-1, None)
        nws.enrich_cached_events(events, resources, snapshot_store=store, http_json_get=get); settled()
        recovered = nws.enrich_cached_events(events, resources, snapshot_store=store)
        assert all(event['geometry'] == geometry and event['properties']['unresolvedZoneCount'] == 0 for event in recovered)
        assert [(e['id'],e['revision'],e['updatedAt']) for e in recovered] == [(e['id'],e['revision'],e['updatedAt']) for e in events]
    finally: resources.close()


def test_nws_optional_work_has_independent_budget_and_ignores_inactive_alerts():
    from api.context import RuntimeResources
    resources = RuntimeResources(); calls = []; now = datetime(2026,10,1,tzinfo=timezone.utc)
    features = [{'geometry': None, 'properties': {'id': str(i), 'event': 'Flood Warning',
        'messageType': 'Cancel' if i == 0 else 'Alert',
        'expires': '2026-09-01T00:00:00Z' if i == 1 else '2026-10-02T00:00:00Z',
        'affectedZones': [f'https://api.weather.gov/zones/forecast/T{i:03}']}} for i in range(3)]
    def get(url, **kwargs):
        if url == nws.DEFAULT_URL:
            time.sleep(.12); return {'features': features}
        calls.append((url, kwargs['timeout'].total)); return {'geometry': None}
    try:
        events = nws.fetch(get, resources=resources, deadline=time.monotonic()+.2, now=now)['events']
        deadline = time.monotonic()+1
        while resources.zone_pending and time.monotonic() < deadline: time.sleep(.005)
        assert len(events) == 3
        assert len(calls) == 1 and calls[0][0].endswith('T002')
        assert .5 < calls[0][1] <= nws.ZONE_FETCH_BUDGET_SECONDS
    finally: resources.close()


def test_refresh_ahead_serves_fresh_snapshot_while_one_shared_fetch_runs(monkeypatch):
    from api.context import RuntimeResources
    from threading import Event
    from datetime import timedelta
    resources = RuntimeResources(); store = FakeSnapshotStore()
    now = datetime(2026, 10, 3, tzinfo=timezone.utc)
    monkeypatch.setattr(snapshots, 'utc_now', lambda: now)
    original = {'events': [{'id': 'original'}], 'fetchedAt': snapshots.iso_utc(now-timedelta(seconds=40)),
                'staleAfter': snapshots.iso_utc(now+timedelta(seconds=20)), 'dataUpdatedAt': 'native-time'}
    store.values[(snapshots.SNAPSHOT_NAMESPACE, 'nws')] = original
    started = Event(); release = Event(); calls = []
    def fetch():
        calls.append(1); started.set(); release.wait(2)
        return {'events': [{'id': 'new'}], 'data_updated_at': 'new-native-time'}
    deps = service.NaturalHazardDependencies.from_context({'_resources': resources, 'SNAPSHOT_STORE': store, 'http_json_get': lambda *_a, **_k: None})
    try:
        for _ in range(5):
            result = service._fetch_provider_results(dependencies=deps, source_specs={'nws': (60, fetch)})['nws']
            assert result['status'] == 'ok'
            assert result['events'] == original['events']
            assert result['staleAfter'] == original['staleAfter']
            assert result['lastSuccessAt'] == original['fetchedAt']
        assert started.wait(1) and len(calls) == 1
        release.set(); resources.hazard_pending['nws'].result(2)
        current = service._fetch_provider_results(dependencies=deps, source_specs={'nws': (60, fetch)})['nws']
        assert current['events'] == [{'id': 'new'}]
        assert current['dataUpdatedAt'] == 'new-native-time'
        assert current['fetchedAt'] == snapshots.iso_utc(now)
        assert len(calls) == 1
    finally:
        release.set(); resources.close()


def test_refresh_ahead_preserves_provider_cooldown_and_original_deadlines(monkeypatch):
    from threading import Lock
    from datetime import timedelta
    now = datetime(2026, 10, 3, tzinfo=timezone.utc)
    monkeypatch.setattr(snapshots, 'utc_now', lambda: now)
    store = FakeSnapshotStore()
    original = {'events': [], 'fetchedAt': snapshots.iso_utc(now-timedelta(seconds=40)),
                'staleAfter': snapshots.iso_utc(now+timedelta(seconds=20))}
    store.values[(snapshots.SNAPSHOT_NAMESPACE, 'nws')] = original
    store.values[(snapshots.CONDITION_NAMESPACE, 'nws')] = {'retryAt': now.timestamp()+120, 'errorCode': 'nws-http-429', 'condition': 'throttled'}
    def forbidden(): raise AssertionError('retry-after must govern upstream requests')
    result = snapshots.fetch_with_snapshot(key='nws', snapshot_store=store, source_lock=Lock(), fetcher=forbidden, ttl_seconds=60, refresh_ahead=True)
    assert result['condition'] == 'throttled' and result['retryAfterSeconds'] == 120
    assert result['lastSuccessAt'] == original['fetchedAt']
    assert result['staleAfter'] == original['staleAfter']
    assert not snapshots.source_refresh_due({'staleAfter': snapshots.iso_utc(now+timedelta(seconds=25))}, 60)
    assert snapshots.source_refresh_due(original, 60)
    assert not snapshots.source_refresh_due({'staleAfter': 'invalid'}, 60)
