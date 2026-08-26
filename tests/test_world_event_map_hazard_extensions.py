from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone

import pytest

from api.services import global_transport_shipping_service as transport
from api.services.natural_hazards import dedupe, map_feed
from api.services.natural_hazards.providers import firms, ncei, nhc, nws, usgs_volcano_cap


def _kmz(kml: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("storm.kml", kml)
    return buffer.getvalue()


def _line_kmz() -> bytes:
    return _kmz("""
      <kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><LineString>
      <coordinates>-70,20,0 -69,21,0 -68,22,0</coordinates>
      </LineString></Placemark></kml>
    """)


def _cone_kmz() -> bytes:
    return _kmz("""
      <kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Polygon><outerBoundaryIs><LinearRing>
      <coordinates>-72,18,0 -66,18,0 -65,24,0 -73,24,0 -72,18,0</coordinates>
      </LinearRing></outerBoundaryIs></Polygon></Placemark></kml>
    """)


def _dateline_cone_kmz() -> bytes:
    return _kmz("""
      <kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Polygon><outerBoundaryIs><LinearRing>
      <coordinates>178,12,0 -178,12,0 -176,18,0 177,18,0 178,12,0</coordinates>
      </LinearRing></outerBoundaryIs></Polygon></Placemark></kml>
    """)


def test_nhc_preserves_observed_forecast_and_cone_geometry() -> None:
    payload = {"activeStorms": [{
        "id": "AL012026",
        "name": "Ada",
        "classification": "HU",
        "longitudeNumeric": -70,
        "latitudeNumeric": 20,
        "intensity": 100,
        "pressure": 960,
        "movementDir": 315,
        "movementSpeed": 12,
        "lastUpdate": "2026-08-25T12:00:00Z",
        "publicAdvisory": {"advNum": "12", "url": "https://www.nhc.noaa.gov/text/fixture.shtml"},
        "bestTrackGIS": {"kmzFile": "https://www.nhc.noaa.gov/gis/fixture-best.kmz"},
        "forecastTrack": {"kmzFile": "https://www.nhc.noaa.gov/gis/fixture-track.kmz"},
        "trackCone": {"kmzFile": "https://www.nhc.noaa.gov/gis/fixture-cone.kmz"},
    }]}

    result = nhc.fetch(
        lambda *_args, **_kwargs: payload,
        http_bytes_get=lambda url, **_kwargs: _cone_kmz() if "cone" in url else _line_kmz(),
    )
    event = result["events"][0]
    assert event["revision"]["advisoryId"] == "12"
    assert event["metrics"]["maximumWind"] == {"value": 100, "unit": "kt"}
    assert set(event["properties"]["geometries"]) == {
        "observedPosition", "observedTrack", "forecastTrack", "forecastCone",
    }
    compact = map_feed.compact_hazard_event(event, zoom=2)
    assert set(compact["properties"]["geometries"]) == set(event["properties"]["geometries"])
    assert "summary" in compact and "limitations" in compact
    assert "report" not in compact and "evidence" not in compact


def test_nhc_splits_forecast_cone_at_dateline() -> None:
    geometry = nhc._kmz_geometry(
        lambda *_args, **_kwargs: _dateline_cone_kmz(),
        "https://www.nhc.noaa.gov/gis/cone.kmz",
        "polygon",
    )
    assert geometry is not None
    assert geometry["type"] == "MultiPolygon"
    for polygon in geometry["coordinates"]:
        longitudes = [point[0] for point in polygon[0]]
        assert max(longitudes) - min(longitudes) <= 180


def test_ncei_anomaly_declares_reproducibility_contract() -> None:
    result = ncei.fetch(
        lambda *_args, **_kwargs: {
            "cell-1": {"coordinates": {"latitude": 45, "longitude": 10}, "anomaly": 3.25},
            "cell-below-threshold": {"coordinates": {"latitude": 0, "longitude": 0}, "anomaly": 0.5},
        },
        now=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    event = result["events"][0]
    metrics = event["metrics"]
    assert metrics["baselinePeriod"] == "1991-2020"
    assert metrics["unit"] == "°C"
    assert metrics["timeWindow"] == "202608"
    assert metrics["spatialResolution"] == "5-degree-grid"
    assert metrics["calculationVersion"]


def test_usgs_volcano_cap_is_official_and_coverage_bounded() -> None:
    result = usgs_volcano_cap.fetch(lambda *_args, **_kwargs: [{
        "volcano_name_appended": "Fixture Volcano",
        "vnum": "123456",
        "longitude": -155.2,
        "latitude": 19.4,
        "notice_identifier": "DOI-USGS-HVO-fixture",
        "sent_date_cap": "2026-08-25T12:00:00-08:00",
        "cap_expires": "2026-08-26T12:00:00-08:00",
        "alert_level": "WATCH",
        "color_code": "ORANGE",
        "is_elevated_cap": True,
        "obs_fullname": "Hawaiian Volcano Observatory",
        "synopsis": "Elevated activity.",
    }])
    event = result["events"][0]
    assert event["id"] == "volcano:usgs:123456"
    assert event["severity"] == "warning"
    assert event["coverage"]["scope"] == "provider-area"
    assert event["coverage"]["isComplete"] is False


def test_dedupe_merges_only_explicit_official_canonical_identity() -> None:
    base = {
        "id": "earthquake:eonet:one",
        "hazardKind": "earthquake",
        "updatedAt": "2026-08-25T12:00:00Z",
        "properties": {},
        "limitations": ["discovery"],
        "revision": {"nativeEventId": "one", "revisionAt": "2026-08-25T12:00:00Z"},
        "sources": [{
            "provider": "NASA EONET",
            "nativeId": "one",
            "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000fixture",
        }],
    }
    primary = {
        **base,
        "id": "earthquake:usgs:us7000fixture",
        "updatedAt": "2026-08-25T12:01:00Z",
        "sources": [{"provider": "USGS", "nativeId": "us7000fixture"}],
        "revision": {"nativeEventId": "us7000fixture", "revisionAt": "2026-08-25T12:01:00Z"},
    }
    merged = dedupe.latest_revision([base, primary])
    assert len(merged) == 1
    assert merged[0]["id"] == "earthquake:usgs:us7000fixture"
    assert len(merged[0]["sources"]) == 2
    assert "explicit USGS" in merged[0]["properties"]["mergeReason"]


def test_nws_cancel_reuses_explicit_cap_reference_identity() -> None:
    payload = {"updated": "2026-08-25T12:00:00Z", "features": [{
        "id": "new-id",
        "geometry": {"type": "Polygon", "coordinates": [[[-100, 30], [-99, 30], [-99, 31], [-100, 30]]]},
        "properties": {
            "id": "new-id",
            "event": "Tornado Warning",
            "messageType": "Cancel",
            "references": [{"identifier": "original-id"}],
            "sent": "2026-08-25T12:00:00Z",
            "effective": "2026-08-25T11:00:00Z",
            "expires": "2026-08-25T13:00:00Z",
            "severity": "Severe",
            "urgency": "Immediate",
            "certainty": "Observed",
            "affectedZones": [],
        },
    }]}
    result = nws.fetch(lambda *_args, **_kwargs: payload)
    event = result["events"][0]
    assert event["id"] == "tornado:nws:original-id"
    assert event["revision"]["cancelled"] is True
    assert event["lifecycle"] == "ended"


@pytest.mark.parametrize(
    ("message_type", "expires", "expected_lifecycle", "expected_cancelled"),
    [
        ("Alert", "2026-08-25T13:00:00Z", "active", False),
        ("Update", "2026-08-25T13:00:00Z", "active", False),
        ("Cancel", "2026-08-25T13:00:00Z", "ended", True),
        ("Alert", "2026-08-25T11:00:00Z", "ended", False),
    ],
)
def test_nws_alert_update_cancel_and_expired_lifecycle(
    message_type: str,
    expires: str,
    expected_lifecycle: str,
    expected_cancelled: bool,
) -> None:
    payload = {"updated": "2026-08-25T12:00:00Z", "features": [{
        "id": f"{message_type.lower()}-id",
        "geometry": {"type": "Polygon", "coordinates": [[[-100, 30], [-99, 30], [-99, 31], [-100, 30]]]},
        "properties": {
            "id": f"{message_type.lower()}-id",
            "event": "Tornado Warning",
            "messageType": message_type,
            "references": ([{"identifier": "original-id"}] if message_type != "Alert" else []),
            "sent": "2026-08-25T12:00:00Z",
            "effective": "2026-08-25T11:00:00Z",
            "expires": expires,
            "severity": "Severe",
            "urgency": "Immediate",
            "certainty": "Observed",
            "affectedZones": [],
        },
    }]}
    result = nws.fetch(
        lambda *_args, **_kwargs: payload,
        now=datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc),
    )
    event = result["events"][0]
    assert event["lifecycle"] == expected_lifecycle
    assert event["revision"]["cancelled"] is expected_cancelled
    assert event["properties"]["expired"] is (expires < "2026-08-25T12:00:00Z")


def test_firms_high_zoom_viewport_returns_real_unanimated_detection_objects() -> None:
    csv_payload = "latitude,longitude,acq_date,acq_time,frp,confidence,satellite,instrument\n34.1,-118.2,2026-08-25,1200,125,high,N20,VIIRS\n"
    result = firms.fetch_viewport(
        lambda *_args, **_kwargs: csv_payload,
        map_key="fixture",
        bbox=(-119, 33, -117, 35),
    )
    event = result["events"][0]
    assert event["geometry"]["coordinates"] == [-118.2, 34.1]
    assert event["properties"]["rawDetection"] is True
    assert event["metrics"]["detectionCount"] == 1


def test_aviation_viewport_uses_bbox_and_never_fabricates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport, "_opensky_access_token", lambda _ctx: ("fixture-token", {"status": "ok"}))
    captured = {}

    def fake_get(_ctx, _url, **kwargs):
        captured.update(kwargs["params"])
        return {"states": [["abc123", "TEST1", "US", None, 1, -73.9, 40.7, 10000, False, 230, 90, 0, None, 10000, None, False, 0]]}

    monkeypatch.setattr(transport, "_http_json_get", fake_get)
    context = transport.GlobalTransportShippingDependencies(
        application=None,
        utc_now_iso=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        http_text_get=None,
        http_json_get=None,
        http_form_post=None,
        get_cached_json=None,
        set_cached_json=None,
        snapshot_store=None,
        search_markets=None,
    )
    result = transport.get_aviation_viewport_snapshot(
        context,
        bbox=(-75, 39, -72, 42),
        zoom=5,
    )
    assert captured == {"lamin": 39, "lomin": -75, "lamax": 42, "lomax": -72}
    assert result["aircraftCount"] == 1
    assert result["aircraft"][0]["callsign"] == "TEST1"


