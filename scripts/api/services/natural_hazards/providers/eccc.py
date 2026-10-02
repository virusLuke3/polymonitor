"""Canadian official alerts, native GeoMet geometry and validity (no centroids)."""
from datetime import datetime, timezone
from ..contracts import SEVERITY_MAPPING_VERSION
from ..normalize import compact_text, iso_timestamp
from ..source_health import SOURCE_COVERAGE

URL = "https://api.weather.gc.ca/collections/weather-alerts/items"


def fetch(http_json_get, *, now=None):
    now = now or datetime.now(timezone.utc)
    features = {}; partial = False
    for status in ("issued", "continued"):
        payload = http_json_get(URL, params={"f": "json", "limit": 1000, "status_en": status}, timeout=6)
        if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
            raise ValueError("eccc-schema-features")
        partial |= any(link.get("rel") == "next" for link in payload.get("links", []))
        for feature in payload["features"]:
            native = str(feature.get("id") or "")
            features[native] = feature
    events = []
    for feature in features.values():
        p = feature.get("properties") or {}
        native = str(feature.get("id") or "")
        updated = iso_timestamp(p.get("publication_datetime"))
        expires = iso_timestamp(p.get("expiration_datetime"))
        if not native or not updated or not expires:
            continue
        if datetime.fromisoformat(expires.replace("Z", "+00:00")) <= now:
            continue
        status = str(p.get("status_en") or "").lower()
        if status in {"ended", "cancelled", "canceled"}:
            continue
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            geometry = None  # retain the record without inventing a map location
        title = str(p.get("alert_name_en") or "Weather alert")
        title_lower = title.lower()
        kind = "tornado" if "tornado" in title_lower else "flood" if any(w in title_lower for w in ("flood", "surge")) else "extreme-heat" if "heat" in title_lower else "extreme-cold" if "cold" in title_lower else "severe-storm" if any(w in title_lower for w in ("storm", "wind", "snow", "blizzard")) else "weather-alert"
        raw = str(p.get("alert_type") or "statement")
        severity = "warning" if raw == "warning" else "watch" if raw == "watch" else "info"
        if str(p.get("risk_colour_en") or "").lower() == "red": severity = "critical"
        source_url = f"{URL}/{native}"
        events.append({"id": f"weather-alert:eccc:{native}", "category": "weather", "hazardKind": kind,
            "title": title, "summary": compact_text(p.get("alert_text_en"), 8000), "severity": severity,
            "occurredAt": iso_timestamp(p.get("validity_datetime")) or updated, "updatedAt": updated, "expiresAt": expires,
            "geometry": geometry, "locationPrecision": "region" if geometry else "unknown", "countryCode": "CA",
            "locationLabel": p.get("feature_name_en"), "relatedMarketIds": [],
            "sources": [{"provider": "ECCC", "url": source_url, "nativeId": native, "observedAt": updated, "freshness": "fresh", "status": "ok"}],
            "coverage": SOURCE_COVERAGE["eccc"], "lifecycle": "forecast" if datetime.fromisoformat((iso_timestamp(p.get("validity_datetime")) or updated).replace("Z", "+00:00")) > now else "active",
            "metrics": {"kind": "weather-alert", "providerSeverity": raw, "instruction": p.get("alert_text_en")},
            "revision": {"provider": "ECCC", "nativeEventId": native, "revisionAt": updated, "replaces": [], "cancelled": False},
            "severityEvidence": {"provider": "ECCC", "rawLevel": raw, "mappingVersion": SEVERITY_MAPPING_VERSION,
                "reason": f"ECCC {raw}; risk colour {p.get('risk_colour_en') or 'unspecified'}"},
            "limitations": ["Canadian official warning coverage only. Native alert regions are not impact forecasts."],
            "properties": {"mapEntity": "hazard-event", "geometrySource": "eccc-alert-polygon", "nativeStatus": status}})
    return {"events": events, "data_updated_at": max((e["updatedAt"] for e in events), default=None),
        "is_partial": partial}
