from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from api.services.natural_hazards.market_linker import (
    LINKER_VERSION,
    link_weather_markets,
    related_weather_markets_snapshot,
)


def hazard(
    *,
    hazard_kind: str = "extreme-heat",
    geometry: dict | None = None,
    metrics: dict | None = None,
) -> dict:
    return {
        "id": f"{hazard_kind}:fixture:1",
        "hazardKind": hazard_kind,
        "effectiveAt": "2026-07-29T10:00:00Z",
        "expiresAt": "2026-07-30T10:00:00Z",
        "geometry": geometry or {"type": "Point", "coordinates": [-96.8, 32.78]},
        "metrics": metrics or {
            "kind": "weather-alert",
            "providerSeverity": "Extreme",
        },
    }


def market(
    *,
    family: str = "highest_temperature",
    title: str = "Highest temperature in Dallas on 2026-07-30?",
) -> dict:
    return {
        "eventSlug": "highest-temperature-in-dallas-on-2026-07-30",
        "eventTitle": title,
        "eventStatus": "live",
        "marketFamily": family,
        "metricType": family,
        "marketUrl": "https://polymarket.com/event/test",
        "updatedAt": "2026-07-29T11:00:00Z",
        "topBin": {
            "marketId": 42,
            "label": "100-101 F",
            "midPriceYes": 0.45,
            "bestBidYes": 0.44,
            "bestAskYes": 0.47,
            "bookStatus": "ok",
            "priceSource": "clob-book",
        },
    }


def weather_payload(*markets: dict, lon: float = -96.797, lat: float = 32.7767) -> dict:
    return {
        "items": [{
            "cityId": "dallas",
            "city": "Dallas",
            "country": "US",
            "lon": lon,
            "lat": lat,
            "markets": list(markets),
        }]
    }


def test_extreme_temperature_market_is_contextual_without_comparable_threshold() -> None:
    payload = link_weather_markets(hazard(), weather_payload(market()))
    assert payload["linkerVersion"] == LINKER_VERSION
    assert payload["counts"] == {
        "candidates": 1,
        "matched": 1,
        "returned": 1,
        "rejected": 0,
    }
    linked = payload["markets"][0]
    assert linked["relationship"] == "contextual"
    assert linked["matchReasons"]["type"]["passed"] is True
    assert linked["matchReasons"]["space"]["level"] == "direct"
    assert linked["matchReasons"]["time"]["passed"] is True
    assert linked["matchReasons"]["metric"]["level"] == "contextual"
    assert linked["quote"]["spread"] == 0.03


def test_title_or_city_similarity_cannot_link_an_earthquake_to_temperature() -> None:
    payload = link_weather_markets(
        hazard(
            hazard_kind="earthquake",
            metrics={"kind": "earthquake", "magnitude": 7.0},
        ),
        weather_payload(market(title="Dallas earthquake and temperature on 2026-07-30")),
    )
    assert payload["markets"] == []
    assert payload["counts"]["rejected"] == 1


def test_flood_to_precipitation_is_contextual_not_direct() -> None:
    payload = link_weather_markets(
        hazard(
            hazard_kind="flood",
            geometry={
                "type": "Polygon",
                "coordinates": [[
                    [-97.0, 32.5],
                    [-96.5, 32.5],
                    [-96.5, 33.0],
                    [-97.0, 33.0],
                    [-97.0, 32.5],
                ]],
            },
        ),
        weather_payload(market(family="precipitation")),
    )
    assert payload["markets"][0]["relationship"] == "contextual"
    assert "does not directly measure flood" in payload["markets"][0]["matchReasons"]["metric"]["reason"]


def test_non_overlapping_market_date_is_rejected() -> None:
    payload = link_weather_markets(
        hazard(),
        weather_payload(market(title="Highest temperature in Dallas on 2026-08-15?")),
    )
    assert payload["markets"] == []


def test_far_away_city_is_rejected_even_when_type_and_time_match() -> None:
    payload = link_weather_markets(
        hazard(),
        weather_payload(market(), lon=139.65, lat=35.67),
    )
    assert payload["markets"] == []


def test_temperature_anomaly_direction_must_match_market_metric() -> None:
    payload = link_weather_markets(
        hazard(
            hazard_kind="temperature-anomaly",
            metrics={
                "kind": "climate-anomaly",
                "variable": "temperature",
                "value": 12,
                "anomaly": -5,
                "unit": "C",
                "baselinePeriod": "1991-2020",
                "calculationVersion": "fixture-v1",
            },
        ),
        weather_payload(market(family="highest_temperature")),
    )
    assert payload["markets"] == []


def test_event_lookup_fails_closed() -> None:
    payload = related_weather_markets_snapshot(
        event_id="missing",
        natural_hazards_payload={"events": [hazard()]},
        weather_map_payload=weather_payload(market()),
    )
    assert payload is None
