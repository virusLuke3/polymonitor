from __future__ import annotations

import threading
import time
from typing import Any, Dict


_RELATED_CONTENT_CACHE_TTL_SECONDS = 120
_RELATED_CONTENT_CACHE: Dict[tuple[int, int], tuple[float, Dict[str, Any]]] = {}
_RELATED_CONTENT_CACHE_LOCK = threading.Lock()


def get_related_content_payload(ctx: dict, market_id: int, limit: int = 8) -> Dict[str, Any]:
    cache_key = (int(market_id), int(limit))
    now = time.time()
    with _RELATED_CONTENT_CACHE_LOCK:
        cached = _RELATED_CONTENT_CACHE.get(cache_key)
        if cached and now - cached[0] < _RELATED_CONTENT_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["sourceMode"] = f"{payload.get('sourceMode') or 'database'}:cache"
            return payload
    payload = ctx["get_related_content_by_market_id"](market_id, limit=limit)
    with _RELATED_CONTENT_CACHE_LOCK:
        _RELATED_CONTENT_CACHE[cache_key] = (now, payload)
        if len(_RELATED_CONTENT_CACHE) > 256:
            oldest_key = min(_RELATED_CONTENT_CACHE, key=lambda key: _RELATED_CONTENT_CACHE[key][0])
            _RELATED_CONTENT_CACHE.pop(oldest_key, None)
    return payload


def get_latest_content_payload(ctx: dict, limit: int = 8) -> Dict[str, Any]:
    return ctx["get_latest_content_snapshot"](limit=limit)
