#!/usr/bin/env python3
"""Publish shared crypto strategy observations; API requests never collect."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.config import load_api_settings
from api.services.crypto_strategy import providers
from api.services.crypto_strategy.contracts import number
from api.services.crypto_strategy.store import Store, database_path


def get(url, params=None):
    if params:
        url += "?" + urlencode(params)
    with urlopen(Request(url, headers={"Accept": "application/json", "User-Agent": "polymonitor-crypto-strategy/1"}), timeout=5) as response:
        raw = response.read(8000001)
        if len(raw) > 8000000:
            raise ValueError("SOURCE_RESPONSE_TOO_LARGE")
        return json.loads(raw)


def enrich(data, store, now, flow_file=None):
    for asset, row in data["assets"].items():
        store.sample("basis:" + asset, now, row.get("basisBps"))
        row["basisHistory"] = store.history("basis:" + asset, now - 86400000)
    for row in data["stablecoins"]:
        key = "peg:" + row["asset"] + ":" + row["source"]
        observed = int(datetime.fromisoformat(row["receivedAt"]).timestamp()*1000) if row.get("receivedAt") else now
        store.sample(key, observed, row.get("deviationBps"))
        row["history"] = store.history(key, now - 86400000)
        # Duration is bounded by continuous observed samples, not extrapolated.
        streak, previous = [], observed
        for point in reversed(row["history"]):
            if abs(point["v"]) < 20 or previous - point["t"] > 90000:
                break
            streak.append(point)
            previous = point["t"]
        row["observedStressSeconds"] = (observed - streak[-1]["t"]) / 1000 if streak and row.get("price") else None
        row["stressThresholdBps"] = 20
    for asset, ref in data["references"].items():
        if not isinstance(ref, dict):
            continue
        market = ref.get("market") or {}
        for quote in ref.get("quotes", {}).values():
            # Receipt-time observations, scoped to exact condition and outcome.
            key = "pm:" + str(market.get("condition_id")) + ":" + quote["token"]
            store.sample(key, number(quote.get("receivedAt")), (quote["bid"] + quote["ask"]) / 2)
            quote["history"] = store.history(key, market.get("starts_at_ms", now))
    if flow_file:
        try:
            raw = json.loads(Path(flow_file).read_text())
            if raw.get("schemaVersion") == 1 and raw.get("mode") == "historical" and isinstance(raw.get("rows"), list):
                data["inflows"] = {**raw, "rows": raw["rows"][-400:], "liveAvailable": False}
        except (OSError, ValueError):
            data["inflows"]["reason"] = "HISTORICAL_FLOW_READ_FAILED"
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--db")
    parser.add_argument("--interval", type=int, default=30)
    args = parser.parse_args()
    settings = load_api_settings()
    path = args.db or database_path(settings.snapshot_sqlite_path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    lock = open(path + ".writer.lock", "a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    store = Store(path)
    base = os.environ.get("POLYDATA_CRYPTO_STRATEGY_BYBIT", "https://api.bybit.com")
    while True:
        start = time.monotonic()
        try:
            now = int(time.time() * 1000)
            payload = providers.collect(get, bybit_base=base, reference_url="", now=now)
            payload = enrich(payload, store, now, os.environ.get("POLYDATA_CRYPTO_EXCHANGE_FLOW_FILE"))
            store.publish(payload, now)
            print(json.dumps({"generatedAt": payload["generatedAt"], "assets": {k: v.get("status") for k, v in payload["assets"].items()}, "options": {k: len(v.get("expiries", [])) for k,v in payload["options"].items()}}), flush=True)
        except Exception as exc:
            store.conn.rollback()
            print("crypto-strategy cycle failed: " + type(exc).__name__, file=sys.stderr, flush=True)
            if not args.watch:
                raise
        if not args.watch:
            break
        time.sleep(max(1, max(30, args.interval) - (time.monotonic() - start)))


if __name__ == "__main__":
    main()
