from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from api.config import PROJECT_ROOT


PANEL_ID = "market-tv-wire"
MARKET_TV_WIRE_SNAPSHOT_NAMESPACE = "snapshot:content:market-tv-wire"
MARKET_TV_WIRE_CACHE_KEY = "panel-v1"
DEFAULT_MARKET_TV_WIRE_LIMIT = 24
MARKET_TV_WIRE_TTL_SECONDS = 900
MARKET_TV_WIRE_SEED_ITEM_LIMIT = 240
MANIFEST_PATH = PROJECT_ROOT / "scripts" / "data" / "live_video_sources.json"

CATEGORY_ORDER = ("macro", "geo", "weather", "sports", "crypto", "news", "other")
CATEGORY_LABELS = {
    "macro": "Macro",
    "geo": "Geo",
    "weather": "Weather",
    "sports": "Sports",
    "crypto": "Crypto",
    "news": "News",
    "other": "Other",
}
CATEGORY_BASE_SCORE = {
    "macro": 92,
    "geo": 88,
    "weather": 84,
    "sports": 80,
    "crypto": 78,
    "news": 74,
    "other": 60,
}
IPTV_CATEGORY_FEEDS = (
    ("news", "https://iptv-org.github.io/iptv/categories/news.m3u"),
    ("macro", "https://iptv-org.github.io/iptv/categories/business.m3u"),
    ("sports", "https://iptv-org.github.io/iptv/categories/sports.m3u"),
    ("weather", "https://iptv-org.github.io/iptv/categories/weather.m3u"),
)
ALLOWED_CATEGORIES = set(CATEGORY_ORDER)
ALLOWED_SOURCE_TYPES = {"hls", "youtube", "external", "timelapse"}
ALLOWED_SOURCE_ROLES = {"channel", "visual"}
NOISE_TERMS = ("xxx", "adult", "shopping", "religion", "music", "kids")
EXTINF_ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')
SLUG_RE = re.compile(r"[^a-z0-9]+")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_now_iso(ctx: dict | None = None) -> str:
    if ctx:
        now = ctx.get("utc_now_iso")
        if callable(now):
            return now()
    return utc_now_iso()


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = SLUG_RE.sub("-", text).strip("-")
    return text or "source"


def _string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    output = []
    for item in value:
        text = _string(item)
        if text:
            output.append(text)
    return output


def _score_for(category: str, *, curated: bool, source_type: str, status: str, market_tags: List[str]) -> int:
    score = CATEGORY_BASE_SCORE.get(category, CATEGORY_BASE_SCORE["other"])
    if curated:
        score += 8
    if source_type == "hls":
        score += 3
    elif source_type == "youtube":
        score += 1
    if status == "not_24_7":
        score -= 14
    elif status in {"blocked", "failed"}:
        score -= 24
    elif status == "unknown":
        score -= 4
    if any(tag in {"fed", "rates", "war", "hurricane", "bitcoin", "nba", "elections"} for tag in market_tags):
        score += 2
    return max(0, min(100, int(score)))


def _status_for(source_type: str, item: Dict[str, Any]) -> str:
    explicit = str(item.get("status") or "").strip().lower()
    if explicit in {"ready", "stale", "not_24_7", "blocked", "failed", "unknown"}:
        return explicit
    if item.get("not24x7"):
        return "not_24_7"
    if source_type in {"external", "youtube"}:
        return "ready"
    if source_type == "hls" and item.get("hlsUrl"):
        return "ready"
    return "unknown"


def _availability(item: Dict[str, Any]) -> str:
    value = str(item.get("availability") or "").strip().lower()
    if value in {"public", "geo_limited", "unknown"}:
        return value
    risk = str(item.get("risk") or "").lower()
    if "region" in risk or "geo" in risk or "paywall" in risk or "provider" in risk:
        return "geo_limited"
    return "public"


def _normalize_category(value: Any) -> str:
    category = str(value or "other").strip().lower()
    return category if category in ALLOWED_CATEGORIES else "other"


def _normalize_source_type(value: Any) -> str:
    source_type = str(value or "external").strip().lower()
    return source_type if source_type in ALLOWED_SOURCE_TYPES else "external"


def _normalize_source_role(value: Any) -> str:
    source_role = str(value or "channel").strip().lower()
    return source_role if source_role in ALLOWED_SOURCE_ROLES else "channel"


