"""Small bounded connection pool for the threaded readonly API runtime."""

from __future__ import annotations

import os
import logging
import threading
import time
from collections import deque
from typing import Any, Callable


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return max(minimum, default)


def _env_float(name: str, default: float, *, minimum: float = 0.1) -> float:
    try:
        return max(minimum, float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return max(minimum, default)


class _ConnectionLease:
    def __init__(self, pool: "ApiPostgresConnectionPool", connection: Any) -> None:
        self._pool = pool
        self._connection = connection
        self._closed = False

    def __getattr__(self, name: str) -> Any:
        if self._closed:
            raise RuntimeError("database connection lease is already closed")
        return getattr(self._connection, name)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pool.release(self._connection)


class ApiPostgresConnectionPool:
    """Thread-safe lazy pool that preserves the existing connection interface."""

    def __init__(
        self,
        connection_factory: Callable[..., Any],
        *,
        max_size: int,
        acquire_timeout_seconds: float,
        connect_attempts: int,
        connect_retry_delay_seconds: float,
    ) -> None:
        self._connection_factory = connection_factory
        self._max_size = max(1, max_size)
        self._acquire_timeout_seconds = max(0.1, acquire_timeout_seconds)
        self._connect_attempts = max(1, connect_attempts)
        self._connect_retry_delay_seconds = max(0.0, connect_retry_delay_seconds)
        self._condition = threading.Condition()
        self._idle: deque[Any] = deque()
        self._connection_count = 0
        self._leases: dict[int, tuple[float, str]] = {}
        self._closed = False

    def acquire(self, *args: Any, **kwargs: Any) -> _ConnectionLease:
        deadline = time.monotonic() + self._acquire_timeout_seconds
        create_connection = False
        with self._condition:
            while True:
                if self._closed:
                    raise RuntimeError("database connection pool is closed")
                if self._idle:
                    connection = self._idle.popleft()
                    break
                if self._connection_count < self._max_size:
                    self._connection_count += 1
                    create_connection = True
                    connection = None
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    held = sorted(
                        ((round(time.monotonic() - started, 1), owner) for started, owner in self._leases.values()),
                        reverse=True,
                    )
                    raise TimeoutError(
                        f"timed out waiting for an API PostgreSQL connection "
                        f"(pool size={self._max_size}, held_seconds_and_threads={held})"
                    )
                self._condition.wait(timeout=remaining)

        if create_connection:
            for attempt in range(1, self._connect_attempts + 1):
                try:
                    connection = self._connection_factory(*args, **kwargs)
                    # The shared DB factory configures PostgreSQL search_path in
                    # its initial transaction. Commit that session setup before
                    # leases start using rollback for transaction cleanup.
                    connection.commit()
                    break
                except Exception:
                    if connection is not None:
                        try:
                            connection.close()
                        except Exception:
                            pass
                    connection = None
                    if attempt >= self._connect_attempts or time.monotonic() >= deadline:
                        with self._condition:
                            self._connection_count -= 1
                            self._condition.notify()
                        raise
                    time.sleep(self._connect_retry_delay_seconds * attempt)
        with self._condition:
            if self._closed:
                self._connection_count -= 1
                connection.close()
                raise RuntimeError("database connection pool is closed")
            self._leases[id(connection)] = (time.monotonic(), threading.current_thread().name)
        return _ConnectionLease(self, connection)

    def release(self, connection: Any) -> None:
        reusable = True
        try:
            connection.rollback()
        except Exception:
            reusable = False
            try:
                connection.close()
            except Exception:
                pass

        with self._condition:
            lease = self._leases.pop(id(connection), None)
            if reusable and not self._closed:
                self._idle.append(connection)
            else:
                if reusable:
                    connection.close()
                self._connection_count -= 1
            self._condition.notify()
        if lease is not None and time.monotonic() - lease[0] >= 5:
            logging.getLogger(__name__).warning(
                "API PostgreSQL connection held %.1fs thread=%s", time.monotonic() - lease[0], lease[1],
            )

    def close(self) -> None:
        with self._condition:
            self._closed = True
            idle = tuple(self._idle)
            self._idle.clear()
            self._connection_count -= len(idle)
            self._condition.notify_all()
        for connection in idle:
            connection.close()


def build_api_connection_factory(
    connection_factory: Callable[..., Any],
    backend_provider: Callable[[], str],
) -> Callable[..., Any]:
    """Return a pooled API connector while retaining non-PostgreSQL behavior."""

    pool_size = _env_int("POLYDATA_API_POSTGRES_POOL_SIZE", 1)
    if pool_size <= 0:
        return connection_factory
    pool = ApiPostgresConnectionPool(
        connection_factory,
        max_size=pool_size,
        acquire_timeout_seconds=_env_float(
            "POLYDATA_API_POSTGRES_POOL_ACQUIRE_TIMEOUT_SECONDS",
            45.0,
        ),
        connect_attempts=_env_int(
            "POLYDATA_API_POSTGRES_POOL_CONNECT_ATTEMPTS",
            6,
            minimum=1,
        ),
        connect_retry_delay_seconds=_env_float(
            "POLYDATA_API_POSTGRES_POOL_CONNECT_RETRY_DELAY_SECONDS",
            0.5,
            minimum=0.0,
        ),
    )

    def _connect(*args: Any, **kwargs: Any) -> Any:
        if backend_provider().strip().lower() not in {"postgres", "postgresql"}:
            return connection_factory(*args, **kwargs)
        return pool.acquire(*args, **kwargs)

    _connect.close = pool.close
    return _connect
