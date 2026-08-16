from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from math import ceil
from typing import Any, Iterable, Mapping

from .contracts import SCHEMA_VERSION
from .service import NaturalHazardDependencies, get_natural_hazard_source_result
from .snapshots import cached_source_result
from .source_health import SOURCE_COVERAGE


MAP_SCHEMA_VERSION = "natural-hazards-map.v1"
DETAIL_SCHEMA_VERSION = "natural-hazard-detail.v1"
MAP_SOURCE_KEYS = ("usgs", "eonet", "gdacs", "nws", "firms", "climate-anomaly")

_RENDER_PROPERTY_KEYS = {
    "observationType",
    "geometrySource",
    "resolvedZoneCount",
    "unresolvedZoneCount",
    "forecast",
    "observed",
    "status",
}

_METRIC_KEYS_BY_KIND = {
    "earthquake": {"magnitude", "depthKm", "significance", "pagerAlert", "tsunami"},
    "tropical-cyclone": {"maximumWind", "pressureHpa", "categoryLabel", "advisoryNumber"},
    "weather-alert": {"urgency", "certainty", "providerSeverity"},
    "wildfire": {"detectionCount", "fireRadiativePowerMw", "sensor", "satellite", "confidenceLabel"},
    "climate-anomaly": {"variable", "value", "anomaly", "unit", "baselinePeriod", "calculationVersion"},
    "volcano-or-other": {"statusLabel"},
}


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    if not rendered:
        return None
    return rendered if len(rendered) <= limit else f"{rendered[: max(0, limit - 1)].rstrip()}…"


def _point(value: Any, precision: int) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        lon = round(float(value[0]), precision)
        lat = round(float(value[1]), precision)
    except (TypeError, ValueError):
        return None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return [lon, lat]


def _dedupe_points(points: Iterable[list[float]]) -> list[list[float]]:
    deduped: list[list[float]] = []
    for point in points:
        if not deduped or point != deduped[-1]:
            deduped.append(point)
    return deduped


def _simplify_line(coordinates: Any, *, max_points: int, precision: int) -> list[list[float]]:
    if not isinstance(coordinates, list):
        return []
    valid = [point for item in coordinates if (point := _point(item, precision)) is not None]
    if len(valid) <= max_points:
        return _dedupe_points(valid)
    stride = max(1, ceil((len(valid) - 1) / max(1, max_points - 1)))
    sampled = valid[::stride]
    if sampled[-1] != valid[-1]:
        sampled.append(valid[-1])
    return _dedupe_points(sampled)


def _simplify_ring(coordinates: Any, *, max_points: int, precision: int) -> list[list[float]]:
    line = _simplify_line(coordinates, max_points=max_points, precision=precision)
    if len(line) < 3:
        return []
    if line[0] != line[-1]:
        line.append(line[0])
    return line if len(line) >= 4 else []


def simplify_geometry(geometry: Any, *, zoom: float = 2.0) -> dict[str, Any] | None:
    """Return a bounded map geometry without mutating the evidence record.

    Global feeds intentionally trade sub-kilometre polygon detail for a small,
    valid shape. The complete source geometry remains available from the detail
    endpoint after selection.
    """

    if not isinstance(geometry, Mapping):
        return None
    kind = str(geometry.get("type") or "")
    coordinates = geometry.get("coordinates")
    if zoom < 3:
        precision, line_budget, ring_budget, hole_budget = 2, 96, 96, 0
    elif zoom < 5:
        precision, line_budget, ring_budget, hole_budget = 3, 256, 256, 1
    else:
        precision, line_budget, ring_budget, hole_budget = 4, 640, 640, 3

    if kind == "Point":
        point = _point(coordinates, precision)
        return {"type": kind, "coordinates": point} if point else None
    if kind == "LineString":
        line = _simplify_line(coordinates, max_points=line_budget, precision=precision)
        return {"type": kind, "coordinates": line} if len(line) >= 2 else None
    if kind == "Polygon" and isinstance(coordinates, list):
        rings = [
            ring
            for item in coordinates[: 1 + hole_budget]
            if (ring := _simplify_ring(item, max_points=ring_budget, precision=precision))
        ]
        return {"type": kind, "coordinates": rings} if rings else None
    if kind == "MultiPolygon" and isinstance(coordinates, list):
        polygons: list[list[list[list[float]]]] = []
        for polygon in coordinates:
            if not isinstance(polygon, list):
                continue
            rings = [
                ring
                for item in polygon[: 1 + hole_budget]
                if (ring := _simplify_ring(item, max_points=ring_budget, precision=precision))
            ]
            if rings:
                polygons.append(rings)
        return {"type": kind, "coordinates": polygons} if polygons else None
    return None