def normalize_source_item(raw: Dict[str, Any], *, generated_at: str, curated: bool) -> Optional[Dict[str, Any]]:
    display_name = _string(raw.get("displayName") or raw.get("name"))
    if not display_name:
        return None
    category = _normalize_category(raw.get("category"))
    source_type = _normalize_source_type(raw.get("sourceType"))
    source_role = _normalize_source_role(raw.get("sourceRole"))
    hls_url = _string(raw.get("hlsUrl"))
    external_url = _string(raw.get("externalUrl"))
    youtube_handle = _string(raw.get("youtubeHandle"))
    fallback_video_id = _string(raw.get("fallbackVideoId"))
    if source_type == "hls" and not hls_url:
        source_type = "external" if external_url else "hls"
    if source_type == "youtube" and not (external_url or youtube_handle or fallback_video_id):
        return None
    if source_type == "external" and not external_url:
        external_url = hls_url
    source_url = _string(raw.get("sourceUrl") or external_url or hls_url)
    if not source_url:
        return None
    market_tags = [tag.lower() for tag in _string_list(raw.get("marketTags"))]
    if curated and not market_tags:
        return None
    status = _status_for(source_type, raw)
    source_name = _string(raw.get("sourceName")) or ("curated" if curated else "iptv-org")
    item_id = _string(raw.get("id")) or f"{source_name}-{display_name}"
    item = {
        "id": _slug(item_id),
        "name": _string(raw.get("name") or display_name) or display_name,
        "displayName": display_name,
        "category": category,
        "sourceRole": source_role,
        "sourceType": source_type,
        "region": _string(raw.get("region")),
        "country": _string(raw.get("country")),
        "language": _string(raw.get("language")),
        "hlsUrl": hls_url,
        "youtubeHandle": youtube_handle,
        "fallbackVideoId": fallback_video_id,
        "externalUrl": external_url or source_url,
        "quality": _string(raw.get("quality")),
        "status": status,
        "availability": _availability(raw),
        "sourceName": source_name,
        "sourceUrl": source_url,
        "marketTags": market_tags,
        "matchedTerms": _string_list(raw.get("matchedTerms")) or market_tags[:4],
        "marketUseCase": _string(raw.get("marketUseCase")) or "Live video context for market-moving events.",
        "relevanceScore": 0,
        "lastCheckedAt": _string(raw.get("lastCheckedAt")) or generated_at,
        "failureReason": _string(raw.get("failureReason")),
        "curated": bool(curated),
    }
    item["relevanceScore"] = _score_for(category, curated=curated, source_type=source_type, status=status, market_tags=market_tags)
    return item


def _manifest_path() -> Path:
    raw = os.environ.get("POLYDATA_MARKET_TV_SOURCE_MANIFEST")
    return Path(raw).expanduser() if raw else MANIFEST_PATH


def load_manifest_items(path: Path | None = None) -> List[Dict[str, Any]]:
    manifest_path = path or _manifest_path()
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("live video source manifest must be a list")
    return [item for item in raw if isinstance(item, dict)]


def _parse_extinf(line: str) -> Dict[str, str]:
    attrs = {match.group(1): match.group(2) for match in EXTINF_ATTR_RE.finditer(line)}
    if "," in line:
        attrs["name"] = line.rsplit(",", 1)[-1].strip()
    return attrs


