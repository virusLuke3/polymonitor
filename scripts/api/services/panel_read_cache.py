"""Bounded shared last-good cache for the four market data panels.

Uses the existing local snapshot store and its striped process locks. Redis is
not required for admission or deduplication on the single API host.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

from api import cache
from api.read_budget import ReadPermit, try_permit

NAMESPACE = "snapshot:market-panels-v2"


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class PanelReadCache:
    def __init__(self, runtime):
        self.runtime = runtime
        self.store = runtime.SNAPSHOT_STORE

    def get(self, layer, identity, builder, *, ttl, max_age, admit=True):
        key = json.dumps([layer, identity], sort_keys=True, separators=(",", ":"))
        value = cache.get_cached_runtime_payload(self.runtime.cache, NAMESPACE, key)
        if value is None:
            value = self.store.get(NAMESPACE, key)
        if value is not None:
            # Never extend a shared snapshot's actual deadline in worker memory.
            return copy.deepcopy(value)
        stale = self.store.get_stale(NAMESPACE, key, max_age_seconds=max_age)
        cooling = self.store.get(NAMESPACE + ":errors", key)
        permit = None if cooling else try_permit("panel-builds", 2) if admit else ReadPermit(None)
        if permit is None:
            return self._fallback(stale, "unavailable" if cooling else "warming")

        def build():
            with permit:
                try:
                    with self.store.fetch_lock(NAMESPACE, key, timeout=0):
                        # Another worker may have finished while admission was pending.
                        existing = self.store.get(NAMESPACE, key)
                        if existing is not None:
                            return existing
                        if self.store.get(NAMESPACE + ":errors", key):
                            return self._fallback(stale, "unavailable")
                        try:
                            payload = builder()
                            payload.setdefault("status", "ok")
                            payload.setdefault("generatedAt", utc_now())
                            if len(json.dumps(payload, default=str)) > 1024 * 1024:
                                raise ValueError("Panel response size exceeded")
                            self.store.set(NAMESPACE, key, payload, ttl, max_entries=512)
                            self.store.set(NAMESPACE + ":health", layer, {
                                "status": "ok", "lastReadAt": utc_now(), "scope": "last-requested-key",
                                "sourceUpdatedAt": payload.get("sourceUpdatedAt") or payload.get("updatedAt"),
                            }, 120, max_entries=16)
                            cache.set_cached_runtime_payload(self.runtime.cache, NAMESPACE, key, payload, ttl)
                            return payload
                        except Exception as error:
                            self.runtime.app.logger.warning("panel read failed layer=%s error_type=%s", layer, type(error).__name__)
                            self.store.set(NAMESPACE + ":health", layer, {"status": "unavailable", "lastAttemptAt": utc_now(), "scope": "last-requested-key"}, 120, max_entries=16)
                            self.store.set(NAMESPACE + ":errors", key, {"failedAt": utc_now()}, 15, max_entries=512)
                            return self._fallback(stale, "unavailable")
                except TimeoutError:
                    return self._fallback(stale, "warming")

        if stale is not None:
            if not self.runtime.resources.start_thread(build, name="panel-read-refresh"):
                permit.close()
            return self._fallback(stale, "refreshing")
        return copy.deepcopy(build())

    @staticmethod
    def _fallback(stale, status):
        if stale is not None:
            payload = {**copy.deepcopy(stale), "status": "stale", "stale": True, "refreshStatus": status}
            if "historyStatus" in payload:
                payload["historyStatus"] = "stale"
            return payload
        return {"status": status, "retryAfter": 15, "items": [], "points": [], "historyStatus": status}
