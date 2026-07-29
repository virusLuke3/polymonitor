from __future__ import annotations

from typing import Any, Dict

from .contracts import coverage


SOURCE_COVERAGE: dict[str, Dict[str, Any]] = {
    "usgs": coverage(
        scope="global",
        label="Global earthquakes reported by the USGS real-time feed",
        complete=False,
        gaps=["Small-event completeness varies by region and network coverage."],
    ),
    "eonet": coverage(
        scope="global",
        label="Global open natural-event discovery from NASA EONET",
        complete=False,
        gaps=["Discovery coverage is not equivalent to local official warnings."],
    ),
    "nws": coverage(
        scope="provider-area",
        label="United States and NWS responsibility areas",
        complete=False,
        gaps=["No official CAP coverage is implied outside NWS responsibility areas."],
    ),
    "firms": coverage(
        scope="global",
        label="NASA FIRMS satellite fire detections",
        complete=False,
        gaps=[
            "Thermal detections are not confirmed wildfire perimeters.",
            "Cloud, smoke, sensor coverage and overpass timing can create gaps.",
            "Global detections are spatially aggregated and display-capped.",
        ],
    ),
    "climate-anomaly": coverage(
        scope="global",
        label="Versioned quantitative climate anomaly pipeline",
        complete=False,
        gaps=["No quantitative baseline pipeline is configured; EONET temperature extremes and drought remain discovery events."],
    ),
}


def unavailable_source(key: str, error_code: str) -> Dict[str, Any]:
    return {
        "key": key,
        "status": "degraded",
        "coverage": SOURCE_COVERAGE[key],
        "fetchedAt": None,
        "dataUpdatedAt": None,
        "staleAfter": None,
        "lastSuccessAt": None,
        "errorCode": error_code,
    }