def test_aviation_viewport_falls_back_to_real_adsb_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport, "_opensky_access_token", lambda _ctx: (None, {"status": "auth-error-cache"}))
    cache = {}
    calls = []

    def fake_get(_ctx, url, **_kwargs):
        calls.append(url)
        assert "api.adsb.lol/v2/point/" in url
        return {"ac": [
            {
                "hex": "a53207",
                "flight": "AAL1567 ",
                "lat": 40.7,
                "lon": -73.9,
                "alt_baro": 17900,
                "gs": 405.7,
                "track": 273.25,
                "baro_rate": 320,
                "emergency": "none",
            },
            {"hex": "outside", "flight": "DROP", "lat": 36.0, "lon": -80.0},
        ]}

    monkeypatch.setattr(transport, "_http_json_get", fake_get)
    context = transport.GlobalTransportShippingDependencies(
        application=None,
        utc_now_iso=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        http_text_get=None,
        http_json_get=None,
        http_form_post=None,
        get_cached_json=lambda namespace, key: cache.get((namespace, key)),
        set_cached_json=lambda namespace, key, value, _ttl: cache.__setitem__((namespace, key), value),
        snapshot_store=None,
        search_markets=None,
    )
    first = transport.get_aviation_viewport_snapshot(
        context,
        bbox=(-75, 39, -72, 42),
        zoom=5,
    )
    second = transport.get_aviation_viewport_snapshot(
        context,
        bbox=(-75, 39, -72, 42),
        zoom=5,
    )

    assert first["status"] == "ok"
    assert first["source"] == "ADSB.lol"
    assert first["fallbackFrom"]["reason"] == "auth-error-cache"
    assert first["coverage"] == {"mode": "covering-sector", "sectorCount": 1, "complete": True}
    assert first["aircraftCount"] == 1
    assert first["aircraft"][0]["callsign"] == "AAL1567"
    assert first["aircraft"][0]["source"] == "ADSB.lol"
    assert second["cacheMode"] == "cache"
    assert len(calls) == 1


def test_aviation_viewport_never_fabricates_when_live_providers_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport, "_opensky_access_token", lambda _ctx: (None, {"status": "auth-error"}))
    monkeypatch.setattr(transport, "_http_json_get", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()))
    context = transport.GlobalTransportShippingDependencies(
        application=None,
        utc_now_iso=lambda: "2026-08-25T12:00:00Z",
        http_text_get=None,
        http_json_get=None,
        http_form_post=None,
        get_cached_json=None,
        set_cached_json=None,
        snapshot_store=None,
        search_markets=None,
    )
    result = transport.get_aviation_viewport_snapshot(
        context,
        bbox=(-75, 39, -72, 42),
        zoom=5,
    )

    assert result["status"] == "unavailable"
    assert result["source"] == "ADSB.lol"
    assert result["aircraft"] == []
    assert result["aircraftCount"] == 0
