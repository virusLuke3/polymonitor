from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from api.context import RuntimeResources
from time import monotonic
from typing import Any, Dict
from urllib.parse import urlparse
from urllib3.util import Timeout

from ..contracts import ProviderResult
from ..normalize import compact_text, iso_timestamp
from ..severity import nws_severity


PROVIDER_KEY = "nws"
DEFAULT_URL = "https://api.weather.gov/alerts"
SOURCE_URL = "https://www.weather.gov/documentation/services-web-alerts"
ZONE_SNAPSHOT_NAMESPACE = "snapshot:world:nws-zones"
ZONE_CACHE_TTL_SECONDS = 6 * 60 * 60
# Optional zone enrichment must finish inside the compact feed's 6.5s
# provider deadline, including time already spent fetching the CAP catalog.
PROVIDER_FETCH_BUDGET_SECONDS = 5.5
MAX_ZONE_FETCHES_PER_REFRESH = 12
ZONE_FETCH_WORKERS = 6
MAX_RING_POINTS = 240



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


def _trusted_zone_url(value: Any) -> str | None:
    url = str(value or "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "api.weather.gov":
        return None
    if not parsed.path.startswith("/zones/"):
        return None
    return url


def _generalize_ring(raw: Any) -> list[list[float]] | None:
    if not isinstance(raw, list) or len(raw) < 4:
        return None
    points: list[list[float]] = []
    for coordinate in raw:
        if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
            return None
        try:
            lon = float(coordinate[0])
            lat = float(coordinate[1])
        except (TypeError, ValueError):
            return None
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return None
        points.append([lon, lat])
    if points[0] != points[-1]:
        points.append(points[0])
    if len(points) <= MAX_RING_POINTS:
        return points
    stride = max(1, (len(points) - 2) // (MAX_RING_POINTS - 2) + 1)
    generalized = points[:-1:stride]
    if generalized[-1] != points[-2]:
        generalized.append(points[-2])
    generalized.append(generalized[0])
    return generalized if len(generalized) >= 4 else None


def _generalized_geometry(raw: Any) -> Dict[str, Any] | None:
    geometry = _geometry(raw)
    if geometry is None:
        return None
    polygons = (
        [geometry["coordinates"]]
        if geometry["type"] == "Polygon"
        else geometry["coordinates"]
    )
    normalized: list[list[list[list[float]]]] = []
    for polygon in polygons:
        if not isinstance(polygon, list):
            continue
        rings = [_generalize_ring(ring) for ring in polygon]
        valid_rings = [ring for ring in rings if ring is not None]
        if valid_rings:
            normalized.append(valid_rings)
    if not normalized:
        return None
    if len(normalized) == 1:
        return {"type": "Polygon", "coordinates": normalized[0]}
    return {"type": "MultiPolygon", "coordinates": normalized}


def _zone_geometry(resources, http_json_get, url: str, deadline: float, snapshot_store=None) -> Dict[str, Any] | None:
    try:
        shared_lock = getattr(snapshot_store, "fetch_lock", None)
        with (shared_lock(ZONE_SNAPSHOT_NAMESPACE, url, timeout=max(0, min(.5, deadline - monotonic()))) if shared_lock else nullcontext()):
            geometry = snapshot_store.get(ZONE_SNAPSHOT_NAMESPACE, url) if snapshot_store else None
            if not geometry:
                remaining = deadline - monotonic()
                if remaining <= .1 or resources.stopped.is_set(): return None
                payload = http_json_get(url, timeout=Timeout(total=remaining, connect=min(2., remaining), read=min(3., remaining)),
                    headers={"Accept": "application/geo+json", "User-Agent": "polymonitor-world-event-map/1.0 (https://polymonitor.club)"})
                geometry = _generalized_geometry(payload.get("geometry") if isinstance(payload, dict) else None)
                if geometry is not None and snapshot_store:
                    snapshot_store.set(ZONE_SNAPSHOT_NAMESPACE, url, geometry, ZONE_CACHE_TTL_SECONDS)
            if geometry is not None:
                with resources.zone_cache_lock: resources.zone_cache[url] = (monotonic(), geometry)
            return geometry
    except TimeoutError:
        return None
    finally:
        with resources.zone_cache_lock: resources.zone_pending.pop(url, None)


def _resolve_zone_geometries(resources, http_json_get, zone_urls: list[str], *, deadline: float, snapshot_store=None) -> dict[str, Dict[str, Any]]:
    """Return cached geometry immediately. Optional enrichment never delays CAP.

    The process-wide pending table is singleflight AND a hard queue bound. A
    cancelled caller does not pretend a running blocking HTTP request stopped.
    """
    resolved: dict[str, Dict[str, Any]] = {}
    now = monotonic()
    with resources.zone_cache_lock:
        for url in dict.fromkeys(zone_urls):
            cached = resources.zone_cache.get(url)
            if cached and now - cached[0] <= ZONE_CACHE_TTL_SECONDS:
                if cached[1] is not None:
                    resolved[url] = cached[1]
                continue
            if url in resources.zone_pending or len(resources.zone_pending) >= MAX_ZONE_FETCHES_PER_REFRESH:
                continue
            if deadline - monotonic() <= 0.1 or resources.stopped.is_set():
                continue
            # Mark before submit, while holding the same lock used by completion.
            resources.zone_pending[url] = True
            try:
                resources.zone_pending[url] = resources.submit(resources.zone_executor, _zone_geometry,
                    resources, http_json_get, url, deadline, snapshot_store)
            except RuntimeError:
                resources.zone_pending.pop(url, None)
    return resolved


def enrich_cached_events(events: list[Dict[str, Any]], resources, *, now: datetime | None = None, snapshot_store=None) -> list[Dict[str, Any]]:
    """Merge completed official zones into the SAME CAP revision, no new times."""
    result = []
    shared_read_deadline = monotonic() + .25
    for event in events:
        properties = event.get("properties") or {}
        zones = properties.get("affectedZones") or []
        expires = iso_timestamp(event.get("expiresAt"))
        expired = bool(expires and datetime.fromisoformat(expires.replace("Z", "+00:00")) <= (now or datetime.now(timezone.utc)))
        if (event.get("revision") or {}).get("cancelled") or event.get("lifecycle") == "ended" or expired or not zones \
            or properties.get("geometrySource") == "nws-alert-polygon":
            result.append(event); continue
        geometries = []
        with resources.zone_cache_lock:
            for url in zones:
                cached = resources.zone_cache.get(url)
                if not cached and snapshot_store and monotonic() < shared_read_deadline:
                    geometry = snapshot_store.get(ZONE_SNAPSHOT_NAMESPACE, url)
                    if geometry:
                        cached = (monotonic(), geometry); resources.zone_cache[url] = cached
                if cached and monotonic() - cached[0] <= ZONE_CACHE_TTL_SECONDS and cached[1]:
                    geometries.append(cached[1])
        if len(geometries) <= int(properties.get("resolvedZoneCount") or 0):
            result.append(event); continue
        result.append({**event, "geometry": _merge_zone_geometries(geometries), "locationPrecision": "region",
            "properties": {**properties, "geometrySource": "nws-affected-zones", "resolvedZoneCount": len(geometries),
                "unresolvedZoneCount": max(0, len(zones) - len(geometries))}})
    return result


def _merge_zone_geometries(geometries: list[Dict[str, Any]]) -> Dict[str, Any] | None:
    polygons: list[list[list[list[float]]]] = []
    for geometry in geometries:
        if geometry.get("type") == "Polygon":
            polygons.append(geometry["coordinates"])
        elif geometry.get("type") == "MultiPolygon":
            polygons.extend(geometry["coordinates"])
    if not polygons:
        return None
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def _prioritized_zone_urls(features: list[Any]) -> list[str]:
    """Round-robin zones so every alert gets a renderable area before detail fills in."""
    zones_by_alert: list[list[str]] = []
    for feature in sorted(features, key=lambda f: -({"Extreme": 3, "Severe": 2, "Moderate": 1}.get(
        (f.get("properties") or {}).get("severity"), 0) if isinstance(f, dict) else 0)):
        if not isinstance(feature, dict) or _geometry(feature.get("geometry")) is not None:
            continue
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        raw_zones = properties.get("affectedZones") if isinstance(properties.get("affectedZones"), list) else []
        trusted = [zone for value in raw_zones if (zone := _trusted_zone_url(value)) is not None]
        if trusted:
            zones_by_alert.append(trusted)
    prioritized: list[str] = []
    for zone_index in range(max((len(zones) for zones in zones_by_alert), default=0)):
        for zones in zones_by_alert:
            if zone_index < len(zones):
                prioritized.append(zones[zone_index])
    return prioritized


def fetch(
    http_json_get,
    *,
    url: str = DEFAULT_URL,
    limit: int = 600,
    resources: RuntimeResources | None = None,
    previous_events: list[Dict[str, Any]] | None = None,
    snapshot_store=None,
    deadline: float | None = None,
    now: datetime | None = None,
) -> ProviderResult:
    deadline = deadline if deadline is not None else monotonic() + PROVIDER_FETCH_BUDGET_SECONDS
    if deadline - monotonic() <= .1:
        raise TimeoutError("nws-catalog-deadline-before-acquisition")
    resources = resources or RuntimeResources()
    observed_now = now or datetime.now(timezone.utc)
    payload = http_json_get(
        url,
        params={"status": "actual", "message_type": "alert,update,cancel"},
        timeout=Timeout(total=max(0.1, deadline - monotonic() - 0.25), connect=2.0, read=max(0.1, deadline - monotonic() - 0.25)),
        headers={
            "Accept": "application/geo+json",
            "User-Agent": "polymonitor-world-event-map/1.0 (https://polymonitor.club)",
        },
    )
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise ValueError("nws-schema-features")
    if features and not any(isinstance(item, dict) and isinstance(item.get("properties"), dict)
        and item["properties"].get("event") for item in features):
        raise ValueError("nws-schema-alerts")
    catalog_partial = bool((payload.get("pagination") or {}).get("next")) or len(features) > max(1, limit)
    bounded_features = features[: max(1, limit)]
    zone_urls = _prioritized_zone_urls(bounded_features)
    resolved_zones = _resolve_zone_geometries(resources, http_json_get, zone_urls, deadline=deadline, snapshot_store=snapshot_store)
    previous_by_id = {
        str(event.get("id")): event
        for event in (previous_events or [])
        if isinstance(event, dict) and event.get("id")
    }
    events: list[Dict[str, Any]] = []
    for feature in bounded_features:
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
        references = properties.get("references") if isinstance(properties.get("references"), list) else []
        referenced_ids = [
            str(reference.get("identifier") or reference.get("@id") or "").strip()
            for reference in references
            if isinstance(reference, dict)
            and str(reference.get("identifier") or reference.get("@id") or "").strip()
        ]
        # CAP Update/Cancel messages have a new identifier. The oldest explicit
        # reference is the stable advisory identity; retaining it makes the
        # latest-revision selector replace the alert instead of drawing a
        # duplicate. No spatial or title-based guess is used here.
        canonical_native_id = referenced_ids[-1] if referenced_ids else native_id
        effective_at = iso_timestamp(properties.get("effective"))
        onset_at = iso_timestamp(properties.get("onset"))
        updated_at = iso_timestamp(properties.get("sent"))
        expires_at = iso_timestamp(properties.get("expires"))
        ended_at = iso_timestamp(properties.get("ends"))
        expired = False
        if expires_at:
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                expired = expiry <= observed_now
            except ValueError:
                expired = False
        geometry = _generalized_geometry(feature.get("geometry"))
        affected_zones = [
            trusted
            for zone in (properties.get("affectedZones") or [])
            if (trusted := _trusted_zone_url(zone)) is not None
        ] if isinstance(properties.get("affectedZones"), list) else []
        resolved_zone_count = sum(1 for zone in affected_zones if zone in resolved_zones)
        if geometry is None and resolved_zone_count:
            geometry = _merge_zone_geometries([resolved_zones[zone] for zone in affected_zones if zone in resolved_zones])
        previous = (
            previous_by_id.get(f"{hazard_kind}:nws:{canonical_native_id}")
            or previous_by_id.get(f"{hazard_kind}:nws:{native_id}")
            or {}
        )
        previous_properties = previous.get("properties") if isinstance(previous.get("properties"), dict) else {}
        previous_zone_count = int(previous_properties.get("resolvedZoneCount") or 0)
        previous_geometry = _geometry(previous.get("geometry"))
        geometry_reused = False
        same_revision = (previous.get("revision") or {}).get("nativeEventId") == native_id
        same_zones = set(previous_properties.get("affectedZones") or []) == set(affected_zones)
        if (not cancelled and not expired and same_revision and same_zones
            and feature.get("geometry") is None and previous_geometry is not None
            and previous_zone_count > resolved_zone_count):
            geometry = previous_geometry
            resolved_zone_count = previous_zone_count
            geometry_reused = True
        severity, evidence = nws_severity(properties)
        area = compact_text(properties.get("areaDesc"), 220)
        limitations = [
            "NWS coverage is regional and does not imply global official alert coverage.",
            "Alert polygons and text may be revised, replaced or cancelled by subsequent CAP messages.",
        ]
        if catalog_partial:
            limitations.append("The alert catalog has further pages or exceeds the response limit; this is partial coverage.")
        if geometry is None:
            limitations.append("This alert has no resolved official zone geometry; no point location was fabricated.")
        elif resolved_zone_count:
            limitations.append(
                "Geometry was resolved from official NWS affected-zone boundaries and generalized for map rendering."
                if not geometry_reused
                else "The best previously resolved official NWS affected-zone geometry was retained during this bounded refresh."
            )
            if resolved_zone_count < len(affected_zones):
                limitations.append("Some referenced NWS zones were unavailable within the bounded refresh deadline.")
        events.append(
            {
                "id": f"{hazard_kind}:nws:{canonical_native_id}",
                "category": "weather",
                "title": compact_text(properties.get("headline"), 240) or event_name,
                "summary": compact_text(properties.get("description"), 700),
                "severity": severity,
                "occurredAt": onset_at or effective_at,
                "updatedAt": updated_at,
                "expiresAt": expires_at,
                "geometry": geometry,
                "locationPrecision": "region" if resolved_zone_count or geometry is None else "exact",
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
                    "affectedZones": affected_zones,
                    "geometrySource": "nws-affected-zones" if resolved_zone_count else "nws-alert-polygon" if geometry else None,
                    "resolvedZoneCount": resolved_zone_count,
                    "unresolvedZoneCount": max(0, len(affected_zones) - resolved_zone_count),
                    "geometryReusedFromSnapshot": geometry_reused,
                    "response": properties.get("response"),
                    "canonicalEventId": f"{hazard_kind}:nws:{canonical_native_id}",
                    "mergeReason": "CAP identifier/references revision chain",
                    "sourceProvenance": [{"provider": "NWS", "nativeEventId": native_id}],
                    "expired": expired,
                },
                "hazardKind": hazard_kind,
                "lifecycle": "ended" if cancelled or expired else "active",
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
                        reference_id
                        for reference_id in referenced_ids
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
    return {"events": events, "data_updated_at": iso_timestamp(payload.get("updated")), "is_partial": catalog_partial}
