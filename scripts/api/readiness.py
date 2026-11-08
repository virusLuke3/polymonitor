"""A bounded, cached dependency probe; polling never creates more workers."""
import threading
import time

from api.read_budget import try_permit


def probe_database(connect, db_path=None):
    """Probe the dependency without waiting behind bulk display reads.

    CachedProbe allows one in-flight call per worker; the shared permit caps
    health connections at two per host, separate from the four display slots.
    """
    permit = try_permit("postgres-readiness", 2)
    if permit is None:
        return False
    with permit:
        connection = connect(db_path, readonly=True, connect_timeout=2)
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1 AS ready")
            return cursor.fetchone() is not None
        finally:
            connection.close()


class CachedProbe:
    def __init__(self, check, ttl=15.0, timeout=2.0):
        self.check, self.ttl = check, ttl
        self.timeout = timeout
        self.lock = threading.Lock()
        self.running = None
        self.checked_at = 0.0
        self.ready = False

    def __call__(self):
        with self.lock:
            if self.checked_at and time.monotonic() - self.checked_at < self.ttl:
                return self.ready
            if self.running is None:
                self.running = threading.Event()
                threading.Thread(target=self._run, name="database-readiness", daemon=True).start()
            completed = self.running
        completed.wait(self.timeout)
        with self.lock:
            return bool(self.checked_at and time.monotonic() - self.checked_at < self.ttl and self.ready)

    def _run(self):
        try:
            ready = bool(self.check())
        except Exception:
            ready = False
        with self.lock:
            self.ready, self.checked_at = ready, time.monotonic()
            completed, self.running = self.running, None
            completed.set()
