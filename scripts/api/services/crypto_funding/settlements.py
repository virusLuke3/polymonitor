from __future__ import annotations

import hashlib
import time

from .contracts import FUNDING_PANEL_LIMIT, number, ordered_funding_assets, timestamp
from .providers import bybit_rows, origin

PUBLICATION_GRACE_SECONDS = 30
RETRY_WINDOW_SECONDS = 10 * 60
EVENT_RETENTION_SECONDS = 20 * 60


def fetch_settlement(get, url: str, contract: dict, due_at: int) -> dict | None:
    """Read a confirmed history row for the venue's announced settlement."""
    params = {"symbol": contract["symbol"], "startTime": (due_at - 10) * 1000,
              "endTime": int(min(time.time(), due_at + 120) * 1000), "limit": 3}
    if contract["exchange"] == "Binance":
        rows = get(f"{origin(url)}/fapi/v1/fundingRate", params=params, timeout=8)
        clock = "fundingTime"
    else:
        rows, _, _ = bybit_rows(get(f"{origin(url)}/v5/market/funding/history",
                                    params={**params, "category": "linear"}, timeout=8))
        clock = "fundingRateTimestamp"
    if not isinstance(rows, list):
        raise ValueError("invalid-funding-history")
    matches = []
    for row in rows:
        if not isinstance(row, dict) or row.get("symbol") != contract["symbol"]:
            continue
        settled_at, rate = number(row.get(clock)), number(row.get("fundingRate"))
        if settled_at is None or rate is None or not params["startTime"] <= settled_at <= params["endTime"]:
            continue
        if abs(rate) <= 1:
            matches.append({**contract, "settledAt": int(settled_at), "ratePercent": rate * 100})
    return max(matches, key=lambda item: item["settledAt"], default=None)


def collect(previous: dict, quote_payload: dict, *, urls: dict, get, executor, jobs: dict, now: int) -> dict:
    """Run history reads only after an announced clock, using the existing quote owner."""
    started_at = previous.get("startedAt", now)
    # Retain a boundary through a short quote outage and the ticker rollover.
    plans = {key: dict(value) for key, value in previous.get("plans", {}).items()
             if now - value["lastSeenAt"] <= 1800}
    assets = ordered_funding_assets((quote_payload.get("assets") or [])[:FUNDING_PANEL_LIMIT])
    for asset in assets:
        for quote in asset.get("quotes") or []:
            key = quote["id"]
            announced = timestamp(quote.get("nextFundingTime"))
            if quote.get("acquisitionState") != "ok" or announced is None or announced <= started_at:
                continue
            announced = int(announced)
            plan = plans.get(key)
            elapsed_pending = plan and not plan.get("confirmed") and (
                now - RETRY_WINDOW_SECONDS < plan["dueAt"] <= now + PUBLICATION_GRACE_SECONDS
            )
            if not plan or (not elapsed_pending and plan["dueAt"] != announced):
                plan = {"contract": {field: quote[field] for field in ("id", "asset", "symbol", "exchange")},
                        "dueAt": announced, "retryAt": announced + PUBLICATION_GRACE_SECONDS}
                plans[key] = plan
            plan["lastSeenAt"] = now

    confirmed = {}
    for key, (due_at, future) in list(jobs.items()):
        if not future.done():
            continue
        del jobs[key]
        plan = plans.get(key)
        if not plan or plan["dueAt"] != due_at or now - due_at >= EVENT_RETENTION_SECONDS:
            continue
        try:
            row = future.result()
        except Exception as exc:
            row = None
            response = getattr(exc, "response", None)
            retry_after = number(response.headers.get("Retry-After")) if response is not None else None
            plan["retryAt"] = now + max(60, int(retry_after or 0))
            plan["error"] = type(exc).__name__
        else:
            plan["retryAt"] = now + 60
            plan.pop("error", None)
        if row is not None:
            plan["confirmed"] = True
            confirmed.setdefault(due_at, []).append(row)

    for key, plan in plans.items():
        due_at = plan["dueAt"]
        if key in jobs or plan.get("confirmed") or not (started_at < due_at and plan["retryAt"] <= now < due_at + RETRY_WINDOW_SECONDS):
            continue
        contract = plan["contract"]
        url = urls.get(contract["exchange"])
        if url:
            jobs[key] = due_at, executor.submit(fetch_settlement, get, url, contract, due_at)

    batches = [batch for batch in previous.get("batches", []) if now - batch["settledAt"] / 1000 <= EVENT_RETENTION_SECONDS]
    for due_at, rows in sorted(confirmed.items()):
        identity = ",".join(sorted(f"{row['id']}:{row['settledAt']}" for row in rows))
        batches.append({"id": hashlib.sha256(identity.encode()).hexdigest()[:24], "dueAt": due_at,
                        "settledAt": max(row["settledAt"] for row in rows), "rows": rows})
    return {"startedAt": started_at, "plans": plans, "batches": batches}
