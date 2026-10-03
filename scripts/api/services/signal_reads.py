"""Bound read verification without blocking HTTP workers on database transport.

Only the three canonical signal seeds use this lane. Collection remains owned
by the seed workers; a pending check cannot publish unverified rows or renew a
source clock. One task per channel also bounds work when a driver ignores its
deadline. Completed trade label checks may be reused for thirty seconds.
"""
from __future__ import annotations

from concurrent.futures import Future, TimeoutError
from copy import deepcopy
from dataclasses import dataclass
import time
from typing import Callable

from api.context import runtime_resources


class SignalReadPending(RuntimeError):
    """The current seed is not yet verified; retry without clearing the UI."""


@dataclass
class ReadCheck:
    seed: dict
    future: Future
    expires: float = 0


def read_verified_seed(ctx: dict, channel: str, seed: dict, verify: Callable[[dict], dict], *,
                       cache_seconds: float = 30, wait_seconds: float = .25) -> dict:
    resources = runtime_resources(ctx)
    with resources.signal_read_lock:
        check = resources.signal_reads.get(channel)
        if check and not check.future.done():
            if check.seed != seed:
                raise SignalReadPending("A previous seed check is completing")
        elif check is None or check.seed != seed or time.monotonic() >= check.expires:
            if check is None and len(resources.signal_reads) >= 3:
                raise SignalReadPending("Signal verification capacity is busy")
            check = ReadCheck(deepcopy(seed), Future())
            resources.signal_reads[channel] = check

            def run():
                try:
                    value = verify(deepcopy(check.seed))
                except Exception as exc:
                    with resources.signal_read_lock:
                        check.expires = time.monotonic() + 5
                        check.future.set_exception(exc)
                else:
                    with resources.signal_read_lock:
                        # Retry unavailable label checks sooner than healthy ones.
                        ttl = min(cache_seconds, 5) if value.get("error") else cache_seconds
                        check.expires = time.monotonic() + ttl
                        check.future.set_result(deepcopy(value))

            if not resources.start_thread(run, name=f"signal-read:{channel}"):
                check.future.set_exception(RuntimeError("Service runtime is closed"))
    try:
        return deepcopy(check.future.result(timeout=wait_seconds))
    except TimeoutError:
        # A verifier may itself raise TimeoutError: preserve that failure once
        # completed rather than labelling it as work still in progress.
        if check.future.done():
            raise
        raise SignalReadPending("Current signal verification is still running") from None