def parse_m3u_playlist(text: str, *, category: str, source_url: str, generated_at: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    pending: Dict[str, str] | None = None
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            pending = _parse_extinf(line)
            continue
        if line.startswith("#"):
            continue
        if not pending:
            continue
        stream_url = line
        pending_attrs = pending
        pending = None
        name = _string(pending_attrs.get("name") or pending_attrs.get("tvg-name") or pending_attrs.get("tvg-id"))
        if not name:
            continue
        lower_name = name.lower()
        if any(term in lower_name for term in NOISE_TERMS):
            continue
        parsed = urlparse(stream_url)
        if parsed.scheme != "https":
            continue
        is_hls = ".m3u8" in parsed.path.lower() or ".m3u8" in stream_url.lower()
        if not is_hls:
            continue
        not_24_7 = "[not 24/7]" in lower_name
        clean_name = name.replace("[Not 24/7]", "").replace("[not 24/7]", "").strip()
        country = _string(pending_attrs.get("tvg-country") or pending_attrs.get("country"))
        language = _string(pending_attrs.get("tvg-language") or pending_attrs.get("language"))
        raw_item = {
            "id": f"iptv-{category}-{pending_attrs.get('tvg-id') or clean_name}",
            "displayName": clean_name,
            "category": category,
            "sourceRole": "channel",
            "sourceType": "hls",
            "country": country,
            "language": language,
            "hlsUrl": stream_url,
            "externalUrl": stream_url,
            "sourceName": "iptv-org",
            "sourceUrl": source_url,
            "quality": _string(pending_attrs.get("height") or pending_attrs.get("quality")),
            "status": "not_24_7" if not_24_7 else "ready",
            "availability": "unknown",
            "marketTags": [category, "live", "video", "iptv"],
            "matchedTerms": [category, "iptv"],
            "marketUseCase": f"Candidate {CATEGORY_LABELS.get(category, category)} live source discovered from iptv-org.",
            "lastCheckedAt": generated_at,
        }
        item = normalize_source_item(raw_item, generated_at=generated_at, curated=False)
        if item:
            items.append(item)
    return items


def _http_text_get(ctx: dict, url: str) -> str:
    getter = ctx.get("http_text_get")
    if callable(getter):
        return getter(url, timeout=10, headers={"User-Agent": "polydata-market-tv-wire/1.0"})
    requests_module = ctx.get("requests")
    if requests_module is None:
        raise RuntimeError("http_text_get unavailable")
    response = requests_module.get(url, timeout=10, headers={"User-Agent": "polydata-market-tv-wire/1.0"})
    response.raise_for_status()
    return response.text


def _dedupe(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    output: List[Dict[str, Any]] = []
    for item in items:
        key = str(item.get("hlsUrl") or item.get("externalUrl") or item.get("id") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    regions = {str(item.get("region") or item.get("country") or "").strip() for item in items if item.get("region") or item.get("country")}
    return {
        "total": len(items),
        "liveReady": sum(1 for item in items if item.get("status") == "ready"),
        "marketMatched": sum(1 for item in items if item.get("relevanceScore", 0) >= 80),
        "regions": len(regions),
        "staleCount": sum(1 for item in items if item.get("status") in {"stale", "not_24_7", "unknown"}),
        "blockedCount": sum(1 for item in items if item.get("status") in {"blocked", "failed"}),
    }


def _categories(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts = {category: 0 for category in CATEGORY_ORDER}
    for item in items:
        category = _normalize_category(item.get("category"))
        counts[category] = counts.get(category, 0) + 1
    return [{"id": category, "label": CATEGORY_LABELS[category], "count": counts.get(category, 0)} for category in CATEGORY_ORDER if counts.get(category, 0)]


def _empty_payload(ctx: dict | None = None, *, status: str = "warming", cache_mode: str = "warming") -> Dict[str, Any]:
    now = _utc_now_iso(ctx)
    return {
        "generatedAt": now,
        "status": status,
        "cacheMode": cache_mode,
        "source": "market-tv-wire-seed",
        "sourceUrl": str(_manifest_path()),
        "summary": _summary([]),
        "categories": [],
        "sources": {},
        "items": [],
        "errors": [],
    }


def build_market_tv_wire_payload(ctx: dict, *, include_iptv: bool = True) -> Dict[str, Any]:
    generated_at = _utc_now_iso(ctx)
    errors: List[str] = []
    source_states: Dict[str, Any] = {}
    items: List[Dict[str, Any]] = []
    manifest_items: List[Dict[str, Any]] = []
    try:
        for raw in load_manifest_items():
            item = normalize_source_item(raw, generated_at=generated_at, curated=True)
            if item:
                manifest_items.append(item)
        source_states["manifest"] = {"status": "ok", "count": len(manifest_items), "lastSuccessAt": generated_at}
        items.extend(manifest_items)
    except Exception as exc:
        errors.append(f"manifest: {exc}")
        source_states["manifest"] = {"status": "error", "count": 0, "error": str(exc)}

    if include_iptv:
        iptv_count = 0
        iptv_errors = 0
        for category, feed_url in IPTV_CATEGORY_FEEDS:
            try:
                text = _http_text_get(ctx, feed_url)
                parsed = parse_m3u_playlist(text, category=category, source_url=feed_url, generated_at=generated_at)
                iptv_count += len(parsed)
                items.extend(parsed)
            except Exception as exc:
                iptv_errors += 1
                errors.append(f"iptv:{category}: {exc}")
        source_states["iptvOrg"] = {
            "status": "ok" if iptv_errors == 0 else ("degraded" if iptv_count else "error"),
            "count": iptv_count,
            "lastSuccessAt": generated_at if iptv_count else None,
            "error": "; ".join(errors[-iptv_errors:]) if iptv_errors else None,
        }

    items = _dedupe(items)
    items.sort(
        key=lambda item: (
            int(item.get("relevanceScore") or 0),
            1 if item.get("status") == "ready" else 0,
            1 if item.get("curated") else 0,
        ),
        reverse=True,
    )
    seed_limit = max(24, int(os.environ.get("POLYDATA_MARKET_TV_WIRE_SEED_LIMIT", MARKET_TV_WIRE_SEED_ITEM_LIMIT)))
    items = items[:seed_limit]
    status = "ok" if items and not errors else ("degraded" if items else "empty")
    return {
        "generatedAt": generated_at,
        "status": status,
        "cacheMode": "live-build",
        "source": "market-tv-wire-seed",
        "sourceUrl": str(_manifest_path()),
        "summary": _summary(items),
        "categories": _categories(items),
        "sources": source_states,
        "items": items,
        "errors": errors[:8],
    }


def _requested_category(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw or raw == "all":
        return None
    return raw if raw in CATEGORY_LABELS else None


def normalize_market_tv_wire_payload(payload: Any, *, ctx: dict | None = None, limit: int = DEFAULT_MARKET_TV_WIRE_LIMIT, category: str | None = None) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_payload(ctx, status="invalid", cache_mode="invalid")
    result = json.loads(json.dumps(payload, ensure_ascii=True, default=str))
    raw_items = result.get("items") if isinstance(result.get("items"), list) else []
    items = [item for item in raw_items if isinstance(item, dict)]
    items.sort(
        key=lambda item: (
            int(item.get("relevanceScore") or 0),
            1 if item.get("status") == "ready" else 0,
            1 if item.get("curated") else 0,
        ),
        reverse=True,
    )
    requested_category = _requested_category(category)
    selected_items = [
        item for item in items
        if not requested_category or _normalize_category(item.get("category")) == requested_category
    ]
    max_items = max(1, min(int(limit or DEFAULT_MARKET_TV_WIRE_LIMIT), 80))
    result["items"] = selected_items[:max_items]
    result["summary"] = result.get("summary") if isinstance(result.get("summary"), dict) else _summary(items)
    result["categories"] = result.get("categories") if isinstance(result.get("categories"), list) else _categories(items)
    result["sources"] = result.get("sources") if isinstance(result.get("sources"), dict) else {}
    result["errors"] = result.get("errors") if isinstance(result.get("errors"), list) else []
    result["generatedAt"] = str(result.get("generatedAt") or _utc_now_iso(ctx))
    result["status"] = str(result.get("status") or ("ok" if items else "warming"))
    result["cacheMode"] = str(result.get("cacheMode") or "seeded")
    result["source"] = str(result.get("source") or "market-tv-wire-seed")
    result["sourceUrl"] = str(result.get("sourceUrl") or _manifest_path())
    result["selection"] = {
        "category": requested_category or "all",
        "total": len(selected_items),
        "returned": len(result["items"]),
        "limit": max_items,
        "truncated": len(selected_items) > max_items,
    }
    return result


def _with_mode(payload: Dict[str, Any], mode: str) -> Dict[str, Any]:
    status = str(payload.get("status") or "ok")
    if "stale" in mode and status == "ok":
        status = "degraded"
    return {**payload, "cacheMode": mode, "status": status}


def _read_seeded(ctx: dict) -> Optional[Dict[str, Any]]:
    reader = ctx.get("get_cached_json")
    if callable(reader):
        payload = reader(MARKET_TV_WIRE_SNAPSHOT_NAMESPACE, MARKET_TV_WIRE_CACHE_KEY)
        if isinstance(payload, dict):
            return _with_mode(payload, "seeded")
    store = ctx.get("SNAPSHOT_STORE")
    if store is not None:
        payload = store.get(MARKET_TV_WIRE_SNAPSHOT_NAMESPACE, MARKET_TV_WIRE_CACHE_KEY)
        if isinstance(payload, dict):
            return _with_mode(payload, "seeded")
        stale = store.get_stale(MARKET_TV_WIRE_SNAPSHOT_NAMESPACE, MARKET_TV_WIRE_CACHE_KEY)
        if isinstance(stale, dict):
            return _with_mode(stale, "stale")
    return None


def get_market_tv_wire_snapshot(ctx: dict, limit: int = DEFAULT_MARKET_TV_WIRE_LIMIT, *, category: str | None = None, allow_live_build: bool = False) -> Dict[str, Any]:
    seeded = _read_seeded(ctx)
    if seeded is not None:
        return normalize_market_tv_wire_payload(seeded, ctx=ctx, limit=limit, category=category)
    if not allow_live_build:
        return normalize_market_tv_wire_payload(_empty_payload(ctx, status="warming", cache_mode="warming"), ctx=ctx, limit=limit, category=category)
    payload = build_market_tv_wire_payload(ctx)
    if payload.get("items"):
        ttl = max(60, int(getattr(ctx.get("SETTINGS"), "market_tv_wire_ttl_seconds", MARKET_TV_WIRE_TTL_SECONDS) or MARKET_TV_WIRE_TTL_SECONDS))
        writer = ctx.get("set_cached_json")
        if callable(writer):
            writer(MARKET_TV_WIRE_SNAPSHOT_NAMESPACE, MARKET_TV_WIRE_CACHE_KEY, payload, ttl)
        store = ctx.get("SNAPSHOT_STORE")
        if store is not None:
            store.set(MARKET_TV_WIRE_SNAPSHOT_NAMESPACE, MARKET_TV_WIRE_CACHE_KEY, payload, ttl)
    return normalize_market_tv_wire_payload(payload, ctx=ctx, limit=limit, category=category)