def compact_hazard_event(event: Mapping[str, Any], *, zoom: float = 2.0) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in (
        "id",
        "category",
        "title",
        "severity",
        "occurredAt",
        "updatedAt",
        "expiresAt",
        "locationPrecision",
        "countryCode",
        "regionCode",
        "locationLabel",
        "confidence",
        "hazardKind",
        "lifecycle",
        "effectiveAt",
        "onsetAt",
        "endedAt",
    ):
        value = event.get(key)
        if value is not None:
            compact[key] = value

    summary = _text(event.get("summary"), 240)
    if summary:
        compact["summary"] = summary
    compact["geometry"] = simplify_geometry(event.get("geometry"), zoom=zoom)
    compact["coverage"] = deepcopy(event.get("coverage") or {
        "scope": "provider-area",
        "label": "Provider coverage was not declared.",
        "isComplete": False,
        "gaps": ["Coverage metadata unavailable."],
    })

    evidence = event.get("severityEvidence") if isinstance(event.get("severityEvidence"), Mapping) else {}
    compact["severityEvidence"] = {
        "provider": str(evidence.get("provider") or "unknown"),
        "mappingVersion": str(evidence.get("mappingVersion") or "unknown"),
        "reason": _text(evidence.get("reason"), 180) or "See the full disaster report.",
    }
    if evidence.get("rawLevel") is not None:
        compact["severityEvidence"]["rawLevel"] = _text(evidence.get("rawLevel"), 80)

    revision = event.get("revision") if isinstance(event.get("revision"), Mapping) else {}
    compact["revision"] = {
        key: deepcopy(value)
        for key in ("nativeEventId", "advisoryId", "revisionAt", "replaces", "cancelled")
        if (value := revision.get(key)) is not None
    }
    metrics = event.get("metrics") if isinstance(event.get("metrics"), Mapping) else {}
    metric_kind = str(metrics.get("kind") or "volcano-or-other")
    compact["metrics"] = {
        "kind": metric_kind,
        **{
            key: deepcopy(value)
            for key in _METRIC_KEYS_BY_KIND.get(metric_kind, set())
            if (value := metrics.get(key)) is not None
        },
    }
    compact["sources"] = []
    for source in event.get("sources") or []:
        if not isinstance(source, Mapping):
            continue
        compact_source = {
            key: source.get(key)
            for key in ("provider", "nativeId", "observedAt", "ingestedAt", "freshness", "status")
            if source.get(key) is not None
        }
        if compact_source.get("provider"):
            compact["sources"].append(compact_source)

    properties = event.get("properties") if isinstance(event.get("properties"), Mapping) else {}
    compact["properties"] = {
        key: deepcopy(value)
        for key in _RENDER_PROPERTY_KEYS
        if (value := properties.get(key)) is not None
    }
    compact["properties"]["detailAvailable"] = True
    compact["limitations"] = [
        text
        for value in list(event.get("limitations") or [])[:2]
        if (text := _text(value, 160))
    ]
    compact["relatedMarketIds"] = []
    return compact


def _empty_source(key: str, error_code: str) -> dict[str, Any]:
    return {
        "key": key,
        "status": "error",
        "coverage": SOURCE_COVERAGE.get(key, {
            "scope": "provider-area",
            "label": "Provider coverage unavailable.",
            "isComplete": False,
            "gaps": ["Provider is not configured."],
        }),
        "events": [],
        "fetchedAt": None,
        "dataUpdatedAt": None,
        "staleAfter": None,
        "lastSuccessAt": None,
        "errorCode": error_code,
    }


def get_natural_hazard_map_snapshot(
    context: Mapping[str, Any],
    *,
    source: str,
    limit: int = 1200,
    zoom: float = 2.0,
) -> dict[str, Any]:
    key = str(source or "").strip().lower()
    if key not in MAP_SOURCE_KEYS:
        raise ValueError("unsupported-natural-hazard-source")
    bounded_limit = max(1, min(1200, int(limit)))
    if key == "climate-anomaly":
        result = _empty_source(key, "baseline-pipeline-not-configured")
    else:
        result = get_natural_hazard_source_result(
            context,
            source=key,
            limit=bounded_limit,
        )
    events = [
        compact_hazard_event(event, zoom=zoom)
        for event in list(result.get("events") or [])[:bounded_limit]
        if isinstance(event, Mapping)
    ]
    source_state = {name: deepcopy(value) for name, value in result.items() if name != "events"}
    errors = [] if source_state.get("status") == "ok" else [{
        "source": key,
        "code": source_state.get("errorCode"),
    }]
    generated_at = str(source_state.get("dataUpdatedAt") or source_state.get("fetchedAt") or _generated_at())
    return {
        "schemaVersion": MAP_SCHEMA_VERSION,
        "generatedAt": generated_at,
        "events": events,
        "sources": [source_state],
        "isPartial": bool(errors),
        "errors": errors,
        "counts": {
            "events": len(events),
            "byHazardKind": {
                hazard_kind: sum(1 for event in events if event.get("hazardKind") == hazard_kind)
                for hazard_kind in sorted({str(event.get("hazardKind") or "") for event in events})
                if hazard_kind
            },
        },
        "meta": {
            "source": key,
            "geometryMode": "simplified",
            "detailEndpoint": "/runtime/world/natural-hazards/events/{eventId}",
            "fullSchemaVersion": SCHEMA_VERSION,
        },
    }


def get_natural_hazard_event_detail(
    context: Mapping[str, Any],
    *,
    event_id: str,
) -> dict[str, Any] | None:
    wanted = str(event_id or "").strip()
    if not wanted:
        return None
    dependencies = NaturalHazardDependencies.from_context(context)
    for key in MAP_SOURCE_KEYS:
        if key == "climate-anomaly":
            continue
        result = cached_source_result(dependencies.snapshot_store, key)
        if not result:
            continue
        for event in result.get("events") or []:
            if isinstance(event, Mapping) and str(event.get("id") or "") == wanted:
                revision = event.get("revision") if isinstance(event.get("revision"), Mapping) else {}
                generated_at = str(
                    event.get("updatedAt")
                    or revision.get("revisionAt")
                    or _generated_at()
                )
                return {
                    "schemaVersion": DETAIL_SCHEMA_VERSION,
                    "generatedAt": generated_at,
                    "event": deepcopy(dict(event)),
                }
    return None
