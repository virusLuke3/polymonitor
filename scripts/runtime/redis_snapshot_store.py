"""Shared public seeds. SQLite is retained only for private state and history."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from functools import lru_cache, wraps
import json
import os
import threading
import time
from urllib.parse import quote
import uuid

from runtime.snapshot_store import SnapshotStore

RETENTION_SECONDS = 7 * 86400
MAX_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 2048


def public_namespace(namespace):
    return (namespace.startswith(("snapshot:", "runtime:", "seed-meta:", "source:"))
            and namespace != "source:open-meteo") or namespace in {
                "agent:market-wide:snapshot", "agent:market-wide:quant"}


def source_version(payload, namespace):
    if not isinstance(payload, dict):
        return 0.0
    fields = (("lastAttemptAt", "updatedAt") if namespace.startswith("seed-meta:") else
              ("generatedAt", "snapshotGeneratedAt", "lastSuccessAt", "fetchedAt", "collectedAt"))
    for field in fields:
        value = payload.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value) / (1000 if value > 10**11 else 1)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
    return 0.0


# The payload and its clocks change together. Every held acquisition lease is
# checked inside this same atomic operation, including nested source locks.
_PUBLISH = """
for i=3,#KEYS do
  if redis.call('GET',KEYS[i]) ~= ARGV[i+4] then return 0 end
end
local old = tonumber(redis.call('HGET',KEYS[1],'version') or '0')
if old > tonumber(ARGV[4]) then return 0 end
if old == tonumber(ARGV[4]) and tonumber(redis.call('HGET',KEYS[1],'updated_at') or '0') > tonumber(ARGV[2]) then return 0 end
redis.call('HSET',KEYS[1], 'payload',ARGV[1], 'updated_at',ARGV[2],
  'expires_at',ARGV[3], 'version',ARGV[4], 'bytes',string.len(ARGV[1]))
redis.call('EXPIRE',KEYS[1],ARGV[5])
redis.call('ZADD',KEYS[2],ARGV[2],KEYS[1])
redis.call('EXPIRE',KEYS[2],math.max(tonumber(ARGV[5]),redis.call('TTL',KEYS[2])))
local excess = redis.call('ZCARD',KEYS[2]) - tonumber(ARGV[6])
if excess > 0 then
  local victims = redis.call('ZRANGE',KEYS[2],0,excess-1)
  for _,key in ipairs(victims) do redis.call('DEL',key); redis.call('ZREM',KEYS[2],key) end
