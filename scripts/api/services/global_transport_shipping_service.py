from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PANEL_ID = "global-transport-shipping"
GLOBAL_TRANSPORT_SNAPSHOT_NAMESPACE = "snapshot:transport:global-shipping"
GLOBAL_TRANSPORT_CACHE_KEY = "panel-v3"
AISSTREAM_SNAPSHOT_NAMESPACE = "snapshot:transport:aisstream"
AISSTREAM_CACHE_KEY = "sample-v1"
DEFAULT_LIMIT = 14
DEFAULT_TTL_SECONDS = 900
DEFAULT_AISSTREAM_SAMPLE_INTERVAL_SECONDS = 21600
AVIATION_ROUTE_LAYER_LIMIT = 360
AVIATION_FLIGHT_LAYER_LIMIT = 140
EVIDENCE_SCHEMA_VERSION = "air-evidence-v1"

OPENFLIGHTS_AIRPORTS_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
OPENFLIGHTS_ROUTES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"
OPENFLIGHTS_AIRLINES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"
TRANSITLAND_ATLAS_URL = "https://raw.githubusercontent.com/transitland/transitland-atlas/master/feeds/gtfs-source-feeds.transit.land.dmfr.json"
TRANSITLAND_ATLAS_INDEX_URL = "https://api.github.com/repos/transitland/transitland-atlas/contents/feeds"
AISSTREAM_DOC_URL = "https://aisstream.io/documentation"

_LIVE_REFRESH_LOCK = threading.Lock()
_LIVE_REFRESHING: set[str] = set()


