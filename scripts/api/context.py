"""Application-owned resources and dependency-construction helpers."""

from __future__ import annotations

from api.config import ClickHouseSettings

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
import logging
import threading
from concurrent.futures import ThreadPoolExecutor


@dataclass
class RuntimeResources:
    """Mutable caches and background work owned by one application/worker."""

    clickhouse: ClickHouseSettings = field(default_factory=ClickHouseSettings.from_environment)
    snapshot_workers: int = 2
    workspace_workers: int = 2
    clickhouse_slots: Any = field(init=False)
    snapshot_slots: Any = field(init=False)
    workspace_slots: Any = field(init=False)

    def __post_init__(self):
        self.clickhouse_slots = threading.BoundedSemaphore(self.clickhouse.concurrency)
        self.snapshot_slots = threading.BoundedSemaphore(self.snapshot_workers)
        self.workspace_slots = threading.BoundedSemaphore(self.workspace_workers)

    health_cache: dict[str, Any] = field(default_factory=dict)
    health_lock: Any = field(default_factory=threading.Lock)
    health_refresh_lock: Any = field(default_factory=threading.Lock)
    health_refreshing: bool = False
    dashboard_refresh_lock: Any = field(default_factory=threading.Lock)
    dashboard_refreshing: bool = False
    prewarm_lock: Any = field(default_factory=threading.Lock)
    prewarm_last_run: dict[str, float] = field(default_factory=dict)
    snapshot_lock: Any = field(default_factory=threading.Lock)
    snapshot_refreshing: set[str] = field(default_factory=set)

    workspace_lock: Any = field(default_factory=threading.Lock)
    workspace_refreshing: set[str] = field(default_factory=set)
    live_refresh_lock: Any = field(default_factory=threading.Lock)
    live_refreshing: set[str] = field(default_factory=set)
    weather_state: dict[str, Any] = field(default_factory=dict)
    weather_state_lock: Any = field(default_factory=threading.Lock)
    content_lock: Any = field(default_factory=threading.Lock)
    content_table_exists: dict[tuple[str, str], bool] = field(default_factory=dict)
    content_tables_ensured: set[str] = field(default_factory=set)
    related_content: dict = field(default_factory=dict)
    quality_lock: Any = field(default_factory=threading.Lock)
    quality_last_good: dict | None = None
    quality_last_error: dict | None = None
    signal_lock: Any = field(default_factory=threading.Lock)
    signal_refreshing: dict[str, bool] = field(default_factory=dict)
    agent_lock: Any = field(default_factory=threading.Lock)
    agent_refreshing: set[str] = field(default_factory=set)
    agent_rate_lock: Any = field(default_factory=threading.Lock)
    agent_rate_buckets: dict[str, list[float]] = field(default_factory=dict)

    hazard_locks: dict[str, Any] = field(default_factory=dict)
    hazard_lock_guard: Any = field(default_factory=threading.Lock)
    hazard_executor: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(max_workers=9, thread_name_prefix="natural-hazard")
    )
    zone_cache: dict[str, tuple[float, Any]] = field(default_factory=dict)
    zone_cache_lock: Any = field(default_factory=threading.Lock)
    zone_executor: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(max_workers=24, thread_name_prefix="nws-zone")
    )
    http_local: Any = field(default_factory=threading.local)
    http_sessions: list[Any] = field(default_factory=list)
    http_lock: Any = field(default_factory=threading.Lock)
    stopped: threading.Event = field(default_factory=threading.Event)
    _threads: set[threading.Thread] = field(default_factory=set, repr=False)
    _thread_lock: Any = field(default_factory=threading.Lock, repr=False)

    def start_thread(self, target: Callable[[], None], *, name: str) -> bool:
        def run():
            try:
                target()
            finally:
                with self._thread_lock:
                    self._threads.discard(threading.current_thread())

        with self._thread_lock:
            if self.stopped.is_set():
                return False
            thread = threading.Thread(target=run, name=name, daemon=True)
            self._threads.add(thread)
            thread.start()
        return True

    def submit(self, executor, target, *args, **kwargs):
        with self._thread_lock:
            if self.stopped.is_set():
                raise RuntimeError("service runtime is closed")
            return executor.submit(target, *args, **kwargs)

    def close(self) -> None:
        with self._thread_lock:
            self.stopped.set()
            threads = tuple(self._threads)
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join()
        for executor in (self.hazard_executor, self.zone_executor):
            executor.shutdown(wait=True, cancel_futures=True)
        with self.http_lock:
            for session in self.http_sessions:
                session.close()
            self.http_sessions.clear()


def runtime_resources(context) -> RuntimeResources:
    """Partial worker/test contexts own their state just like application contexts."""
    state = context.get("_resources")
    if state is None:
        state = RuntimeResources()
        context["_resources"] = state
    return state


class ApplicationLog(Protocol):
    logger: logging.Logger


def resolve_route_callable(context: Mapping[str, Any], name: str) -> Callable[..., Any]:
    """Resolve one typed route dependency.

    Resolve a callable while constructing domain dependencies. Partial mappings
    are used by isolated tests; missing operations fail when invoked.
    """

    try:
        dependency = context[name]
    except KeyError:

        def missing_dependency(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError(f"Route dependency is unavailable: {name}")

        return missing_dependency
    if not callable(dependency):
        raise TypeError(f"Route dependency is not callable: {name}")
    return dependency


def resolve_service_callable(context: Mapping[str, Any], name: str) -> Callable[..., Any]:
    """Resolve a service callback at composition time; unavailable operations fail on use."""

    try:
        dependency = context[name]
    except KeyError:

        def missing_dependency(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError(f"Service dependency is unavailable: {name}")

        return missing_dependency
    if not callable(dependency):
        raise TypeError(f"Service dependency is not callable: {name}")
    return dependency


def resolve_optional_service_callable(
    context: Mapping[str, Any],
    name: str,
) -> Callable[..., Any] | None:
    """Resolve an optional service callable while rejecting invalid values."""

    dependency = context.get(name)
    if dependency is None:
        return None
    if not callable(dependency):
        raise TypeError(f"Service dependency is not callable: {name}")
    return dependency
