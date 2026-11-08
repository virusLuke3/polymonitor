"""Existing macro owners share one monotonic acquisition deadline per round."""
from __future__ import annotations

import time

from api.clients.source_transport import read_response_bytes, read_with_retry


def start_round(owner, setting: str, default: int) -> None:
    owner.collection_started = time.monotonic()
    owner.collection_budget = max(1, int(getattr(owner.settings, setting, default) or default))
    owner.collection_deadline = owner.collection_started + owner.collection_budget


def round_evidence(owner) -> dict:
    started = getattr(owner, "collection_started", None)
    if started is None:
        return {}
    return {"budgetSeconds": owner.collection_budget,
            "elapsedSeconds": round(time.monotonic() - started, 3),
            "exhausted": time.monotonic() >= owner.collection_deadline,
            "scope": "whole-owner-acquisition", "fullAttemptsOnly": True}


def read_text(owner, url: str, *, timeout=15, **kwargs) -> str:
    deadline = getattr(owner, "collection_deadline", None)
    body = read_with_retry(owner.requests, url,
        lambda response: read_response_bytes(response, 2 * 1024 * 1024, deadline=deadline),
        attempts=2, deadline=deadline, timeout=timeout, stream=True,
        require_full_attempt=True, **kwargs)
    return body.decode("utf-8-sig")
