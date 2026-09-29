"""Read existing upstream order books; never collect, rebuild or write them."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict

import requests

BOOK_LEVEL_LIMIT = 12


def get_lob_runtime_status() -> dict[str, Any]:
    try:
        with requests.Session() as session:
            session.trust_env = False
            base = os.environ.get("MARKET_DATA_LOB_URL", "http://127.0.0.1:18610").rstrip("/")
            response = session.get(f"{base}/health", timeout=(0.5, 1.5))
            response.raise_for_status()
            return response.json()
    except (requests.RequestException, ValueError):
        return {"source": "market-data", "status": "unavailable"}


@dataclass(frozen=True)
class LobDependencies:
    get_market_by_id: Callable[[int], dict[str, Any] | None]


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    try:
        return _timestamp(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def _live_side(side, token_id: str) -> dict[str, Any]:
    if not isinstance(side, dict) or side.get("tokenId") != token_id:
        raise ValueError("LOB token identity mismatch")
    result = dict(side)
    status = result.get("bookStatus")
    if status not in {"warming", "live", "stale", "unavailable"}:
        raise ValueError("Invalid LOB status")
    if status == "live":
        now = datetime.now(timezone.utc)
        heartbeat = _timestamp(result.get("heartbeatAt"))
        received = _timestamp(result.get("receivedAt"))
        deadline = _timestamp(result.get("staleAfter"))
        if (
            result.get("continuity") is not True
            or not heartbeat
            or not received
            or not deadline
            or not 0 <= (now - heartbeat).total_seconds() <= 20
            or deadline <= now
            or received > heartbeat
        ):
            result["bookStatus"] = "stale"
    return result


def get_runtime_lob_by_token_payload(
    token_id: str, *, no_token_id: str = "", market_title: str = "", market_id: int | None = None
) -> dict[str, Any]:
    token_id, no_token_id = str(token_id or "").strip(), str(no_token_id or "").strip()
    if (
        not token_id.isdecimal()
        or len(token_id) > 100
        or (no_token_id and (not no_token_id.isdecimal() or len(no_token_id) > 100))
    ):
        return {"error": "Invalid token id", "_status": 400}
    envelope = {
        "marketId": market_id,
        "localMarketId": market_id,
        "marketTitle": market_title,
        "tokenMode": True,
        "source": "market-data",
        "runtimeModel": "websocket-live",
    }
    try:
        # One local request for both outcomes; never warm, collect, or write here.
        with requests.Session() as session:
            session.trust_env = False
            base = os.environ.get("MARKET_DATA_LOB_URL", "http://127.0.0.1:18610").rstrip("/")
            response = session.get(f"{base}/book/{token_id}", params={"noTokenId": no_token_id}, timeout=(0.5, 1.5))
            response.raise_for_status()
            payload = response.json()
        if payload.get("source") != "market-data" or payload.get("runtimeModel") != "websocket-live":
            raise ValueError("Unexpected LOB source")
        yes, no = _live_side(payload.get("yes"), token_id), _live_side(payload.get("no"), no_token_id)
        states = {s["bookStatus"] for s in ([yes, no] if no_token_id else [yes])}
        status = next(s for s in ("unavailable", "stale", "warming", "live") if s in states)
        times = [s.get("receivedAt") for s in ([yes, no] if no_token_id else [yes]) if s.get("receivedAt")]
        return {
            **envelope,
            "yes": yes,
            "no": no,
            "bookStatus": status,
            "generatedAt": payload.get("generatedAt"),
            "fetchedAt": min(times) if times else None,
        }
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        logging.getLogger(__name__).warning("Market-data live book unavailable", exc_info=True)

        def empty(token):
            return {"tokenId": token, "bids": [], "asks": [], "bookStatus": "unavailable", "continuity": False}

        return {
            **envelope,
            "yes": empty(token_id),
            "no": empty(no_token_id),
            "bookStatus": "unavailable",
            "fallbackReason": "live-source-unavailable",
        }


def get_runtime_lob_payload(deps: LobDependencies, market_id: int) -> dict[str, Any]:
    market = deps.get_market_by_id(market_id)
    if not market:
        return {"error": "Market not found", "_status": 404}
    return get_runtime_lob_by_token_payload(
        market.get("yes_token_id") or "",
        no_token_id=market.get("no_token_id") or "",
        market_title=market.get("title") or "",
        market_id=market_id,
    )
