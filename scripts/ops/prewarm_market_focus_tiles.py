#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import time
import urllib.parse
import urllib.request
from typing import Any


def _json_get(base_url: str, path: str, timeout_seconds: float) -> dict[str, Any]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"Accept": "application/json", "User-Agent": "polydata-focus-prewarm/1.0"},
    )
    with opener.open(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected payload for {path}")
    return payload


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return round(ordered[index], 1)


def prewarm(base_url: str, *, limit: int, workers: int, timeout_seconds: float) -> dict[str, Any]:
    query = urllib.parse.urlencode({"page": 1, "pageSize": limit, "status": "active"})
    catalog_started = time.perf_counter()
    catalog = _json_get(base_url, f"/markets?{query}", timeout_seconds)
    market_ids = [
        int(item["id"])
        for item in (catalog.get("items") or [])[:limit]
        if isinstance(item, dict) and item.get("id") is not None
    ]

    def warm_one(market_id: int) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            payload = _json_get(base_url, f"/markets/{market_id}/focus-tile", timeout_seconds)
            return {
                "marketId": market_id,
                "status": str(payload.get("focusStatus") or "unknown"),
                "latencyMs": round((time.perf_counter() - started) * 1000, 1),
                "error": None,
            }
        except Exception as exc:
            return {
                "marketId": market_id,
                "status": "error",
                "latencyMs": round((time.perf_counter() - started) * 1000, 1),
                "error": str(exc)[:180],
            }

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        for result in executor.map(warm_one, market_ids):
            results.append(result)
    latencies = [float(item["latencyMs"]) for item in results if item.get("status") != "error"]
    counts: dict[str, int] = {}
    for item in results:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {
        "status": "ok" if results and counts.get("error", 0) < len(results) else "error",
        "source": "local-api-focus-tile-prewarm",
        "catalogLatencyMs": round((time.perf_counter() - catalog_started) * 1000, 1),
        "requested": len(market_ids),
        "counts": counts,
        "latencyMs": {
            "median": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 1) if latencies else None,
        },
        "errors": [item for item in results if item.get("error")][:5],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prewarm selection-critical market focus tiles through the local API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18500")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--timeout-seconds", type=float, default=3.0)
    args = parser.parse_args()
    try:
        payload = prewarm(
            args.base_url,
            limit=max(1, min(int(args.limit), 80)),
            workers=max(1, min(int(args.workers), 12)),
            timeout_seconds=max(0.5, min(float(args.timeout_seconds), 15.0)),
        )
    except Exception as exc:
        payload = {"status": "error", "source": "local-api-focus-tile-prewarm", "error": str(exc)[:240]}
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    return 0 if payload.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
