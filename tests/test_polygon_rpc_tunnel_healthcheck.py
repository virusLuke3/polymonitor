from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import socket
import subprocess
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ops" / "polygon_rpc_tunnel_healthcheck.sh"


def _run_healthcheck(tmp_path: Path, rpc_url: str, **extra: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "POLYDATA_ENV_FILE": str(tmp_path / "missing.env"),
            "POLYMARKET_RPC_URL": rpc_url,
            "POLYDATA_POLYGON_RPC_RESTART_FAILURE_THRESHOLD": "3",
            "POLYDATA_POLYGON_RPC_HEALTH_STATE_DIR": str(tmp_path / "state"),
            "POLYDATA_POLYGON_RPC_HEALTH_TIMEOUT_SECONDS": "0.1",
        }
    )
    env.update(extra)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )


def _unused_loopback_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_transport_failure_requires_consecutive_threshold(tmp_path: Path) -> None:
    url = f"http://127.0.0.1:{_unused_loopback_port()}"

    first = _run_healthcheck(tmp_path, url)
    second = _run_healthcheck(tmp_path, url)

    assert first.returncode == 0
    assert second.returncode == 0
    assert "TRANSIENT_TRANSPORT_FAILURE: 1/3" in first.stderr
    assert "TRANSIENT_TRANSPORT_FAILURE: 2/3" in second.stderr
    assert "Traceback" not in first.stderr + second.stderr
    assert (tmp_path / "state" / "consecutive-transport-failures").read_text() == "2\n"


def test_busy_bor_timeout_never_restarts_tunnel(tmp_path: Path) -> None:
    class SlowHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
            time.sleep(1)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _run_healthcheck(tmp_path, f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.returncode == 0
    assert "DEGRADED_BUSY" in result.stderr
    assert "restarting" not in result.stderr.lower()
    assert not (tmp_path / "state" / "consecutive-transport-failures").exists()


def test_invalid_restart_threshold_is_rejected(tmp_path: Path) -> None:
    result = _run_healthcheck(
        tmp_path,
        f"http://127.0.0.1:{_unused_loopback_port()}",
        POLYDATA_POLYGON_RPC_RESTART_FAILURE_THRESHOLD="0",
    )

    assert result.returncode == 64
    assert "invalid restart failure threshold" in result.stderr
