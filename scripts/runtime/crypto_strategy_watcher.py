#!/usr/bin/env python3
"""Publish shared crypto strategy observations; API requests never collect."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data_sources import source_value

from api.config import load_api_settings
from api.clients.http_client import http_json_get
from api.context import RuntimeResources
from api.services.crypto_strategy import providers
from api.services.crypto_strategy.cadence import SourceCadence
from api.services.crypto_strategy.contracts import number
from api.services.crypto_strategy.store import Store, database_path


def get(context, url, params=None):
    slow = urlsplit(url).path.endswith(("/kline", "/open-interest", "/funding/history",
                                       "/get_instruments", "/get_book_summary_by_currency"))
    deadline = context.get("crypto_deadline")
    remaining = deadline - time.monotonic() if deadline is not None else 90
    if remaining <= 0:
        raise requests.exceptions.Timeout("crypto collection budget exhausted")
    return http_json_get(context, url, params=params, timeout=min(45 if slow else 12, remaining),
                         headers={"Accept": "application/json", "User-Agent": "polymonitor-crypto-strategy/1"},
                         max_response_bytes=8_000_000, retry_attempts=4 if slow else 1, retry_deadline=deadline)


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


class SlowSources:
    """Bounded work owned by this collector; slow reads cannot delay fast publication."""
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="crypto-history")
        self.jobs = {}

    def reap(self, cadence):
        for key, future in list(self.jobs.items()):
            if future.done():
                try:
                    cadence.entries.update(future.result())
                except Exception as exc:
                    print("crypto slow source failed: " + type(exc).__name__, file=sys.stderr, flush=True)
                del self.jobs[key]

    def schedule(self, cadence, base, now):
        self.reap(cadence)
        specs = [(asset, [(base, asset, key) for key in ("spotBars", "linearBars", "oiHistory", "fundingHistory")])
                 for asset in providers.ASSETS]
        specs += [("options:" + asset, [(providers.DERIBIT_BASE, asset, "options")]) for asset in ("BTC", "ETH")]
        for name, keys in specs:
            keys = [cadence.key(key) for key in keys]
            if name in self.jobs or all(cadence.entries.get(key, {}).get("retryAt", 0) > now for key in keys):
                continue
            entries = {key: cadence.entries[key] for key in keys if key in cadence.entries}
            self.jobs[name] = self.pool.submit(self._refresh, name, base, entries)

    @staticmethod
    def _refresh(name, base, entries):
        cadence = SourceCadence(entries)
        now = int(time.time() * 1000)
        with closing(RuntimeResources()) as resources:
            fetch = partial(get, {"requests": requests, "_resources": resources, "crypto_deadline": time.monotonic() + 90})
            if name.startswith("options:"):
                asset = name.split(":")[1]
                try:
                    cadence.read((providers.DERIBIT_BASE, asset, "options"), now, 300_000,
                                 lambda: providers.options(fetch, asset, now))
                except OSError:
                    pass  # Failed state, retry clock and bounded last-good still publish.
            else:
                providers.venue_asset(fetch, base, name, now, cadence, history_only=True)
        return cadence.entries

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)


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
    cadence = SourceCadence(store.source_entries())
    base = source_value('POLYDATA_CRYPTO_STRATEGY_BYBIT')
    slow_sources = SlowSources() if args.watch else None
    while True:
        start = time.monotonic()
        try:
            now = int(time.time() * 1000)
            if slow_sources:
                slow_sources.schedule(cadence, base, now)
            # collect() owns a finite thread pool per cycle. Close its pooled
            # HTTP sessions with that cycle so retired threads cannot leak them.
            with closing(RuntimeResources()) as resources:
                source_get = partial(get, {"requests": requests, "_resources": resources, "crypto_deadline": start + (30 if slow_sources else 90)})
                payload = providers.collect(source_get, bybit_base=base, reference_url="", now=now, cadence=cadence,
                                            fast_only=slow_sources is not None)
            payload = enrich(payload, store, now, os.environ.get("POLYDATA_CRYPTO_EXCHANGE_FLOW_FILE"))
            store.publish(payload, now, cadence.entries)
            print(json.dumps({"generatedAt": payload["generatedAt"], "assets": {k: v.get("status") for k, v in payload["assets"].items()},
                              "assetErrors": {k: v.get("errors") for k, v in payload["assets"].items() if v.get("errors")},
                              "options": {k: {"expiries": len(v.get("expiries", [])), "observedAt": v.get("observedAt"),
                                              "error": v.get("error"), "sourceState": v.get("sourceState")}
                                          for k, v in payload["options"].items()}}), flush=True)
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
