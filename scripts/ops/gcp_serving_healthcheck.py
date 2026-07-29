#!/usr/bin/env python3
"""Bounded self-healing for the GCP API and Telegram publisher.

The normal systemd restart policy handles process exits.  This check handles
the more subtle case where a process is still running but no longer serving
useful work.  Recovery is deliberately rate limited so a broken deployment or
dependency cannot turn into a restart storm.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import ProxyHandler, build_opener

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ops.lib.incidents import update_incident_history
from scripts.ops.lib.redaction import redact_text
from scripts.ops.lib.snapshot import operations_state_dir


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return max(minimum, default)


API_UNIT = os.environ.get("POLYDATA_SERVING_HEALTH_API_UNIT", "polydata-api.service")
PUBLISHER_UNIT = os.environ.get(
    "POLYDATA_SERVING_HEALTH_PUBLISHER_UNIT", "polydata-telegram-publisher.service"
)
API_BASE = os.environ.get(
    "POLYDATA_SERVING_HEALTH_API_BASE",
    f"http://127.0.0.1:{os.environ.get('POLYDATA_API_PORT', '18500')}",
).rstrip("/")
PROBE_TIMEOUT_SECONDS = _env_int("POLYDATA_SERVING_HEALTH_PROBE_TIMEOUT_SECONDS", 10)
FAILURE_THRESHOLD = _env_int("POLYDATA_SERVING_HEALTH_FAILURE_THRESHOLD", 2)
RESTART_WINDOW_SECONDS = _env_int("POLYDATA_SERVING_HEALTH_RESTART_WINDOW_SECONDS", 1800)
MAX_RESTARTS_PER_WINDOW = _env_int("POLYDATA_SERVING_HEALTH_MAX_RESTARTS", 3)
BACKOFF_SECONDS = _env_int("POLYDATA_SERVING_HEALTH_BACKOFF_SECONDS", 1800)
API_WARMUP_SECONDS = _env_int("POLYDATA_SERVING_HEALTH_API_WARMUP_SECONDS", 180)
PUBLISHER_WARMUP_SECONDS = _env_int("POLYDATA_SERVING_HEALTH_PUBLISHER_WARMUP_SECONDS", 120)
PUBLISHER_STALE_SECONDS = _env_int("POLYDATA_SERVING_HEALTH_PUBLISHER_STALE_SECONDS", 300)

STATE_DIR = Path(
    os.environ.get(
        "POLYDATA_SERVING_HEALTH_STATE_DIR",
        str(Path.home() / ".local" / "state" / "polydata-serving-healthcheck"),
    )
)
STATE_PATH = STATE_DIR / "state.json"
LOCK_PATH = STATE_DIR / "healthcheck.lock"
PUBLISHER_HEARTBEAT_PATH = Path(
    os.environ.get(
        "POLYDATA_TELEGRAM_HEARTBEAT_PATH",
        str(Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "polydata-telegram" / "publisher-heartbeat.json"),
    )
)


def _log(message: str) -> None:
    print(f"[serving-health] {redact_text(message, limit=500)}", file=sys.stderr, flush=True)


def _default_unit_state() -> dict[str, Any]:
    return {
        "consecutive_failures": 0,
        "restart_attempts": [],
        "backoff_until": 0,
        "last_recovery_at": 0,
        "last_success_at": 0,
        "last_failure": "",
        "start_limit_blocked": False,
    }


def _load_state() -> dict[str, Any]:
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload.setdefault("units", {})
            return payload
    except (OSError, ValueError, TypeError):
        pass
    return {"units": {}}


def _save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(STATE_PATH)


def _unit_state(state: dict[str, Any], key: str) -> dict[str, Any]:
    units = state.setdefault("units", {})
    current = units.setdefault(key, _default_unit_state())
    for field, value in _default_unit_state().items():
        current.setdefault(field, value)
    return current


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )


def _unit_active(unit: str) -> bool:
    return _systemctl("is-active", "--quiet", unit).returncode == 0


def _probe_json(path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = f"?{urlencode(params)}" if params else ""
    request = build_opener(ProxyHandler({})).open(
        f"{API_BASE}/{path.lstrip('/')}{query}", timeout=PROBE_TIMEOUT_SECONDS
    )
    try:
        if int(getattr(request, "status", 200)) != 200:
            raise RuntimeError(f"HTTP {getattr(request, 'status', 'unknown')}")
        payload = json.loads(request.read().decode("utf-8"))
    finally:
        request.close()
    if not isinstance(payload, dict):
        raise RuntimeError("response was not a JSON object")
    return payload


def _api_healthy() -> tuple[bool, bool, str]:
    if not _unit_active(API_UNIT):
        return False, False, f"{API_UNIT} is not active"
    try:
        health = _probe_json("/health")
        status = str(health.get("status") or "").lower()
        if status not in {"ok", "degraded"}:
            return False, False, f"/health returned status={status!r}"
        if status == "degraded":
            return True, False, "API responsive; dependency health is degraded"
        _probe_json("/content/latest", params={"limit": 1})
    except Exception as exc:
        return False, False, f"API probe failed: {exc}"
    return True, True, "liveness and latest-content probes passed"


def _record_recovery_incident(component: str, status: str, summary: str) -> None:
    try:
        update_incident_history(
            operations_state_dir() / "incidents.json",
            [{"component": f"recovery:{component}", "status": status, "summary": summary}],
        )
    except Exception as exc:
        _log(f"could not record recovery incident: {type(exc).__name__}")


def _publisher_healthy(now: int) -> tuple[bool, str]:
    if not _unit_active(PUBLISHER_UNIT):
        return False, f"{PUBLISHER_UNIT} is not active"
    try:
        age = max(0, now - int(PUBLISHER_HEARTBEAT_PATH.stat().st_mtime))
    except OSError as exc:
        return False, f"publisher heartbeat unavailable: {exc}"
    if age > PUBLISHER_STALE_SECONDS:
        return False, f"publisher heartbeat is stale ({age}s > {PUBLISHER_STALE_SECONDS}s)"
    return True, f"publisher heartbeat age={age}s"


def _mark_healthy(unit_state: dict[str, Any], now: int) -> None:
    unit_state["consecutive_failures"] = 0
    unit_state["last_success_at"] = now
    unit_state["last_failure"] = ""
    unit_state["restart_attempts"] = [
        int(value)
        for value in unit_state.get("restart_attempts", [])
        if now - int(value) < RESTART_WINDOW_SECONDS
    ]


def _recover(
    *,
    key: str,
    unit: str,
    reason: str,
    now: int,
    state: dict[str, Any],
    warmup_seconds: int,
) -> None:
    current = _unit_state(state, key)
    last_recovery_at = int(current.get("last_recovery_at") or 0)
    if last_recovery_at and now - last_recovery_at < warmup_seconds:
        _log(
            f"{key} unhealthy during warmup ({now - last_recovery_at}s/{warmup_seconds}s): {reason}"
        )
        return

    current["consecutive_failures"] = int(current.get("consecutive_failures") or 0) + 1
    current["last_failure"] = reason
    failures = int(current["consecutive_failures"])
    if failures < FAILURE_THRESHOLD:
        _log(f"{key} failure {failures}/{FAILURE_THRESHOLD}; waiting for confirmation: {reason}")
        return

    backoff_until = int(current.get("backoff_until") or 0)
    if now < backoff_until:
        _log(f"{key} recovery suppressed by backoff for {backoff_until - now}s: {reason}")
        return

    attempts = [
        int(value)
        for value in current.get("restart_attempts", [])
        if now - int(value) < RESTART_WINDOW_SECONDS
    ]
    current["restart_attempts"] = attempts
    if len(attempts) >= MAX_RESTARTS_PER_WINDOW:
        current["backoff_until"] = now + BACKOFF_SECONDS
        current["consecutive_failures"] = 0
        _log(
            f"{key} restart budget exhausted ({len(attempts)}/{MAX_RESTARTS_PER_WINDOW}); "
            f"backing off for {BACKOFF_SECONDS}s"
        )
        return

    if bool(current.get("start_limit_blocked")):
        _log(f"{key} backoff elapsed; resetting systemd start-limit state")
        _systemctl("reset-failed", unit)
        current["start_limit_blocked"] = False

    _log(
        f"restarting {unit} after {failures} consecutive failures "
        f"(attempt {len(attempts) + 1}/{MAX_RESTARTS_PER_WINDOW}): {reason}"
    )
    _record_recovery_incident(key, "warning", f"bounded restart attempt for {unit}")
    result = _systemctl("restart", unit)
    current["restart_attempts"] = [*attempts, now]
    current["last_recovery_at"] = now
    current["consecutive_failures"] = 0
    if result.returncode != 0:
        current["start_limit_blocked"] = True
        current["backoff_until"] = now + BACKOFF_SECONDS
        _log(
            f"restart of {unit} failed; backing off for {BACKOFF_SECONDS}s: "
            f"{result.stdout.strip() or 'unknown systemctl error'}"
        )
        _record_recovery_incident(key, "unhealthy", f"bounded restart failed for {unit}")
    else:
        current["backoff_until"] = 0


def run_once(*, now: int | None = None) -> int:
    timestamp = int(time.time() if now is None else now)
    state = _load_state()

    api_ok, dependencies_ready, api_detail = _api_healthy()
    api_state = _unit_state(state, "api")
    if api_ok:
        _mark_healthy(api_state, timestamp)
        _record_recovery_incident("api", "healthy", "API recovery path healthy")
        _log(f"api healthy: {api_detail}")
    else:
        _recover(
            key="api",
            unit=API_UNIT,
            reason=api_detail,
            now=timestamp,
            state=state,
            warmup_seconds=API_WARMUP_SECONDS,
        )

    # The publisher depends on the API. Restarting it while the API is down only
    # wastes resources, so publisher recovery is attempted only after API probes
    # pass.
    if api_ok and dependencies_ready:
        publisher_ok, publisher_detail = _publisher_healthy(timestamp)
        publisher_state = _unit_state(state, "publisher")
        if publisher_ok:
            _mark_healthy(publisher_state, timestamp)
            _record_recovery_incident("publisher", "healthy", "publisher recovery path healthy")
            _log(f"publisher healthy: {publisher_detail}")
        else:
            _recover(
                key="publisher",
                unit=PUBLISHER_UNIT,
                reason=publisher_detail,
                now=timestamp,
                state=state,
                warmup_seconds=PUBLISHER_WARMUP_SECONDS,
            )
    else:
        _log("publisher recovery deferred until API and its dependencies are healthy")

    _save_state(state)
    return 0


def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _log("another healthcheck is still running; skipping this cycle")
            return 0
        return run_once()


if __name__ == "__main__":
    raise SystemExit(main())
