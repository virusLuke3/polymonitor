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
GLOBAL_TRANSPORT_CACHE_KEY = "panel-v1"
DEFAULT_LIMIT = 14
DEFAULT_TTL_SECONDS = 900

OPENFLIGHTS_AIRPORTS_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
OPENFLIGHTS_ROUTES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"
OPENFLIGHTS_AIRLINES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"
TRANSITLAND_ATLAS_URL = "https://raw.githubusercontent.com/transitland/transitland-atlas/master/feeds/gtfs-source-feeds.transit.land.dmfr.json"
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

    hubs = []
    seen_hubs: set[str] = set()
    for airport_id, count in airport_counts.most_common(20):
        airport = airports.get(airport_id)
        if not airport:
            continue
        key = str(airport.get("id") or airport_id)
        if key in seen_hubs:
            continue
        seen_hubs.add(key)
        hubs.append({**airport, "routeCount": count})
        if len(hubs) >= 10:
            break

    corridors = [
        {"sourceCountry": pair[0], "destCountry": pair[1], "routeCount": count}
        for pair, count in country_corridors.most_common(10)
    ]
    return {
        "routeCount": valid_routes,
        "directRouteCount": direct_routes,
        "countryCount": len(country_counts),
        "topHubs": hubs,
        "topCountryCorridors": corridors,
        "topAirlines": [{"name": name, "routeCount": count} for name, count in airline_counts.most_common(8)],
        "topEquipment": [{"code": code, "routeCount": count} for code, count in equipment_counts.most_common(8)],
    }


def _parse_transitland(payload: Dict[str, Any]) -> Dict[str, Any]:
    feeds = payload.get("feeds") if isinstance(payload.get("feeds"), list) else []
    operators_by_id: Dict[str, Dict[str, Any]] = {}
    spec_counts: Counter[str] = Counter()
    authorization_counts: Counter[str] = Counter()
    country_hint_counts: Counter[str] = Counter()
    sample_feeds: List[Dict[str, Any]] = []

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
        if len(sample_feeds) < 6:
            sample_feeds.append(
                {
                    "id": feed_id,
                    "spec": spec,
                    "url": (feed.get("urls") or {}).get("static_current") if isinstance(feed.get("urls"), dict) else None,
                    "authorization": auth_type,
                    "operators": [op.get("name") for op in feed.get("operators") or [] if isinstance(op, dict) and op.get("name")][:3],
                }
            )

    return {
        "feedCount": len(feeds),
        "operatorCount": len(operators_by_id),
        "specCounts": dict(spec_counts),
        "authorizationCounts": dict(authorization_counts),
        "topCountryHints": [{"code": key, "feedCount": value} for key, value in country_hint_counts.most_common(8)],
        "sampleFeeds": sample_feeds,
    }


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


def _aisstream_status() -> Dict[str, Any]:
    api_key = str(os.environ.get("POLYDATA_AISSTREAM_API_KEY") or "").strip()
    if not api_key:
        return {"status": "missing-key", "messageCount": 0, "sourceUrl": AISSTREAM_DOC_URL}
    if str(os.environ.get("POLYDATA_AISSTREAM_SAMPLE_ENABLED", "0")).strip().lower() not in {"1", "true", "yes", "on"}:
        return {"status": "configured", "messageCount": 0, "sourceUrl": AISSTREAM_DOC_URL}
    try:
        import asyncio

        timeout_seconds = max(3, min(int(os.environ.get("POLYDATA_AISSTREAM_SAMPLE_SECONDS", "8") or 8), 20))
        return {**asyncio.run(_sample_aisstream(api_key, timeout_seconds=timeout_seconds)), "sourceUrl": AISSTREAM_DOC_URL}
    except Exception as exc:
        return {"status": "error", "messageCount": 0, "error": exc.__class__.__name__, "sourceUrl": AISSTREAM_DOC_URL}


def _market_links(ctx: dict, query: str) -> List[Dict[str, Any]]:
    search = ctx.get("search_markets")
    if not callable(search):
        return []
    try:
        rows = search(query, limit=3) or []
    except Exception:
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
    airports_text, airports_source = _read_openflights_text(ctx, "airports.dat", OPENFLIGHTS_AIRPORTS_URL)
    routes_text, routes_source = _read_openflights_text(ctx, "routes.dat", OPENFLIGHTS_ROUTES_URL)
    try:
        airlines_text, _ = _read_openflights_text(ctx, "airlines.dat", OPENFLIGHTS_AIRLINES_URL)
    except Exception:
        airlines_text = ""
    airports = _parse_airports(airports_text)
    airlines = _parse_airlines(airlines_text)
    route_stats = _parse_routes(routes_text, airports, airlines)

    transit_url = os.environ.get("POLYDATA_TRANSITLAND_ATLAS_URL", TRANSITLAND_ATLAS_URL)
    transit_payload = json.loads(_http_text(ctx, transit_url, timeout=20))
    transit_stats = _parse_transitland(transit_payload if isinstance(transit_payload, dict) else {})
    ais_status = _aisstream_status()

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
            summary=f"{transit_stats['feedCount']} feeds / {transit_stats['operatorCount']} operators in sampled DMFR catalog.",
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
            summary=f"AISStream status: {ais_status.get('status')}. Configure POLYDATA_AISSTREAM_API_KEY for live vessel sample.",
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
    return {
        "panelId": PANEL_ID,
        "generatedAt": _utc_now_iso(ctx),
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
        "summary": {
            "airports": len({row.get("id") for row in airports.values() if row.get("id")}),
            "routes": route_stats["routeCount"],
            "countries": route_stats["countryCount"],
            "topHub": (route_stats["topHubs"][0].get("iata") or route_stats["topHubs"][0].get("name")) if route_stats["topHubs"] else None,
            "transitFeeds": transit_stats["feedCount"],
            "transitOperators": transit_stats["operatorCount"],
            "aisStatus": ais_status.get("status"),
        },
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
        "summary": {"airports": 0, "routes": 0, "countries": 0, "topHub": None, "transitFeeds": 0, "transitOperators": 0, "aisStatus": "unknown"},
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
