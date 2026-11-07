"""Weather projection of existing committed books; no acquisition or storage."""
from datetime import datetime, timezone, timedelta
import math

RETAINED_SECONDS = 7200


def _time(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (TypeError, ValueError):
        return None


def project_weather_book(payload, token, *, now=None):
    now = now or datetime.now(timezone.utc)
    side = payload.get("yes") or {}
    status = side.get("bookStatus") or payload.get("bookStatus") or "unavailable"
    empty = {"bookStatus": status, "bids": [], "asks": []}
    if side.get("tokenId") != token:
        return {**empty, "bookStatus": "unavailable"}
    received, heartbeat, deadline, observed = (_time(side.get(key)) for key in ("receivedAt", "heartbeatAt", "staleAfter", "observedAt"))
    if side.get("eventAt") and (not _time(side["eventAt"]) or _time(side["eventAt"]) > now):
        return {**empty, "bookStatus": "invalid"}
    live = bool(status == "live" and side.get("continuity") is True and received and heartbeat and deadline
                and 0 <= (now - heartbeat).total_seconds() < 20 and received <= heartbeat and deadline > now)
    snapshot = bool(status == "available" and side.get("upstreamReady") is True and observed and 0 <= (now - observed).total_seconds() < 30)
    event = _time(side.get("eventAt")) or (received if live else None)
    retained = bool(status in {"live", "available", "stale"} and event and 0 <= (now - event).total_seconds() < RETAINED_SECONDS)
    if not (live or snapshot or retained):
        return {**empty, "bookStatus": "stale" if status in {"live", "available", "stale"} else status}
    def price(value):
        try:
            number = float(value)
            return number if math.isfinite(number) and 0 <= number <= 1 else None
        except (TypeError, ValueError):
            return None
    def best(key, explicit, choose):
        if side.get(explicit) is not None:
            return price(side[explicit])
        values = [price(row.get("price")) for row in side.get(key, []) if isinstance(row, dict)]
        return choose((value for value in values if value is not None), default=None)
    bid, ask = best("bids", "bestBid", max), best("asks", "bestAsk", min)
    if any(side.get(key) is not None and price(side[key]) is None for key in ("bestBid", "bestAsk")) or (bid is not None and ask is not None and bid > ask):
        return {**empty, "bookStatus": "invalid"}
    if bid is None and ask is None:
        return {**empty, "bookStatus": "no-book"}
    valid_until = deadline if live else observed + timedelta(seconds=30) if snapshot else event + timedelta(seconds=RETAINED_SECONDS)
    return {"bookStatus": "ok" if live else "snapshot" if snapshot else "retained",
            "priceSource": "clob-book" if live else "clob-snapshot" if snapshot else "previous-book",
            "quoteUpdatedAt": event.isoformat() if event else None,
            "quoteObservedAt": side.get("observedAt"), "quoteStaleAfter": valid_until.isoformat(),
            "bids": [{"price": bid}] if bid is not None else [], "asks": [{"price": ask}] if ask is not None else []}
