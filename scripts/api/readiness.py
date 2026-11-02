"""A bounded, cached dependency probe; polling never creates more workers."""
import threading
import time


class CachedProbe:
    def __init__(self, check, ttl=15.0):
        self.check, self.ttl = check, ttl
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
        completed.wait(0.1)
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
