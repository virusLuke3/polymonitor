#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helpers for watcher seed metadata stored in Redis + SQLite snapshot."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional


SEED_META_TTL_SECONDS = 7 * 24 * 60 * 60
_logger = logging.getLogger(__name__)


class SnapshotPublicationError(RuntimeError):
    """The authoritative snapshot was not accepted by its store."""


def publish_snapshot(*, snapshot_store: Any, namespace: str, cache_key: str,
                     payload: Any, ttl_seconds: int, redis_client: Any = None,
                     redis_cache_key: str = "") -> None:
    """Confirm SQLite before mirroring; an optional mirror cannot fail publication."""
    try:
        if snapshot_store.set(namespace, cache_key, payload, ttl_seconds) is False:
            raise SnapshotPublicationError("SQLite snapshot write was not accepted")
    except SnapshotPublicationError:
        raise
    except Exception as exc:
        raise SnapshotPublicationError(f"SQLite snapshot write failed: {type(exc).__name__}") from exc
    if redis_client is not None:
        try:
            accepted = redis_client.set(redis_cache_key, json.dumps(payload, ensure_ascii=True, default=str), ex=ttl_seconds)
            if accepted is False:
                _logger.warning("Redis snapshot mirror rejected namespace=%s", namespace)
        except Exception as exc:
            _logger.warning("Redis snapshot mirror failed namespace=%s error_type=%s", namespace, type(exc).__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def redis_key(prefix: str, namespace: str, cache_key: str) -> str:
    return f"{str(prefix or '')}{namespace}:{cache_key}"


def retained_snapshot(previous: Dict[str, Any], *, sources: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Retain data clocks, but never republish a failed refresh as healthy."""
    return {**previous, "status": "stale", "cacheMode": "stale-seed",
            "lastAttemptAt": utc_now_iso(), "sources": sources or {"refresh": "error"}}


def collection_delay(interval: int, failures: int, elapsed: float) -> float:
    """Normal cadence is start-to-start; failed slow feeds recover with backoff."""
    target = interval if failures == 0 else min(interval, 1800, 300 * 2 ** min(failures - 1, 3))
    return max(30.0, target - elapsed)


class SeedMetaStore:
    def __init__(self, *, redis_client: Any, redis_prefix: str, snapshot_store: Any) -> None:
        self.redis_client = redis_client
        self.redis_prefix = str(redis_prefix or "")
        self.snapshot_store = snapshot_store

    def _redis_key(self, namespace: str, cache_key: str) -> str:
        return redis_key(self.redis_prefix, namespace, cache_key)

    def load(self, namespace: str, cache_key: str) -> Optional[Dict[str, Any]]:
        if self.snapshot_store is not None:
            stale = self.snapshot_store.get_stale(namespace, cache_key)
            if isinstance(stale, dict):
                return stale
        try:
            raw = self.redis_client.get(self._redis_key(namespace, cache_key))
            if raw:
                payload = json.loads(str(raw))
                if isinstance(payload, dict):
                    return payload
        except Exception:
            pass
        return None

    def store(self, namespace: str, cache_key: str, payload: Dict[str, Any], ttl_seconds: int = SEED_META_TTL_SECONDS) -> Dict[str, Any]:
        if self.snapshot_store is not None:
            publish_snapshot(snapshot_store=self.snapshot_store, namespace=namespace, cache_key=cache_key,
                             payload=payload, ttl_seconds=ttl_seconds, redis_client=self.redis_client,
                             redis_cache_key=self._redis_key(namespace, cache_key))
            return payload
        try:
            serialized = json.dumps(payload, ensure_ascii=True, default=str)
            try:
                accepted = self.redis_client.set(self._redis_key(namespace, cache_key), serialized, ex=ttl_seconds)
            except TypeError:
                accepted = self.redis_client.set(self._redis_key(namespace, cache_key), serialized)
            if accepted is False:
                raise SnapshotPublicationError("Seed metadata write was not accepted")
        except Exception as exc:
            raise SnapshotPublicationError(f"Seed metadata write failed: {type(exc).__name__}") from exc
        return payload


def build_seed_meta_payload(
    *,
    panel_id: str,
    namespace: str,
    cache_key: str,
    service_name: str,
    expected_interval_seconds: int,
    status: str,
    last_attempt_at: Optional[str] = None,
    last_success_at: Optional[str] = None,
    record_count: Optional[int] = None,
    source_states: Optional[Dict[str, Any]] = None,
    error_summary: Optional[str] = None,
    cache_mode: Optional[str] = None,
    payload_status: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_status = str(status or "unknown").strip().lower() or "unknown"
    payload: Dict[str, Any] = {
        "panelId": str(panel_id or "").strip(),
        "namespace": str(namespace or "").strip(),
        "cacheKey": str(cache_key or "").strip(),
        "serviceName": str(service_name or "").strip(),
        "status": normalized_status,
        "lastAttemptAt": str(last_attempt_at or utc_now_iso()),
        "lastSuccessAt": str(last_success_at) if last_success_at else None,
        "expectedIntervalSeconds": max(1, int(expected_interval_seconds or 60)),
        "recordCount": max(0, int(record_count or 0)),
        "sourceStates": dict(source_states or {}),
        "errorSummary": str(error_summary).strip() if error_summary else None,
        "cacheMode": str(cache_mode).strip() if cache_mode else None,
        "payloadStatus": str(payload_status).strip() if payload_status else None,
        "updatedAt": utc_now_iso(),
    }
    if metadata:
        payload["metadata"] = dict(metadata)
    return payload
