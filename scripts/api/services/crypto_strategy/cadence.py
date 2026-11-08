"""Source-owned schedules and bounded last-good recovery, persisted by the writer."""
from copy import deepcopy
import json


def source_error(exc):
    if isinstance(exc, SourceReadError):
        return exc.reason
    if isinstance(exc, ValueError) and str(exc).startswith(("BYBIT_", "DERIBIT_", "KRAKEN_", "INVALID_STABLECOIN")):
        return str(exc)[:100]
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return f"HTTP_{status}" if isinstance(status, int) else type(exc).__name__


class SourceReadError(OSError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__("SOURCE_RETRY_WAIT:" + reason)


class SourceCadence:
    def __init__(self, entries=None, *, read_only=False):
        self.entries = deepcopy(entries or {})
        self.read_only = read_only

    @staticmethod
    def key(key):
        return json.dumps(key, separators=(",", ":"))

    def read(self, key, now, interval_ms, fetch, *, retain_ms=1_800_000):
        identity = self.key(key)
        entry = self.entries.get(identity)
        if not self.read_only and (entry is None or now < entry["lastAttemptAt"] or now >= entry["retryAt"]):
            try:
                value = fetch()
            except (OSError, ValueError, TypeError, KeyError) as exc:
                failures = (entry or {}).get("failures", 0) + 1
                entry = {**(entry or {}), "lastAttemptAt": now, "error": source_error(exc),
                         "failures": failures,
                         "retryAt": now + min(interval_ms, 60_000 * 2 ** min(failures - 1, 3), 300_000)}
                self.entries[identity] = entry
            else:
                entry = {"lastAttemptAt": now, "lastSuccessAt": now, "error": None,
                         "failures": 0, "retryAt": now + interval_ms, "value": deepcopy(value)}
                self.entries[identity] = entry
        if entry is None:
            raise SourceReadError("SOURCE_REFRESH_PENDING")
        success = entry.get("lastSuccessAt")
        if success is not None and 0 <= now - success <= retain_ms and "value" in entry:
            return deepcopy(entry["value"])
        entry.pop("value", None)
        raise SourceReadError(entry.get("error") or "SOURCE_CACHE_EXPIRED")

    def state(self, key):
        entry = self.entries.get(self.key(key), {})
        return {"status": "stale" if entry.get("error") and "value" in entry else
                          "unavailable" if entry.get("error") or "value" not in entry else "ok",
                "lastAttemptAt": entry.get("lastAttemptAt"), "lastSuccessAt": entry.get("lastSuccessAt"),
                "retryAt": entry.get("retryAt"), "error": entry.get("error"),
                "retained": bool(entry.get("error") and "value" in entry)}