end
return 1
"""
_RENEW = "if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('PEXPIRE',KEYS[1],ARGV[2]) end return 0"
_RELEASE = "if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0"


class RedisSnapshotStore(SnapshotStore):
    backend = "redis"

    def __init__(self, db_path, *, client, prefix="polydata:", lease_seconds=60):
        super().__init__(db_path)
        self.client = client
        self.prefix = prefix + "seed:v1:"
        self.lease_seconds = lease_seconds
        self._leases = ContextVar("seed_leases", default=())
        self._reads = ContextVar("seed_batch_reads", default=None)

    def key(self, namespace, cache_key):
        return self.prefix + "data:" + quote(namespace, safe="") + ":" + quote(cache_key, safe="")

    def index_key(self, namespace):
        return self.prefix + "index:" + quote(namespace, safe="")

    def _row(self, namespace, cache_key):
        key = self.key(namespace, cache_key)
        reads = self._reads.get()
        if reads is not None and key in reads:
            return reads[key]
        row = self.client.hmget(key, "payload", "updated_at", "expires_at")
        if reads is not None:
            reads[key] = row
        return row

    def get(self, namespace, cache_key):
        if not public_namespace(namespace):
            return super().get(namespace, cache_key)
        payload, _, expires = self._row(namespace, cache_key)
        return json.loads(payload) if payload and float(expires) > time.time() else None

    def get_stale(self, namespace, cache_key, *, max_age_seconds=None):
        if not public_namespace(namespace):
            return super().get_stale(namespace, cache_key, max_age_seconds=max_age_seconds)
        payload, updated, _ = self._row(namespace, cache_key)
        if payload and (max_age_seconds is None or time.time() - float(updated) <= max_age_seconds):
            return json.loads(payload)
        return None

    def get_latest_stale(self, namespace, *, exclude_cache_key=None):
        if not public_namespace(namespace):
            return super().get_latest_stale(namespace, exclude_cache_key=exclude_cache_key)
        keys = self.client.zrevrange(self.index_key(namespace), 0, MAX_ENTRIES - 1)
        excluded = self.key(namespace, exclude_cache_key) if exclude_cache_key else None
        for offset in range(0, len(keys), 32):
            batch = [key for key in keys[offset:offset + 32] if key != excluded]
            pipe = self.client.pipeline(transaction=False)
            for key in batch:
                pipe.hget(key, "payload")
            for key, payload in zip(batch, pipe.execute()):
                if payload:
                    return json.loads(payload)
                self.client.zrem(self.index_key(namespace), key)
        return None

    def set(self, namespace, cache_key, payload, ttl_seconds, *, max_entries=None):
        if not public_namespace(namespace):
            return super().set(namespace, cache_key, payload, ttl_seconds, max_entries=max_entries)
        now = time.time()
        return self.import_snapshot(namespace, cache_key, payload, now, now + max(1, ttl_seconds), max_entries=max_entries)

    def import_snapshot(self, namespace, cache_key, payload, updated_at, expires_at, *, max_entries=None):
        """Used by publication and explicit migration; never re-date source data."""
        if not public_namespace(namespace):
            raise ValueError("Not a public seed namespace")
        serialized = json.dumps(payload, ensure_ascii=True, default=str, allow_nan=False)
        if len(serialized.encode()) > MAX_BYTES:
            raise ValueError("Public seed exceeds 16 MiB")
        remaining = int(max(expires_at, updated_at + RETENTION_SECONDS) - time.time())
        if remaining <= 0:
            return False
        leases = self._leases.get()
        keys = [self.key(namespace, cache_key), self.index_key(namespace)] + [key for key, _ in leases]
        args = [serialized, updated_at, expires_at, source_version(payload, namespace), remaining,
                min(MAX_ENTRIES, max(1, max_entries or MAX_ENTRIES))] + [owner for _, owner in leases]
        accepted = bool(self.client.eval(_PUBLISH, len(keys), *keys, *args))
        if accepted and self._reads.get() is not None:
            self._reads.get().pop(keys[0], None)
        return accepted

    @contextmanager
    def read_batch(self, identities=()):
        """One pipelined read for declared identities; misses remain real misses."""
        keys = list(dict.fromkeys(self.key(ns, key) for ns, key in identities if public_namespace(ns)))
        pipe = self.client.pipeline(transaction=False)
        for key in keys:
            pipe.hmget(key, "payload", "updated_at", "expires_at")
        token = self._reads.set(dict(zip(keys, pipe.execute())) if keys else {})
        try:
            yield
        finally:
            self._reads.reset(token)

    @contextmanager
    def read_namespaces(self, namespaces):
        """Bounded bootstrap prefetch; domain getters still validate each value."""
        pipe = self.client.pipeline(transaction=False)
        for ns in dict.fromkeys(namespaces):
            pipe.zrevrange(self.index_key(ns), 0, 15)
        keys = list(dict.fromkeys(key for group in pipe.execute() for key in group))[:128]
        pipe = self.client.pipeline(transaction=False)
        for key in keys:
            pipe.hget(key, "bytes")
        selected, total = [], 0
        for key, size in zip(keys, pipe.execute()):
            if size and total + int(size) <= 32 * 1024 * 1024:
                selected.append(key)
                total += int(size)
        pipe = self.client.pipeline(transaction=False)
        for key in selected:
            pipe.hmget(key, "payload", "updated_at", "expires_at")
        token = self._reads.set(dict(zip(selected, pipe.execute())))
        try:
            yield
        finally:
            self._reads.reset(token)

    @contextmanager
    def fetch_lock(self, namespace, cache_key, *, timeout=6, lock_pool=0):
        if not public_namespace(namespace) and not namespace.startswith("owner:"):
            with super().fetch_lock(namespace, cache_key, timeout=timeout, lock_pool=lock_pool):
                yield
            return
        if not isinstance(lock_pool, int) or not 0 <= lock_pool < 8:
            raise ValueError("snapshot lock pool must be between 0 and 7")
        key = self.prefix + "lock:" + quote(namespace, safe="") + ":" + quote(cache_key, safe="")
        owner, milliseconds = uuid.uuid4().hex, int(self.lease_seconds * 1000)
        deadline = time.monotonic() + max(0, timeout)
        while not self.client.set(key, owner, nx=True, px=milliseconds):
            if time.monotonic() >= deadline:
                raise TimeoutError("shared-source-acquisition-deadline")
            time.sleep(min(.025, max(0, deadline - time.monotonic())))
        stop = threading.Event()

        def renew():
            while not stop.wait(self.lease_seconds / 3):
                try:
                    if not self.client.eval(_RENEW, 1, key, owner, milliseconds):
                        return
                except Exception:
                    return  # Publishing still checks the lease atomically.

        thread = threading.Thread(target=renew, name="seed-lease", daemon=True)
        token = self._leases.set(self._leases.get() + ((key, owner),))
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=1.1)
            self._leases.reset(token)
            try:
                self.client.eval(_RELEASE, 1, key, owner)
            except Exception:
                pass  # TTL releases it; never delete another owner's lease.


@lru_cache(maxsize=8)
def _client(url):
    import redis
    from redis.retry import Retry
    from redis.backoff import NoBackoff
    return redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=1,
                               socket_timeout=1, retry=Retry(NoBackoff(), 0), max_connections=16)


def create_snapshot_store(db_path, **kwargs):
    mode = os.environ.get("POLYMONITOR_SEED_BACKEND", "redis")
    if mode == "sqlite":
        return SnapshotStore(db_path, **kwargs)
    if mode != "redis":
        raise ValueError("POLYMONITOR_SEED_BACKEND must be redis or sqlite")
    from api.config import load_api_settings
    settings = load_api_settings()
    from runtime.environment import configured_value
    url = configured_value("POLYMONITOR_SEED_REDIS_URL", settings.redis_url)
    if not url:
        raise RuntimeError("Redis seed storage requires POLYMONITOR_SEED_REDIS_URL or POLYDATA_REDIS_URL")
    prefix = configured_value("POLYMONITOR_SEED_REDIS_PREFIX", settings.redis_prefix)
    return RedisSnapshotStore(db_path, client=_client(url), prefix=prefix)


def seed_writer(method):
    """One collector round across API workers/hosts; publication uses its lease."""
    @wraps(method)
    def run(self, *args, **kwargs):
        store = getattr(self, "snapshot_store", None)
        if getattr(store, "backend", "sqlite") != "redis":
            return method(self, *args, **kwargs)
        with store.fetch_lock("snapshot:collector", type(self).__name__, timeout=0):
            return method(self, *args, **kwargs)
    return run
