"""Existing macro owners share one monotonic acquisition deadline per round."""
from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict

from runtime.seed_meta import redis_key as _redis_key

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

class MacroSourceCache:
    """Source cache policy shared by the CPI, registry and retail collectors."""

    def _get_cached_json(self, namespace: str, cache_key: str) -> Dict[str, Any] | None:
        if self.snapshot_store.backend == "redis":
            return self.snapshot_store.get(namespace, cache_key)
        payload = self.snapshot_store.get(namespace, cache_key)
        if not isinstance(payload, dict):
            payload = self.snapshot_store.get_stale(namespace, cache_key)
        return payload if isinstance(payload, dict) else None

    def _set_cached_json(self, namespace: str, cache_key: str, payload: Dict[str, Any], ttl: int) -> None:
        if self.snapshot_store.backend == "redis":
            if not self.snapshot_store.set(namespace, cache_key, payload, ttl):
                raise RuntimeError("Seed publication rejected")
            return payload
        if self.redis_client is not None:
            try:
                self.redis_client.set(_redis_key(self.redis_prefix, namespace, cache_key), json.dumps(payload, ensure_ascii=True, default=str), ex=ttl)
            except Exception as exc:
                print(f"[macro-source] Redis cache mirror failed: {type(exc).__name__}", file=sys.stderr)
