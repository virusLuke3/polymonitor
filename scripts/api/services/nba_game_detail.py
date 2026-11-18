"""Game detail snapshots produced by the NBA scoreboard owner."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from requests.exceptions import RequestException

from api.services.seed_recovery import age_seconds


NAMESPACE = "snapshot:sports:nba-game-detail"
RETAIN_SECONDS = 86400


def _phase(event: dict) -> str:
    status = event.get("status") or {}
    return (status.get("type") or {}).get("state", "")


def collect(store: Any, events: list[dict], *, fetched_at: str, fetch_summary) -> int:
    """Preserve the original ESPN objects, timestamps and last successful detail."""
    games = [(str(event["id"]), event) for event in events if str(event.get("id", "")).isdigit()]
    previous = {key: store.get_stale(NAMESPACE, key) or {} for key, _ in games}
    board_time = datetime.fromisoformat(fetched_at.replace("Z", "+00:00")).timestamp()
    due = []
    for key, event in games:
        prior = previous[key]
        phase = _phase(event)
        if (prior.get("retryAt") or 0) > board_time:
            continue
        if phase == "post" and prior.get("summaryPhase") == "post":
            continue
        cadence = 60 if phase == "in" else 600
        if prior.get("attemptPhase") != phase or age_seconds(prior.get("lastAttemptAt"), fetched_at) >= cadence - 2:
            due.append((key, phase))

    def fetch(game: tuple[str, str]) -> tuple[str, dict]:
        key, phase = game
        try:
            summary = fetch_summary(key)
            header = summary.get("header") if isinstance(summary, dict) else None
            if not isinstance(header, dict) or str(header.get("id")) != key:
                raise ValueError("ESPN summary identity mismatch")
            summary_phase = _phase(next(iter(header.get("competitions") or []), {}))
            result = {"summary": summary, "summaryPhase": summary_phase,
                      "summaryFetchedAt": datetime.now(timezone.utc).isoformat(), "summaryError": None, "retryAt": None}
        except (RequestException, ValueError, TypeError, OSError, AttributeError) as exc:
            response = getattr(exc, "response", None)
            result = {"summaryError": type(exc).__name__, "retryAt": None}
            if response is not None and response.status_code == 429:
                wait = response.headers.get("Retry-After", "")
                try:
                    retry_at = (datetime.now(timezone.utc) + timedelta(seconds=int(wait))
                                if wait.isdigit() else parsedate_to_datetime(wait))
                except (TypeError, ValueError, OverflowError):
                    retry_at = datetime.now(timezone.utc) + timedelta(seconds=60)
                result = {"summaryError": "HTTP 429", "retryAt": retry_at.replace(tzinfo=retry_at.tzinfo or timezone.utc).timestamp()}
        return key, {**result, "lastAttemptAt": fetched_at, "attemptPhase": phase}

    with ThreadPoolExecutor(max_workers=4) as executor:
        summaries = dict(executor.map(fetch, due))
    for key, event in games:
        prior = previous[key]
        if key not in summaries and prior.get("scoreboard") == event:
            continue
        record = {**prior, **summaries.get(key, {}), "eventId": key,
                  "scoreboard": event, "scoreboardFetchedAt": fetched_at}
        if store.set(NAMESPACE, key, record, RETAIN_SECONDS, max_entries=48) is False:
            raise RuntimeError("NBA detail snapshot write rejected")
    return sum("summary" in result for result in summaries.values())


def read(store: Any, game_id: str) -> dict:
    record = store.get_stale(NAMESPACE, game_id) if store is not None else None
    now = datetime.now(timezone.utc).isoformat()
    if not isinstance(record, dict) or record.get("eventId") != game_id:
        return {"eventId": game_id, "source": "ESPN", "status": "unavailable"}
    summary_at = record.get("summaryFetchedAt")
    scoreboard_at = record.get("scoreboardFetchedAt")
    summary_age = age_seconds(summary_at, now)
    scoreboard_age = age_seconds(scoreboard_at, now)
    summary = record.get("summary") if 0 <= summary_age <= RETAIN_SECONDS else None
    scoreboard = record.get("scoreboard") if 0 <= scoreboard_age <= RETAIN_SECONDS else None
    phase = _phase(scoreboard or {})
    fresh_for = {"in": 180, "pre": 1200, "post": RETAIN_SECONDS}.get(phase, 180)
    summary_error = record.get("summaryError")
    status = ("ok" if summary and summary_age <= fresh_for and not summary_error
              and (not phase or record.get("summaryPhase") == phase) else
              "stale" if summary else "partial" if scoreboard else "unavailable")
    return {"eventId": game_id, "source": "ESPN", "status": status,
            "scoreboard": scoreboard, "scoreboardFetchedAt": scoreboard_at if scoreboard else None,
            "summary": summary, "summaryFetchedAt": summary_at if summary else None,
            "summaryError": summary_error}
