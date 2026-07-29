from __future__ import annotations

from typing import Any, Dict

from ..contracts import ProviderResult
from ..normalize import compact_text, iso_timestamp
from ..severity import nws_severity


PROVIDER_KEY = "nws"
DEFAULT_URL = "https://api.weather.gov/alerts/active"
SOURCE_URL = "https://www.weather.gov/documentation/services-web-alerts"


def _hazard_kind(event_name: str) -> str | None:
    lowered = event_name.lower()
    if "tornado" in lowered:
        return "tornado"
    if any(term in lowered for term in ("hurricane", "tropical storm", "typhoon", "cyclone")):
        return "tropical-cyclone"
    if "tsunami" in lowered:
        return "tsunami"
    if "volcano" in lowered:
        return "volcano"
    if "flood" in lowered:
        return "flood"
    if any(term in lowered for term in ("excessive heat", "heat advisory", "extreme heat")):
        return "extreme-heat"
    if any(term in lowered for term in ("extreme cold", "wind chill", "freeze", "frost")):
        return "extreme-cold"
    if any(term in lowered for term in ("storm", "blizzard", "snow", "squall", "high wind", "dust storm")):
        return "severe-storm"
    return None


def _geometry(raw: Any) -> Dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    geometry_type = str(raw.get("type") or "")
    coordinates = raw.get("coordinates")
    if geometry_type not in {"Polygon", "MultiPolygon"} or not isinstance(coordinates, list):
        return None
    return {"type": geometry_type, "coordinates": coordinates}


def fetch(http_json_get, *, url: str = DEFAULT_URL, limit: int = 600) -> ProviderResult:
    payload = http_json_get(
        url,
        params={"status": "actual", "message_type": "alert,update"},
        timeout=20,
        headers={
            "Accept": "application/geo+json",
            "User-Agent": "polymonitor-world-event-map/1.0 (https://polymonitor.club)",
        },
    )
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise ValueError("nws-schema-features")
    events: list[Dict[str, Any]] = []
    for feature in features[: max(1, limit)]:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        native_id = str(properties.get("id") or feature.get("id") or "").strip()
        event_name = compact_text(properties.get("event"), 160) or ""
        hazard_kind = _hazard_kind(event_name)
        if not native_id or hazard_kind is None:
            continue
        message_type = str(properties.get("messageType") or "Alert")
        cancelled = message_type.lower() == "cancel"
        effective_at = iso_timestamp(properties.get("effective"))
        onset_at = iso_timestamp(properties.get("onset"))
        updated_at = iso_timestamp(properties.get("sent"))
        expires_at = iso_timestamp(properties.get("expires"))
        ended_at = iso_timestamp(properties.get("ends"))
        geometry = _geometry(feature.get("geometry"))
        severity, evidence = nws_severity(properties)
        area = compact_text(properties.get("areaDesc"), 220)
        limitations = [
            "NWS coverage is regional and does not imply global official alert coverage.",
            "Alert polygons and text may be revised, replaced or cancelled by subsequent CAP messages.",
        ]
        if geometry is None:
            limitations.append("This alert has no polygon geometry; no point location was fabricated.")
        references = properties.get("references") if isinstance(properties.get("references"), list) else []
        events.append(
            {
                "id": f"{hazard_kind}:nws:{native_id}",
                "category": "weather",
                "title": compact_text(properties.get("headline"), 240) or event_name,
                "summary": compact_text(properties.get("description"), 700),
                "severity": severity,
                "occurredAt": onset_at or effective_at,
                "updatedAt": updated_at,
                "expiresAt": expires_at,
                "geometry": geometry,
                "locationPrecision": "region" if geometry is None else "exact",
                "locationLabel": area,
                "sources": [
                    {
                        "provider": "NWS",
                        "url": str(properties.get("@id") or feature.get("id") or SOURCE_URL),
                        "nativeId": native_id,
                        "observedAt": updated_at,
                        "freshness": "live",
                        "status": "ok",
                    }
                ],
                "limitations": limitations,
                "relatedMarketIds": [],
                "properties": {
                    "mapEntity": "hazard-event",
                    "senderName": properties.get("senderName"),
                    "affectedZones": properties.get("affectedZones") or [],
                    "response": properties.get("response"),
                },
                "hazardKind": hazard_kind,
                "lifecycle": "ended" if cancelled else "active",
                "effectiveAt": effective_at,
                "onsetAt": onset_at,
                "endedAt": ended_at,
                "coverage": {
                    "scope": "provider-area",
                    "label": "United States and NWS responsibility areas",
                    "isComplete": False,
                    "gaps": ["No official CAP coverage is implied outside NWS responsibility areas."],
                },
                "severityEvidence": evidence,
                "revision": {
                    "nativeEventId": native_id,
                    "advisoryId": native_id,
                    "revisionAt": updated_at,
                    "replaces": [
                        str(reference.get("identifier") or reference.get("@id") or "")
                        for reference in references
                        if isinstance(reference, dict)
                    ],
                    "cancelled": cancelled,
                },
                "metrics": {
                    "kind": "weather-alert",
                    "urgency": properties.get("urgency"),
                    "certainty": properties.get("certainty"),
                    "providerSeverity": properties.get("severity"),
                    "instruction": compact_text(properties.get("instruction"), 700),
                },
            }
        )
    return {"events": events, "data_updated_at": iso_timestamp(payload.get("updated"))}