def _utc_now_iso(ctx: dict | None = None) -> str:
    if ctx:
        getter = ctx.get("utc_now_iso")
        if callable(getter):
            return getter()
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _source_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _null(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text == r"\N" else text


def _float(value: Any) -> Optional[float]:
    try:
        text = _null(value)
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def _parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_seconds(value: Any) -> Optional[float]:
    parsed = _parse_iso(value)
    if parsed is None:
        return None
    return (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, default) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _local_openflights_path(filename: str) -> Optional[Path]:
    roots = [
        os.environ.get("POLYDATA_OPENFLIGHTS_ROOT"),
        "/home/jiahuaiyu/develop/polymarket/githubProjects/openflights",
        "/opt/openflights",
        "/opt/polyData/openflights",
    ]
    for root in roots:
        if not root:
            continue
        path = Path(root).expanduser() / "data" / filename
        if path.exists():
            return path
    return None


def _http_text(ctx: dict, url: str, *, timeout: int = 18) -> str:
    getter = ctx.get("http_text_get")
    if callable(getter):
        return str(getter(url, timeout=timeout, headers={"User-Agent": "polydata-global-transport/1.0"}))
    raise RuntimeError("http_text_get unavailable")


def _read_openflights_text(ctx: dict, filename: str, url: str) -> tuple[str, str]:
    local_path = _local_openflights_path(filename)
    if local_path is not None:
        return local_path.read_text(encoding="utf-8", errors="replace"), f"file://{local_path}"
    return _http_text(ctx, url), url


def _csv_rows(text: str) -> Iterable[List[str]]:
    return csv.reader(io.StringIO(text))


def _parse_airports(text: str) -> Dict[str, Dict[str, Any]]:
    airports: Dict[str, Dict[str, Any]] = {}
    for row in _csv_rows(text):
        if len(row) < 14:
            continue
        airport_id = _null(row[0])
        iata = _null(row[4])
        icao = _null(row[5])
        item = {
            "id": airport_id,
            "name": _null(row[1]),
            "city": _null(row[2]),
            "country": _null(row[3]),
            "iata": iata,
            "icao": icao,
            "lat": _float(row[6]),
            "lon": _float(row[7]),
            "type": _null(row[12]) or "airport",
            "source": _null(row[13]) or "OpenFlights",
        }
        for key in (airport_id, iata, icao):
            if key:
                airports[key] = item
    return airports


def _parse_airlines(text: str) -> Dict[str, Dict[str, Any]]:
    airlines: Dict[str, Dict[str, Any]] = {}
    for row in _csv_rows(text):
        if len(row) < 8:
            continue
        airline_id = _null(row[0])
        iata = _null(row[3])
        icao = _null(row[4])
        item = {
            "id": airline_id,
            "name": _null(row[1]),
            "country": _null(row[6]),
            "active": _null(row[7]) == "Y",
        }
        for key in (airline_id, iata, icao):
            if key:
                airlines[key] = item
    return airlines


def _parse_routes(text: str, airports: Dict[str, Dict[str, Any]], airlines: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    airport_counts: Counter[str] = Counter()
    country_counts: Counter[str] = Counter()
    country_corridors: Counter[tuple[str, str]] = Counter()
    airline_counts: Counter[str] = Counter()
    equipment_counts: Counter[str] = Counter()
    route_edges: List[Dict[str, Any]] = []
    valid_routes = 0
    direct_routes = 0

    for row in _csv_rows(text):
        if len(row) < 9:
            continue
        airline_code = _null(row[0])
        airline_id = _null(row[1])
        src_key = _null(row[3]) or _null(row[2])
        dst_key = _null(row[5]) or _null(row[4])
        src = airports.get(src_key) or airports.get(_null(row[2]))
        dst = airports.get(dst_key) or airports.get(_null(row[4]))
        if not src or not dst:
            continue
        valid_routes += 1
        if _null(row[7]) in {"", "0"}:
            direct_routes += 1
        src_id = str(src.get("id") or src.get("iata") or src_key)
        dst_id = str(dst.get("id") or dst.get("iata") or dst_key)
        airport_counts[src_id] += 1
        airport_counts[dst_id] += 1
        for country in (src.get("country"), dst.get("country")):
            if country:
                country_counts[str(country)] += 1
        country_pair = tuple(sorted([str(src.get("country") or "Unknown"), str(dst.get("country") or "Unknown")]))
        country_corridors[country_pair] += 1
        airline = airlines.get(airline_id) or airlines.get(airline_code) or {"name": airline_code or "Unknown"}
        airline_counts[str(airline.get("name") or airline_code or "Unknown")] += 1
        for code in _null(row[8]).split():
            if code:
                equipment_counts[code] += 1
        src_lat = src.get("lat")
        src_lon = src.get("lon")
        dst_lat = dst.get("lat")
        dst_lon = dst.get("lon")
        src_code = src.get("iata") or src.get("icao") or src_id
        dst_code = dst.get("iata") or dst.get("icao") or dst_id
        airport_counts[str(src_code)] += 1
        airport_counts[str(dst_code)] += 1
        if (
            isinstance(src_lat, (int, float))
            and isinstance(src_lon, (int, float))
            and isinstance(dst_lat, (int, float))
            and isinstance(dst_lon, (int, float))
            and src_code
            and dst_code
            and src_code != dst_code
        ):
            route_edges.append(
                {
                    "fromCode": src_code,
                    "toCode": dst_code,
                    "fromName": src.get("name") or src_code,
                    "toName": dst.get("name") or dst_code,
                    "fromCity": src.get("city"),
                    "toCity": dst.get("city"),
                    "fromCountry": src.get("country"),
                    "toCountry": dst.get("country"),
                    "fromLat": src_lat,
                    "fromLon": src_lon,
                    "toLat": dst_lat,
                    "toLon": dst_lon,
                    "airline": airline.get("name") or airline_code or "Unknown",
                    "equipment": _null(row[8]),
                    "stops": _null(row[7]) or "0",
                }
            )

    hubs = []
    seen_hubs: set[str] = set()
    for airport_id, count in airport_counts.most_common(48):
        airport = airports.get(airport_id)
        if not airport:
            continue
        key = str(airport.get("id") or airport_id)
        if key in seen_hubs:
            continue
        seen_hubs.add(key)
        hubs.append({**airport, "routeCount": count})
        if len(hubs) >= 24:
            break

    corridors = [
        {"sourceCountry": pair[0], "destCountry": pair[1], "routeCount": count}
        for pair, count in country_corridors.most_common(10)
    ]
    top_route_edges: List[Dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    airport_route_limits: Counter[str] = Counter()
    country_pair_limits: Counter[tuple[str, str]] = Counter()
    route_edges.sort(
        key=lambda edge: (
            airport_counts[str(edge.get("fromCode") or "")]
            + airport_counts[str(edge.get("toCode") or "")],
            edge.get("fromCountry") != edge.get("toCountry"),
        ),
        reverse=True,
    )
    for edge in route_edges:
        pair = tuple(sorted([str(edge.get("fromCode") or ""), str(edge.get("toCode") or "")]))
        if not pair[0] or not pair[1] or pair in seen_pairs:
            continue
        country_pair = tuple(sorted([str(edge.get("fromCountry") or "Unknown"), str(edge.get("toCountry") or "Unknown")]))
        from_code = str(edge.get("fromCode") or "")
        to_code = str(edge.get("toCode") or "")
        if airport_route_limits[from_code] >= 28 or airport_route_limits[to_code] >= 28:
            continue
        if country_pair_limits[country_pair] >= 34:
            continue
        seen_pairs.add(pair)
        airport_route_limits[from_code] += 1
        airport_route_limits[to_code] += 1
        country_pair_limits[country_pair] += 1
        from_score = airport_counts[from_code]
        to_score = airport_counts[to_code]
        traffic_score = min(100, max(18, round((from_score + to_score) / 35)))
        is_international = edge.get("fromCountry") != edge.get("toCountry")
        route_key = f"{edge.get('fromCode')}-{edge.get('toCode')}"
        phase_seed = int(hashlib.sha1(route_key.encode("utf-8")).hexdigest()[:4], 16)
        top_route_edges.append(
            {
                **edge,
                "id": _source_hash(route_key),
                "corridor": f"{edge.get('fromCountry') or 'Unknown'} / {edge.get('toCountry') or 'Unknown'}",
                "trafficScore": traffic_score,
                "riskScore": min(88, max(8, 18 + (12 if is_international else 0) + round(traffic_score * 0.28))),
                "status": "watch" if is_international and traffic_score >= 70 else "normal",
                "layer": "trunk" if traffic_score >= 70 else ("international" if is_international else "regional"),
                "phase": round((phase_seed % 1000) / 1000, 3),
                "speed": round(0.055 + ((phase_seed % 7) * 0.007), 3),
            }
        )
        if len(top_route_edges) >= AVIATION_ROUTE_LAYER_LIMIT:
            break

    return {
        "routeCount": valid_routes,
        "directRouteCount": direct_routes,
        "countryCount": len(country_counts),
        "topHubs": hubs,
        "topRoutes": top_route_edges,
        "topCountryCorridors": corridors,
        "topAirlines": [{"name": name, "routeCount": count} for name, count in airline_counts.most_common(8)],
        "topEquipment": [{"code": code, "routeCount": count} for code, count in equipment_counts.most_common(8)],
    }


def _route_risk_sources(route: Dict[str, Any]) -> List[str]:
    sources: List[str] = []
    from_country = str(route.get("fromCountry") or "")
    to_country = str(route.get("toCountry") or "")
    traffic_score = int(route.get("trafficScore") or 0)
    risk_score = int(route.get("riskScore") or 0)
    conflict_watch = {
        "Iran",
        "Iraq",
        "Israel",
        "Lebanon",
        "Palestine",
        "Russia",
        "Ukraine",
        "Syria",
        "Yemen",
        "Sudan",
        "Libya",
        "Pakistan",
    }
    weather_watch = {
        "United States",
        "Mexico",
        "Japan",
        "China",
        "Philippines",
        "India",
        "Bangladesh",
        "Vietnam",
        "Indonesia",
        "Australia",
    }
    if route.get("layer") in {"trunk", "international"} or traffic_score >= 55 or from_country != to_country:
        sources.append("corridor")
    if from_country in conflict_watch or to_country in conflict_watch:
        sources.append("conflict")
    if from_country in weather_watch or to_country in weather_watch or risk_score >= 62:
        sources.append("weather")
    return list(dict.fromkeys(sources))


def _route_risk_reason(route: Dict[str, Any], sources: List[str]) -> str:
    pieces = []
    if "corridor" in sources:
        pieces.append(f"{route.get('layer') or 'route'} corridor / {route.get('trafficScore') or 0} traffic")
    if "conflict" in sources:
        pieces.append("country-pair intersects conflict watchlist")
    if "weather" in sources:
        pieces.append("endpoint region has weather disruption exposure")
    return "; ".join(pieces) or "baseline OpenFlights route edge"


def _trend(seed: str, *, length: int = 9, floor: int = 16, ceiling: int = 92) -> List[int]:
    base = int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8], 16)
    values = []
    for index in range(length):
        step = ((base >> (index % 12)) + index * 17) % 29
        values.append(max(floor, min(ceiling, floor + step + index * 3)))
    return values


def _build_aviation_layer(route_stats: Dict[str, Any], *, generated_at: str, source_url: str) -> Dict[str, Any]:
    hubs = []
    for hub in route_stats.get("topHubs", [])[:24]:
        code = hub.get("iata") or hub.get("icao") or hub.get("id")
        route_count = int(hub.get("routeCount") or 0)
        hubs.append(
            {
                "code": code,
                "name": hub.get("name") or code,
                "city": hub.get("city"),
                "country": hub.get("country"),
                "lat": hub.get("lat"),
                "lon": hub.get("lon"),
                "routeCount": route_count,
                "status": "watch" if route_count >= 1200 else "normal",
                "riskScore": min(92, max(12, round(route_count / 18))),
                "delayScore": min(88, max(5, round(route_count / 34))),
                "trend": _trend(str(code or hub.get("name") or "hub"), floor=18, ceiling=86),
                "source": "OpenFlights",
                "sourceUrl": source_url,
                "evidenceType": "airport",
            }
        )
    routes = route_stats.get("topRoutes", [])[:AVIATION_ROUTE_LAYER_LIMIT]
    enriched_routes: List[Dict[str, Any]] = []
    for route in routes:
        risk_sources = _route_risk_sources(route)
        risk_reason = _route_risk_reason(route, risk_sources)
        confidence = 0.72
        if route.get("layer") == "trunk":
            confidence += 0.08
        if "conflict" in risk_sources or "weather" in risk_sources:
            confidence += 0.04
        enriched_routes.append(
            {
                **route,
                "riskSources": risk_sources,
                "riskReason": risk_reason,
                "confidence": round(min(0.92, confidence), 2),
                "source": "OpenFlights",
                "sourceUrl": source_url,
                "evidenceType": "air_route",
                "updatedAt": generated_at,
                "trend": _trend(f"{route.get('fromCode')}-{route.get('toCode')}", floor=12, ceiling=94),
                "relatedPolymarketMarketIds": [],
            }
        )
    routes = enriched_routes
    flights = []
    for index, route in enumerate(routes[:AVIATION_FLIGHT_LAYER_LIMIT]):
        callsign_seed = str(route.get("airline") or "AIR").upper().replace(" ", "")[:3] or "AIR"
        flights.append(
            {
                "id": f"flight-{route.get('id') or index}",
                "callsign": f"{callsign_seed}{100 + index}",
                "fromCode": route.get("fromCode"),
                "toCode": route.get("toCode"),
                "fromLon": route.get("fromLon"),
                "fromLat": route.get("fromLat"),
                "toLon": route.get("toLon"),
                "toLat": route.get("toLat"),
                "phase": route.get("phase", 0),
                "speed": route.get("speed", 0.06),
                "status": route.get("status", "normal"),
                "riskScore": route.get("riskScore", 0),
                "trafficScore": route.get("trafficScore", 0),
                "riskSources": route.get("riskSources") or [],
                "riskReason": route.get("riskReason"),
                "layer": route.get("layer"),
                "source": "OpenFlights",
                "sourceUrl": source_url,
            }
        )
    airline_rows = []
    for index, row in enumerate(route_stats.get("topAirlines", [])[:8]):
        route_count = int(row.get("routeCount") or 0)
        airline_rows.append(
            {
                **row,
                "status": "watch" if route_count >= 1200 else "normal",
                "exposureScore": min(100, max(8, round(route_count / 12))),
                "trend": _trend(str(row.get("name") or index), floor=10, ceiling=90),
                "source": "OpenFlights",
                "sourceUrl": source_url,
            }
        )
    ops_rows = [
        {
            "code": hub.get("code"),
            "name": hub.get("name"),
            "city": hub.get("city"),
            "country": hub.get("country"),
            "status": hub.get("status"),
            "riskScore": hub.get("riskScore"),
            "delayScore": hub.get("delayScore"),
            "routeCount": hub.get("routeCount"),
            "trend": hub.get("trend"),
            "source": hub.get("source"),
            "sourceUrl": hub.get("sourceUrl"),
        }
        for hub in hubs[:8]
    ]
    news_rows = [
        {
            "title": f"{route.get('fromCode')} -> {route.get('toCode')} {route.get('layer')} corridor",
            "corridor": route.get("corridor"),
            "status": "watch" if route.get("riskSources") else route.get("status"),
            "riskScore": route.get("riskScore"),
            "riskSources": route.get("riskSources"),
            "riskReason": route.get("riskReason"),
            "source": "OpenFlights",
            "sourceUrl": source_url,
            "updatedAt": generated_at,
        }
        for route in routes[:8]
    ]
    return {
        "generatedAt": generated_at,
        "mode": "seeded-route-graph",
        "hubs": hubs,
        "routes": routes,
        "flights": flights,
        "ops": ops_rows,
        "airlines": airline_rows,
        "news": news_rows,
    }


def _evidence_record(
    *,
    evidence_type: str,
    entity: str,
    lat: Any = None,
    lon: Any = None,
    route: Any = None,
    severity: str = "normal",
    confidence: float = 0.7,
    source: str,
    source_url: str,
    updated_at: str,
    related_market_ids: Optional[List[Any]] = None,
    risk_sources: Optional[List[str]] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "type": evidence_type,
        "entity": entity,
        "lat": lat,
        "lon": lon,
        "route": route,
        "severity": severity,
        "confidence": confidence,
        "source": source,
        "sourceUrl": source_url,
        "updatedAt": updated_at,
        "relatedMarketIds": related_market_ids or [],
        "riskSources": risk_sources or [],
        "reason": reason,
    }


def _build_evidence_payload(aviation: Dict[str, Any], items: List[Dict[str, Any]], *, generated_at: str) -> Dict[str, Any]:
    route_records = [
        _evidence_record(
            evidence_type="air_route",
            entity=f"{route.get('fromCode')}->{route.get('toCode')}",
            route=[route.get("fromCode"), route.get("toCode")],
            severity="watch" if route.get("riskSources") else "normal",
            confidence=float(route.get("confidence") or 0.72),
            source=str(route.get("source") or "OpenFlights"),
            source_url=str(route.get("sourceUrl") or OPENFLIGHTS_ROUTES_URL),
            updated_at=generated_at,
            related_market_ids=route.get("relatedPolymarketMarketIds") or [],
            risk_sources=route.get("riskSources") or [],
            reason=route.get("riskReason"),
        )
        for route in aviation.get("routes", [])[:96]
    ]
    ops_records = [
        _evidence_record(
            evidence_type="airport",
            entity=str(row.get("code") or row.get("name") or "Airport"),
            severity=str(row.get("status") or "normal"),
            confidence=0.78,
            source=str(row.get("source") or "OpenFlights"),
            source_url=str(row.get("sourceUrl") or OPENFLIGHTS_ROUTES_URL),
            updated_at=generated_at,
            reason=f"{row.get('routeCount') or 0} route edges / delay proxy {row.get('delayScore') or 0}",
        )
        for row in aviation.get("ops", [])
    ]
    risk_records = [
        _evidence_record(
            evidence_type=str(item.get("evidenceType") or item.get("topic") or "transport"),
            entity=str(item.get("entity") or item.get("title") or "transport"),
            severity=str(item.get("severity") or "normal"),
            confidence=float(item.get("confidence") or 0.6),
            source=str(item.get("evidenceType") or item.get("source") or "transport"),
            source_url=str(item.get("sourceUrl") or OPENFLIGHTS_ROUTES_URL),
            updated_at=str(item.get("eventTime") or generated_at),
            related_market_ids=item.get("relatedPolymarketMarketIds") or [],
            risk_sources=list(item.get("tags") or []),
            reason=str(item.get("summary") or item.get("title") or ""),
        )
        for item in items
    ]
    return {
        "schemaVersion": EVIDENCE_SCHEMA_VERSION,
        "routes": route_records,
        "risks": risk_records,
        "ops": ops_records,
    }


def _parse_transitland_payloads(payloads: Iterable[Dict[str, Any]], *, catalog_file_count: int = 0, scanned_file_count: int = 0) -> Dict[str, Any]:
    operators_by_id: Dict[str, Dict[str, Any]] = {}
    spec_counts: Counter[str] = Counter()
    authorization_counts: Counter[str] = Counter()
    country_hint_counts: Counter[str] = Counter()
    sample_feeds: List[Dict[str, Any]] = []

    for payload in payloads:
        feeds = payload.get("feeds") if isinstance(payload.get("feeds"), list) else []
        for feed in feeds:
            if not isinstance(feed, dict):
                continue
            spec = str(feed.get("spec") or "unknown")
            spec_counts[spec] += 1
            auth = feed.get("authorization")
            auth_type = "open"
            if isinstance(auth, dict) and auth.get("type"):
                auth_type = str(auth.get("type"))
            authorization_counts[auth_type] += 1
            feed_id = str(feed.get("id") or "")
            parts = feed_id.split("-")
            if len(parts) >= 2:
                country_hint_counts[parts[-1]] += 1
            for operator in feed.get("operators") or []:
                if not isinstance(operator, dict):
                    continue
                operator_id = str(operator.get("onestop_id") or operator.get("id") or operator.get("name") or "")
                if operator_id:
                    operators_by_id[operator_id] = operator
            if len(sample_feeds) >= 8:
                continue
            urls = feed.get("urls") if isinstance(feed.get("urls"), dict) else {}
            sample_feeds.append(
                {
                    "id": feed_id,
                    "spec": spec,
                    "url": urls.get("static_current") or urls.get("realtime_vehicle_positions") or urls.get("realtime_trip_updates"),
                    "authorization": auth_type,
                    "operators": [op.get("name") for op in feed.get("operators") or [] if isinstance(op, dict) and op.get("name")][:3],
                }
            )

    return {
        "feedCount": sum(spec_counts.values()),
        "operatorCount": len(operators_by_id),
        "catalogFileCount": catalog_file_count,
        "scannedFileCount": scanned_file_count,
        "specCounts": dict(spec_counts),
        "authorizationCounts": dict(authorization_counts),
        "topCountryHints": [{"code": key, "feedCount": value} for key, value in country_hint_counts.most_common(8)],
        "sampleFeeds": sample_feeds,
    }


def _select_evenly(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    if limit <= 0 or len(rows) <= limit:
        return rows
    if limit == 1:
        return [rows[0]]
    step = (len(rows) - 1) / float(limit - 1)
    indexes = sorted({round(index * step) for index in range(limit)})
    return [rows[index] for index in indexes]


def _fetch_transitland_catalog(ctx: dict) -> tuple[Dict[str, Any], str]:
    explicit_urls = [
        url.strip()
        for url in str(os.environ.get("POLYDATA_TRANSITLAND_ATLAS_URLS") or "").split(",")
        if url.strip()
    ]
    legacy_url = str(os.environ.get("POLYDATA_TRANSITLAND_ATLAS_URL") or "").strip()
    if explicit_urls or legacy_url:
        urls = explicit_urls or [legacy_url]
        payloads = []
        for url in urls:
            parsed = json.loads(_http_text(ctx, url, timeout=20))
            if isinstance(parsed, dict):
                payloads.append(parsed)
        return _parse_transitland_payloads(payloads, catalog_file_count=len(urls), scanned_file_count=len(payloads)), urls[0] if urls else TRANSITLAND_ATLAS_URL

    index_url = os.environ.get("POLYDATA_TRANSITLAND_ATLAS_INDEX_URL", TRANSITLAND_ATLAS_INDEX_URL)
    file_limit = max(1, min(int(os.environ.get("POLYDATA_TRANSITLAND_ATLAS_FILE_LIMIT", "48") or 48), 120))
    index_payload = json.loads(_http_text(ctx, index_url, timeout=20))
    files = []
    if isinstance(index_payload, list):
        for item in index_payload:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            url = str(item.get("download_url") or "")
            if name.endswith(".dmfr.json") and url:
                files.append({"name": name, "downloadUrl": url})
    selected = _select_evenly(files, file_limit)
    payloads = []
    for item in selected:
        parsed = json.loads(_http_text(ctx, item["downloadUrl"], timeout=20))
        if isinstance(parsed, dict):
            payloads.append(parsed)
    if payloads:
        return _parse_transitland_payloads(payloads, catalog_file_count=len(files), scanned_file_count=len(payloads)), index_url
    parsed = json.loads(_http_text(ctx, TRANSITLAND_ATLAS_URL, timeout=20))
    payloads = [parsed] if isinstance(parsed, dict) else []
    return _parse_transitland_payloads(payloads, catalog_file_count=1, scanned_file_count=len(payloads)), TRANSITLAND_ATLAS_URL


async def _sample_aisstream(api_key: str, *, timeout_seconds: int) -> Dict[str, Any]:
    import asyncio
    import websockets

    uri = os.environ.get("POLYDATA_AISSTREAM_WS_URL", "wss://stream.aisstream.io/v0/stream")
    bbox = json.loads(os.environ.get("POLYDATA_AISSTREAM_BBOX_JSON", "[[[-180,-90],[180,90]]]"))
    subscription = {
        "APIKey": api_key,
        "BoundingBoxes": bbox,
        "FilterMessageTypes": ["PositionReport"],
    }
    vessels = 0
    countries: Counter[str] = Counter()
    started = datetime.now(timezone.utc)
    async with websockets.connect(uri, open_timeout=timeout_seconds) as websocket:
        await websocket.send(json.dumps(subscription))
        while (datetime.now(timezone.utc) - started).total_seconds() < timeout_seconds:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                break
            vessels += 1
            try:
                payload = json.loads(message)
                meta = payload.get("MetaData") if isinstance(payload, dict) else {}
                country = str((meta or {}).get("ShipName") or "AIS").strip()[:3] or "AIS"
                countries[country] += 1
            except Exception:
                continue
            if vessels >= int(os.environ.get("POLYDATA_AISSTREAM_SAMPLE_LIMIT", "12") or 12):
                break
    return {"status": "ok", "messageCount": vessels, "topShipHints": dict(countries.most_common(5))}


def _aisstream_api_key() -> str:
    return str(os.environ.get("POLYDATA_AISSTREAM_API_KEY") or os.environ.get("AISSTREAM_API_KEY") or "").strip()


def _read_aisstream_cache(ctx: dict, *, max_age_seconds: int) -> Optional[Dict[str, Any]]:
    reader = ctx.get("get_cached_json")
    payload = reader(AISSTREAM_SNAPSHOT_NAMESPACE, AISSTREAM_CACHE_KEY) if callable(reader) else None
    if not isinstance(payload, dict):
        store = ctx.get("SNAPSHOT_STORE")
        if store is not None:
            payload = store.get(AISSTREAM_SNAPSHOT_NAMESPACE, AISSTREAM_CACHE_KEY)
    if not isinstance(payload, dict):
        return None
    sampled_at = payload.get("sampledAt") or payload.get("generatedAt")
    age = _age_seconds(sampled_at)
    if age is None or age > max_age_seconds:
        return None
    return {**payload, "cacheMode": "ais-cache", "ageSeconds": round(max(0, age))}


def _store_aisstream_cache(ctx: dict, payload: Dict[str, Any], *, ttl_seconds: int) -> None:
    store = ctx.get("SNAPSHOT_STORE")
    if store is not None:
        store.set(AISSTREAM_SNAPSHOT_NAMESPACE, AISSTREAM_CACHE_KEY, payload, ttl_seconds)
    setter = ctx.get("set_cached_json")
    if callable(setter):
        setter(AISSTREAM_SNAPSHOT_NAMESPACE, AISSTREAM_CACHE_KEY, payload, ttl_seconds)


def _aisstream_status(ctx: dict) -> Dict[str, Any]:
    api_key = _aisstream_api_key()
    min_interval = _env_int(
        "POLYDATA_AISSTREAM_MIN_SAMPLE_INTERVAL_SECONDS",
        DEFAULT_AISSTREAM_SAMPLE_INTERVAL_SECONDS,
        minimum=900,
        maximum=86400,
    )
    if not api_key:
        return {"status": "missing-key", "messageCount": 0, "sourceUrl": AISSTREAM_DOC_URL}
    cached = _read_aisstream_cache(ctx, max_age_seconds=min_interval)
    if cached is not None:
        return cached
    if not _env_bool("POLYDATA_AISSTREAM_SAMPLE_ENABLED", True):
        return {
            "status": "configured",
            "messageCount": 0,
            "sourceUrl": AISSTREAM_DOC_URL,
            "cacheTtlSeconds": min_interval,
            "sampleEnabled": False,
        }
    try:
        import asyncio

        timeout_seconds = _env_int("POLYDATA_AISSTREAM_SAMPLE_SECONDS", 8, minimum=3, maximum=20)
        sampled = {
            **asyncio.run(_sample_aisstream(api_key, timeout_seconds=timeout_seconds)),
            "sourceUrl": AISSTREAM_DOC_URL,
            "sampledAt": _utc_now_iso(ctx),
            "sampleWindowSeconds": timeout_seconds,
            "cacheTtlSeconds": min_interval,
        }
        _store_aisstream_cache(ctx, sampled, ttl_seconds=min_interval)
        return sampled
    except Exception as exc:
        error_payload = {
            "status": "error",
            "messageCount": 0,
            "error": exc.__class__.__name__,
            "sourceUrl": AISSTREAM_DOC_URL,
            "sampledAt": _utc_now_iso(ctx),
            "cacheTtlSeconds": min_interval,
        }
        _store_aisstream_cache(ctx, error_payload, ttl_seconds=min_interval)
        return error_payload


def _market_links(ctx: dict, query: str) -> List[Dict[str, Any]]:
    search = ctx.get("search_markets")
    if not callable(search):
        return []
    try:
        rows = search(query, limit=3) or []
    except Exception:
        return []
    if isinstance(rows, dict):
        rows = rows.get("items") or []
    if not isinstance(rows, list):
        return []
    links = []
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        links.append(
            {
                "marketId": row.get("id") or row.get("marketId"),
                "slug": row.get("slug"),
                "question": row.get("question") or row.get("title"),
                "marketUrl": f"https://polymarket.com/event/{row.get('slug')}" if row.get("slug") else None,
                "matchScore": 0.62,
                "matchReasons": ["transport", "entity"],
            }
        )
    return links


def _item(*, topic: str, entity: str, country: str, title: str, summary: str, metric: int, metric_label: str, source_url: str, evidence_type: str, confidence: float, severity: str, tags: List[str], evidence: Dict[str, Any], markets: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    market_rows = markets or []
    return {
        "id": _source_hash(f"{topic}|{entity}|{title}"),
        "topic": topic,
        "entity": entity,
        "country": country,
        "team": None,
        "eventTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sourceUrl": source_url,
        "evidenceType": evidence_type,
        "title": title,
        "summary": summary,
        "metric": metric,
        "metricLabel": metric_label,
        "confidence": confidence,
        "severity": severity,
        "tags": tags,
        "relatedPolymarketMarketIds": [row.get("marketId") for row in market_rows if row.get("marketId")],
        "markets": market_rows,
        "evidence": evidence,
    }


def build_global_transport_shipping_payload(ctx: dict, *, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    generated_at = _utc_now_iso(ctx)
    airports_text, airports_source = _read_openflights_text(ctx, "airports.dat", OPENFLIGHTS_AIRPORTS_URL)
    routes_text, routes_source = _read_openflights_text(ctx, "routes.dat", OPENFLIGHTS_ROUTES_URL)
    try:
        airlines_text, _ = _read_openflights_text(ctx, "airlines.dat", OPENFLIGHTS_AIRLINES_URL)
    except Exception:
        airlines_text = ""
    airports = _parse_airports(airports_text)
    airlines = _parse_airlines(airlines_text)
    route_stats = _parse_routes(routes_text, airports, airlines)

    transit_stats, transit_url = _fetch_transitland_catalog(ctx)
    ais_status = _aisstream_status(ctx)

    items: List[Dict[str, Any]] = []
    for hub in route_stats["topHubs"][:6]:
        code = hub.get("iata") or hub.get("icao") or hub.get("id")
        markets = _market_links(ctx, f"{code} airport delay travel disruption")
        items.append(
            _item(
                topic="aviation",
                entity=str(code or hub.get("name") or "Airport"),
                country=str(hub.get("country") or ""),
                title=f"{hub.get('name') or code} route hub",
                summary=f"{hub.get('city') or 'Unknown city'} / {hub.get('country') or 'Unknown'} has {hub.get('routeCount')} OpenFlights route edges.",
                metric=int(hub.get("routeCount") or 0),
                metric_label="ROUTES",
                source_url=routes_source,
                evidence_type="OPENFLIGHTS",
                confidence=0.82,
                severity="watch" if int(hub.get("routeCount") or 0) >= 1200 else "normal",
                tags=["airport", "routes"],
                evidence=hub,
                markets=markets,
            )
        )
    for corridor in route_stats["topCountryCorridors"][:4]:
        entity = f"{corridor['sourceCountry']} / {corridor['destCountry']}"
        items.append(
            _item(
                topic="aviation",
                entity=entity,
                country=str(corridor["sourceCountry"]),
                title=f"{entity} air corridor",
                summary=f"{corridor['routeCount']} directional OpenFlights route edges connect this country pair.",
                metric=int(corridor["routeCount"]),
                metric_label="EDGES",
                source_url=routes_source,
                evidence_type="OPENFLIGHTS",
                confidence=0.78,
                severity="normal",
                tags=["corridor", "air"],
                evidence=corridor,
                markets=_market_links(ctx, f"{entity} flight disruption airline"),
            )
        )
    gtfs_count = int(transit_stats.get("specCounts", {}).get("gtfs", 0))
    items.append(
        _item(
            topic="public-transit",
            entity="Transitland Atlas",
            country="Global",
            title="Transitland mobility feed catalog",
            summary=f"{transit_stats['feedCount']} feeds / {transit_stats['operatorCount']} operators across {transit_stats.get('scannedFileCount', 0)} of {transit_stats.get('catalogFileCount', 0)} DMFR files.",
            metric=int(transit_stats["feedCount"]),
            metric_label="FEEDS",
            source_url=transit_url,
            evidence_type="TRANSITLAND",
            confidence=0.86,
            severity="normal",
            tags=["gtfs", "operators"],
            evidence=transit_stats,
            markets=_market_links(ctx, "public transit strike delay gtfs"),
        )
    )
    items.append(
        _item(
            topic="public-transit",
            entity="GTFS coverage",
            country="Global",
            title="GTFS static feed coverage",
            summary=f"{gtfs_count} static GTFS feeds, authorization mix: {transit_stats.get('authorizationCounts') or {}}.",
            metric=gtfs_count,
            metric_label="GTFS",
            source_url=transit_url,
            evidence_type="TRANSITLAND",
            confidence=0.8,
            severity="watch" if gtfs_count == 0 else "normal",
            tags=["gtfs", "catalog"],
            evidence={"specCounts": transit_stats.get("specCounts"), "sampleFeeds": transit_stats.get("sampleFeeds")},
        )
    )
    ais_severity = "watch" if ais_status.get("status") in {"missing-key", "error"} else "normal"
    items.append(
        _item(
            topic="shipping",
            entity="AISStream",
            country="Global",
            title="Global AIS websocket status",
            summary=f"AISStream status: {ais_status.get('status')}. Uses cached low-frequency samples when AISSTREAM_API_KEY is configured.",
            metric=int(ais_status.get("messageCount") or 0),
            metric_label="AIS MSG",
            source_url=AISSTREAM_DOC_URL,
            evidence_type="AISSTREAM",
            confidence=0.48 if ais_status.get("status") == "missing-key" else 0.76,
            severity=ais_severity,
            tags=["ais", "shipping"],
            evidence=ais_status,
            markets=_market_links(ctx, "shipping disruption port vessel"),
        )
    )
    items.sort(key=lambda row: (0 if row["severity"] == "watch" else 1, -int(row.get("metric") or 0)))
    limited = items[: max(1, int(limit or DEFAULT_LIMIT))]
    aviation = _build_aviation_layer(route_stats, generated_at=generated_at, source_url=routes_source)
    evidence_payload = _build_evidence_payload(aviation, limited, generated_at=generated_at)
    source_health = {
        "openflights": "fresh",
        "transitland": "fresh",
        "aisstream": "degraded" if ais_status.get("status") in {"missing-key", "error"} else ("stale" if ais_status.get("cacheMode") else "fresh"),
        "weatherRiskJoin": "frontend-runtime",
        "conflictRiskJoin": "frontend-runtime",
    }
    return {
        "panelId": PANEL_ID,
        "generatedAt": generated_at,
        "status": "ok" if items else "empty",
        "cacheMode": "live-build",
        "freshness": "live",
        "source": "OpenFlights + Transitland Atlas + AISStream",
        "sourceUrl": OPENFLIGHTS_AIRPORTS_URL,
        "sources": {
            "openflights": {"status": "ok", "airportsSource": airports_source, "routesSource": routes_source},
            "transitland": {"status": "ok", "sourceUrl": transit_url},
            "aisstream": {"status": ais_status.get("status"), "sourceUrl": AISSTREAM_DOC_URL},
        },
        "sourceHealth": source_health,
        "cachePolicy": {
            "staticTtlSeconds": 86400,
            "snapshotTtlSeconds": DEFAULT_TTL_SECONDS,
            "aisMinSampleIntervalSeconds": _env_int(
                "POLYDATA_AISSTREAM_MIN_SAMPLE_INTERVAL_SECONDS",
                DEFAULT_AISSTREAM_SAMPLE_INTERVAL_SECONDS,
                minimum=900,
                maximum=86400,
            ),
            "quotaGuard": {
                "aisstream": "cached-low-frequency",
                "openflights": "static-source",
                "transitland": "sampled-catalog",
            },
        },
        "summary": {
            "airports": len({row.get("id") for row in airports.values() if row.get("id")}),
            "routes": route_stats["routeCount"],
            "visibleRoutes": len(aviation.get("routes", [])),
            "flightSamples": len(aviation.get("flights", [])),
            "countries": route_stats["countryCount"],
            "topHub": (route_stats["topHubs"][0].get("iata") or route_stats["topHubs"][0].get("name")) if route_stats["topHubs"] else None,
            "transitFeeds": transit_stats["feedCount"],
            "transitOperators": transit_stats["operatorCount"],
            "transitCatalogFiles": transit_stats.get("catalogFileCount", 0),
            "transitScannedFiles": transit_stats.get("scannedFileCount", 0),
            "aisStatus": ais_status.get("status"),
            "evidenceVersion": EVIDENCE_SCHEMA_VERSION,
        },
        "aviation": aviation,
        "evidence": evidence_payload,
        "items": limited,
    }


def _empty_payload(ctx: dict, *, cache_mode: str = "seed-miss") -> Dict[str, Any]:
    return {
        "panelId": PANEL_ID,
        "generatedAt": _utc_now_iso(ctx),
        "status": "warming",
        "cacheMode": cache_mode,
        "freshness": "warming",
        "source": "OpenFlights + Transitland Atlas + AISStream",
        "sourceUrl": OPENFLIGHTS_AIRPORTS_URL,
        "sources": {},
        "summary": {"airports": 0, "routes": 0, "visibleRoutes": 0, "flightSamples": 0, "countries": 0, "topHub": None, "transitFeeds": 0, "transitOperators": 0, "aisStatus": "unknown", "evidenceVersion": EVIDENCE_SCHEMA_VERSION},
        "aviation": {"mode": "warming", "hubs": [], "routes": [], "flights": [], "ops": [], "airlines": [], "news": []},
        "evidence": {"schemaVersion": EVIDENCE_SCHEMA_VERSION, "routes": [], "risks": [], "ops": []},
        "items": [],
    }


def normalize_global_transport_shipping_payload(payload: Dict[str, Any], *, ctx: dict, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    return {
        **payload,
        "panelId": PANEL_ID,
        "generatedAt": payload.get("generatedAt") or _utc_now_iso(ctx),
        "items": items[: max(1, int(limit or DEFAULT_LIMIT))],
    }


def _with_cache_mode(payload: Dict[str, Any], cache_mode: str, freshness: str = "seeded") -> Dict[str, Any]:
    return {**payload, "cacheMode": cache_mode, "freshness": payload.get("freshness") or freshness}


def _read_seeded_snapshot(ctx: dict) -> Optional[Dict[str, Any]]:
    reader = ctx.get("get_cached_json")
    if callable(reader):
        payload = reader(GLOBAL_TRANSPORT_SNAPSHOT_NAMESPACE, GLOBAL_TRANSPORT_CACHE_KEY)
        if isinstance(payload, dict):
            return _with_cache_mode(payload, "redis-seed")
    store = ctx.get("SNAPSHOT_STORE")
    if store is None:
        return None
    payload = store.get(GLOBAL_TRANSPORT_SNAPSHOT_NAMESPACE, GLOBAL_TRANSPORT_CACHE_KEY)
    if isinstance(payload, dict):
        return _with_cache_mode(payload, "sqlite-seed")
    stale = store.get_stale(GLOBAL_TRANSPORT_SNAPSHOT_NAMESPACE, GLOBAL_TRANSPORT_CACHE_KEY)
    if isinstance(stale, dict):
        return _with_cache_mode(stale, "stale-seed")
    return None


def _store_live(ctx: dict, payload: Dict[str, Any], *, ttl_seconds: int) -> None:
    store = ctx.get("SNAPSHOT_STORE")
    if store is not None:
        store.set(GLOBAL_TRANSPORT_SNAPSHOT_NAMESPACE, GLOBAL_TRANSPORT_CACHE_KEY, payload, ttl_seconds)
    setter = ctx.get("set_cached_json")
    if callable(setter):
        setter(GLOBAL_TRANSPORT_SNAPSHOT_NAMESPACE, GLOBAL_TRANSPORT_CACHE_KEY, payload, ttl_seconds)


def _schedule_live_refresh(ctx: dict, *, limit: int, ttl_seconds: int, reason: str) -> bool:
    refresh_key = f"{GLOBAL_TRANSPORT_SNAPSHOT_NAMESPACE}:{GLOBAL_TRANSPORT_CACHE_KEY}"
    with _LIVE_REFRESH_LOCK:
        if refresh_key in _LIVE_REFRESHING:
            return False
        _LIVE_REFRESHING.add(refresh_key)

    def refresh() -> None:
        logger = getattr(ctx.get("app"), "logger", None)
        try:
            payload = {**build_global_transport_shipping_payload(ctx, limit=limit), "cacheMode": "live-build"}
            if payload.get("items"):
                _store_live(ctx, payload, ttl_seconds=ttl_seconds)
            elif logger is not None and hasattr(logger, "warning"):
                logger.warning("global transport refresh skipped empty payload reason=%s", reason)
        except Exception:
            if logger is not None:
                logger.exception("global transport refresh failed reason=%s", reason)
        finally:
            with _LIVE_REFRESH_LOCK:
                _LIVE_REFRESHING.discard(refresh_key)

    thread = threading.Thread(target=refresh, name="global-transport-refresh", daemon=True)
    thread.start()
    return True


def get_global_transport_shipping_snapshot(ctx: dict, limit: int = DEFAULT_LIMIT, *, allow_live_build: bool = True) -> Dict[str, Any]:
    ttl_seconds = max(300, int(os.environ.get("POLYDATA_GLOBAL_TRANSPORT_TTL_SECONDS", DEFAULT_TTL_SECONDS) or DEFAULT_TTL_SECONDS))
    seeded = _read_seeded_snapshot(ctx)
    if seeded is not None:
        if allow_live_build and seeded.get("cacheMode") == "stale-seed":
            _schedule_live_refresh(ctx, limit=limit, ttl_seconds=ttl_seconds, reason="stale-seed")
        return normalize_global_transport_shipping_payload(seeded, ctx=ctx, limit=limit)
    if not allow_live_build:
        return normalize_global_transport_shipping_payload(_empty_payload(ctx, cache_mode="seed-miss"), ctx=ctx, limit=limit)
    scheduled = _schedule_live_refresh(ctx, limit=limit, ttl_seconds=ttl_seconds, reason="seed-miss")
    mode = "seed-miss-refreshing" if scheduled else "seed-miss-refresh-inflight"
    return normalize_global_transport_shipping_payload(_empty_payload(ctx, cache_mode=mode), ctx=ctx, limit=limit)
