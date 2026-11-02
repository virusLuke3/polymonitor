"""Host-wide admission for this API, including overlapping worker generations.

Locks are released by the kernel if a worker exits. No database or Redis calls
are needed to reject work, and the number of lock files is fixed.
"""
from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path


class ReadPermit:
    def __init__(self, fd: int):
        self.fd = fd

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def try_permit(source: str, capacity: int) -> ReadPermit | None:
    root = Path(os.environ.get("POLYDATA_READ_BUDGET_DIR", f"/tmp/polydata-api-read-{os.getuid()}"))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for slot in range(capacity):
        fd = os.open(root / f"{source}-{slot}.lock", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return ReadPermit(fd)
        except BlockingIOError:
            os.close(fd)
    return None


def take_read_token(source: str, *, per_second: float, burst: int) -> bool:
    """Bound cache-miss throughput too; concurrency alone is not a rate budget."""
    permit = try_permit(source + "-rate", 1)
    if permit is None:
        return False
    with permit:
        raw = os.read(permit.fd, 128).decode("ascii")
        now = time.monotonic()
        try:
            then, tokens = (float(part) for part in raw.split())
            # monotonic time resets on reboot; a fresh window has at most burst.
            tokens = min(burst, tokens + max(0, now - then) * per_second) if now >= then else float(burst)
        except ValueError:
            tokens = float(burst)
        allowed = tokens >= 1
        if allowed:
            tokens -= 1
        os.lseek(permit.fd, 0, os.SEEK_SET)
        os.write(permit.fd, f"{now} {tokens}".encode("ascii"))
        os.ftruncate(permit.fd, os.lseek(permit.fd, 0, os.SEEK_CUR))
        return allowed
