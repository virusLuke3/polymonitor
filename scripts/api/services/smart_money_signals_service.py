"""Publish the Smart Money worktree's matched trade cards to the public seed store."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess

from runtime.seed_meta import publish_snapshot, utc_now_iso

NAMESPACE = "snapshot:signals:smart-money"
CACHE_KEY = "matched-trades-v2"
LIMIT = 12
FRESH_SECONDS = 900


def run_source(*args, include_runtime=False, input_data=None):
    root = Path(os.environ["POLYMONITOR_SMART_MONEY_WORKTREE"]).resolve(strict=True)
    python = Path(os.environ["POLYMONITOR_SMART_MONEY_PYTHON"]).resolve(strict=True)
    source_env = Path(os.environ["POLYMONITOR_SMART_MONEY_ENV_FILE"]).resolve(strict=True)
    pythonpath = str(root / "src")
    if include_runtime:
        pythonpath += os.pathsep + str(Path(__file__).resolve().parents[2])
    result = subprocess.run(
        [str(python), *args], cwd=root,
        env={"PYTHONPATH": pythonpath, "PYTHONDONTWRITEBYTECODE": "1", "SMART_MONEY_ENV_FILE": str(source_env)},
        input=input_data, capture_output=True, text=True, timeout=20, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Smart Money signal export failed (exit {result.returncode})")
    return result.stdout


def public_card(row):
    reasons = [
        f"{sector} · {bucket['id']} {bucket['name']}"
        for selection in row["selection"]
        for sector, buckets in selection.get("buckets", {}).items()
        for bucket in buckets
    ]
    return {
        "id": row["signal_id"], "title": row["title"], "eventSlug": row["event_slug"],
        "outcome": row["outcome"], "side": row["side"],
        "amountUsdc": row["amount_usdc"], "averagePrice": row["average_price"],
        "fragments": row["fragments"], "tradedAt": row["last_trade_at"],
        "tags": list(dict.fromkeys(reasons)),
    }


def collect(store):
    with store.fetch_lock(NAMESPACE, CACHE_KEY, timeout=0):
        items = [public_card(json.loads(line)) for line in
                 run_source("-m", "smart_money", "signals", "--limit", str(LIMIT)).splitlines()]
        items.sort(key=lambda item: (item["tradedAt"], item["id"]), reverse=True)
        previous = store.get_stale(NAMESPACE, CACHE_KEY)
        if not previous or previous.get("items") != items:
            publish_snapshot(
                snapshot_store=store, namespace=NAMESPACE, cache_key=CACHE_KEY,
                payload={"source": CACHE_KEY, "generatedAt": utc_now_iso(),
                         "sourceObservedAt": items[0]["tradedAt"] if items else None, "items": items},
                ttl_seconds=FRESH_SECONDS,
            )
        return {"status": "ok" if items else "empty", "recordCount": len(items)}


def read_snapshot(store, *, limit):
    payload = store.get_stale(NAMESPACE, CACHE_KEY) if store is not None else None
    if payload is None:
        return {"source": CACHE_KEY, "status": "warming", "items": []}
    last_trade = payload["sourceObservedAt"]
    if last_trade:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_trade)).total_seconds()
        status = "ok" if 0 <= age <= FRESH_SECONDS else "stale"
    else:
        status = "empty" if store.get(NAMESPACE, CACHE_KEY) is not None else "stale"
    return {**payload, "status": status, "items": payload["items"][:limit]}
