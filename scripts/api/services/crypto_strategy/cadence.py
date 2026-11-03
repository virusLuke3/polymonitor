"""Worker-local attempt budgets; cached observations keep their source clocks."""
from copy import deepcopy


class SourceCadence:
    def __init__(self):
        self.entries = {}

    def read(self, key, now, interval_ms, fetch):
        entry = self.entries.get(key)
        if entry is not None and 0 <= now - entry[0] < interval_ms:
            if entry[2]:
                raise OSError("SOURCE_RETRY_WAIT:" + entry[2])
            return deepcopy(entry[1])
        try:
            value = fetch()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            # A failed source also waits its normal budget, without becoming
            # a successful observation or triggering every fast worker tick.
            self.entries[key] = (now, None, type(exc).__name__)
            raise
        self.entries[key] = (now, deepcopy(value), None)
        return value
