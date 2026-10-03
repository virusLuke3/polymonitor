"""Service resources and business operations, independent of HTTP registration."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import replace

try:
    import requests
except ImportError:
    requests = None
from types import SimpleNamespace

from db.trade_v2 import (
    get_trade_read_source,
    sql_identifier,
)
from runtime.content_runtime import RuntimeContentProvider
from runtime.snapshot_store import SnapshotStore

from api import cache as api_cache
from api import db as api_db
from api.config import ApiSettings, load_api_settings
from api.context import ApplicationLog, RuntimeResources
from api.db_pool import ApiPostgresConnectionPool, build_api_connection_factory
from api.services import (
    bootstrap_service,
    global_weather_map_service,
    natural_hazards,
    system_service,
)


class ServiceRuntime:
    """Instance-owned service resources. Workers and HTTP apps use the same composition without importing each other."""

    def __init__(
        self, settings: ApiSettings | None = None, *, application: ApplicationLog | None = None, connection_factory=None
    ):
        self.SETTINGS = settings or load_api_settings()
        self.resources = RuntimeResources(
            clickhouse=self.SETTINGS.clickhouse,
            snapshot_workers=self.SETTINGS.snapshot_refresh_workers,
            workspace_workers=self.SETTINGS.workspace_refresh_workers,
            shutdown_timeout_seconds=self.SETTINGS.shutdown_timeout_seconds,
        )
        self.app = application or SimpleNamespace(logger=logging.getLogger("polydata.services"))
        self.ALLOWED_ORIGINS = set(self.SETTINGS.allowed_origins)
        self._dashboard_cache_lock = threading.Lock()
        self._dashboard_cache: Dict[str, Any] = {"value": None, "expires_at": 0.0}
        self._bootstrap_cache_lock = threading.Lock()
        self._bootstrap_cache: Dict[str, Any] = {"value": None, "expires_at": 0.0}
        self._clob_session = None
        self._clob_session_lock = threading.Lock()
        self._api_connection_factory = connection_factory or build_api_connection_factory(
            self.SETTINGS.database.connect, lambda: self.SETTINGS.database.backend
        )
        # Label checks must not queue behind unrelated background builders.
        self._alpha_database = replace(self.SETTINGS.database, connection={
            **self.SETTINGS.database.connection, "statement_timeout_ms": 3000, "connect_timeout": 8,
        })
        self._alpha_connection_pool = ApiPostgresConnectionPool(
            connection_factory or self._alpha_database.connect,
            max_size=1, acquire_timeout_seconds=8,
        ) if self.SETTINGS.database.backend in {"postgres", "postgresql"} else None
        self.TRADE_READ_SOURCE = sql_identifier(get_trade_read_source())
        self.CONTENT_RUNTIME_PROVIDER = RuntimeContentProvider()
        self.SNAPSHOT_STORE = SnapshotStore(self.SETTINGS.snapshot_sqlite_path)
        self._runtime_init_lock = threading.Lock()
        self._runtime_initialized = False
        self._closed = False
        self._snapshot_prewarm_owner_fd = None
        from api.bindings import bind_services

        bind_services(self)
        alpha_db_context = {**self.api_db_context}
        if self._alpha_connection_pool is not None:
            alpha_db_context["get_connection"] = self._alpha_connection_pool.acquire
        self.alpha_signal_context = {
            **self.signal_context,
            "query_all": lambda sql, params=None: api_db.query_all(alpha_db_context, sql, params),
        }
        self.signal_context["alpha_context"] = self.alpha_signal_context

    def _runtime_coordination_dir(self) -> Path:
        candidate = Path(self.SETTINGS.snapshot_sqlite_path).expanduser()
        base_dir = candidate.parent if candidate.parent != Path("") else Path("/tmp/polydata")
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir

    def _try_acquire_runtime_lock(self, lock_name: str):
        lock_path = self._runtime_coordination_dir() / lock_name
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 384)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
            return fd
        except BlockingIOError:
            os.close(fd)
            return None

    def _claim_startup_prewarm_slot(self) -> bool:
        cooldown_seconds = max(30, int(os.environ.get("POLYDATA_STARTUP_PREWARM_COOLDOWN_SECONDS", "300")))
        marker_path = self._runtime_coordination_dir() / "startup-prewarm.marker"
        lock_path = self._runtime_coordination_dir() / "startup-prewarm.marker.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 384)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            now = time.time()
            last_run = 0.0
            if marker_path.exists():
                try:
                    payload = json.loads(marker_path.read_text(encoding="utf-8") or "{}")
                    last_run = float(payload.get("last_run_ts") or 0.0)
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    last_run = 0.0
            if now - last_run < cooldown_seconds:
                self.app.logger.info(
                    "startup-prewarm skip reason=cooldown pid=%s cooldown_seconds=%s age_seconds=%.2f",
                    os.getpid(),
                    cooldown_seconds,
                    max(0.0, now - last_run),
                )
                return False
            marker_path.write_text(json.dumps({"last_run_ts": now, "pid": os.getpid()}), encoding="utf-8")
            self.app.logger.info("startup-prewarm claim pid=%s cooldown_seconds=%s", os.getpid(), cooldown_seconds)
            return True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _claim_snapshot_prewarm_owner(self) -> bool:
        if self._snapshot_prewarm_owner_fd is not None:
            return True
        fd = self._try_acquire_runtime_lock("snapshot-prewarm.worker.lock")
        if fd is None:
            self.app.logger.info("snapshot-prewarm thread-skip reason=lock-held pid=%s", os.getpid())
            return False
        self._snapshot_prewarm_owner_fd = fd
        self.app.logger.info("snapshot-prewarm thread-owner pid=%s", os.getpid())
        return True

    def get_clob_session(self):
        if requests is None:
            return None
        if self._clob_session is not None:
            return self._clob_session
        with self._clob_session_lock:
            if self._clob_session is not None:
                return self._clob_session
            session = requests.Session()
            session.trust_env = str(os.environ.get("POLYDATA_CLOB_TRUST_ENV_PROXY") or "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            session.headers.update({"Accept": "application/json", "User-Agent": "polyData-api/1.0"})
            self._clob_session = session
            return self._clob_session

    def set_cached_runtime_payload(
        self, namespace: str, cache_key: str, payload: Any, ttl_seconds: int | None = None
    ) -> Any:
        if ttl_seconds is None:
            ttl_seconds = self.SETTINGS.clob_price_cache_ttl_seconds
        return api_cache.set_cached_runtime_payload(self.cache, namespace, cache_key, payload, ttl_seconds)

    def set_cached_json(self, namespace: str, cache_key: str, payload: Dict[str, Any], ttl_seconds: int) -> None:
        api_cache.set_cached_json(self.cache, namespace, cache_key, payload, ttl_seconds)

    def http_form_post(
        self, url: str, *, data: Dict[str, Any], timeout: int = 12, headers: Optional[Dict[str, str]] = None
    ) -> Any:
        if requests is None:
            raise RuntimeError("requests is not installed")
        session = requests.Session()
        session.trust_env = str(os.environ.get("POLYDATA_API_HTTP_TRUST_ENV_PROXY") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            response = session.post(url, data=data, timeout=timeout, headers=headers)
            response.raise_for_status()
            return response.json()
        finally:
            session.close()

    def http_text_get(self, url: str, *, timeout: int = 12, headers: Optional[Dict[str, str]] = None) -> str:
        if requests is None:
            raise RuntimeError("requests is not installed")
        session = requests.Session()
        session.trust_env = str(os.environ.get("POLYDATA_API_HTTP_TRUST_ENV_PROXY") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            response = session.get(url, timeout=timeout, headers=headers)
            response.raise_for_status()
            return response.text
        finally:
            session.close()

    def http_bytes_get(self, url: str, *, timeout: int = 12, headers: Optional[Dict[str, str]] = None) -> bytes:
        if requests is None:
            raise RuntimeError("requests is not installed")
        session = requests.Session()
        session.trust_env = str(os.environ.get("POLYDATA_API_HTTP_TRUST_ENV_PROXY") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            response = session.get(url, timeout=timeout, headers=headers)
            response.raise_for_status()
            return response.content
        finally:
            session.close()

    def get_natural_hazard_related_markets(
        self, event_id: str, limit: int = natural_hazards.DEFAULT_RELATED_MARKET_LIMIT
    ) -> Dict[str, Any] | None:
        hazards = natural_hazards.get_natural_hazards_snapshot(
            self.natural_hazard, limit=natural_hazards.DEFAULT_EVENT_LIMIT, allow_provider_fetch=False
        )
        weather_markets = global_weather_map_service.get_global_weather_map_snapshot(
            self.global_weather_map, limit=100, allow_live_build=False
        )
        return natural_hazards.related_weather_markets_snapshot(
            event_id=event_id, natural_hazards_payload=hazards, weather_map_payload=weather_markets, limit=limit
        )

    def get_dashboard_payload_cached(self) -> Dict[str, Any]:
        return bootstrap_service.get_dashboard_payload_cached(self.dashboard_cache)

    def get_markets_payload_cached(
        self, cache_key: str, builder, *, namespace: str = "markets", ttl_seconds: int | None = None
    ) -> Dict[str, Any]:
        if ttl_seconds is None:
            ttl_seconds = self.SETTINGS.markets_cache_ttl_seconds
        return api_cache.get_markets_payload_cached(
            self.cache, cache_key, builder, namespace=namespace, ttl_seconds=ttl_seconds
        )

    def get_bootstrap_component_cached(self, component_key: str, builder, *, ttl_seconds: int | None = None) -> Any:
        if ttl_seconds is None:
            ttl_seconds = self.SETTINGS.bootstrap_component_ttl_seconds
        return api_cache.get_bootstrap_component_cached(self.cache, component_key, builder, ttl_seconds=ttl_seconds)

    def prewarm_critical_payloads(self) -> None:
        bootstrap_service.prewarm_critical_payloads(self.bootstrap_prewarm)

    def start_snapshot_prewarm_thread(self) -> None:
        bootstrap_service.start_snapshot_prewarm_thread(self.bootstrap_prewarm)

    def start(self) -> None:
        """Start explicitly requested cache warmers once; never provision source schemas."""
        with self._runtime_init_lock:
            if self._closed:
                raise RuntimeError("service runtime is closed")
            if self._runtime_initialized:
                return
            if self._claim_startup_prewarm_slot():
                system_service.prewarm_system_health_payload(self.system_health)
                if self.SETTINGS.snapshot_prewarm_enabled:
                    self.prewarm_critical_payloads()
            if self.SETTINGS.snapshot_prewarm_enabled and self._claim_snapshot_prewarm_owner():
                self.start_snapshot_prewarm_thread()
            self._runtime_initialized = True

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self) -> None:
        """Stop work before closing the resources that its callbacks consume."""
        with self._runtime_init_lock:
            if self._closed:
                return
            self._closed = True
        self.resources.close()
        for resource in (self._clob_session, self.cache.redis_client, self.CONTENT_RUNTIME_PROVIDER, self._alpha_connection_pool):
            close = getattr(resource, "close", None)
            if close is not None:
                close()
        close = getattr(self._api_connection_factory, "close", None)
        if close is not None:
            close()
        if self._snapshot_prewarm_owner_fd is not None:
            os.close(self._snapshot_prewarm_owner_fd)
            self._snapshot_prewarm_owner_fd = None
