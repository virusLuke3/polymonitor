#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${POLYDATA_ENV_FILE:-$HOME/.config/polydata/polydata.env}"

load_env_file() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -n "$line" && "${line:0:1}" != "#" && "$line" == *=* ]] || continue
    local key="${line%%=*}"
    local value="${line#*=}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    value="${value%\"}"
    value="${value#\"}"
    export "$key=$value"
  done < "$file"
}

load_env_file "$ENV_FILE"

RPC_URL="${POLYMARKET_RPC_URL:-http://127.0.0.1:28545}"
MAX_LAG_BLOCKS="${POLYDATA_POLYGON_RPC_MAX_LAG_BLOCKS:-5000}"
TUNNEL_UNIT="${POLYDATA_POLYGON_RPC_TUNNEL_UNIT:-polydata-polygon-rpc-tunnel.service}"
RESTART_FAILURE_THRESHOLD="${POLYDATA_POLYGON_RPC_RESTART_FAILURE_THRESHOLD:-3}"
RPC_TIMEOUT_SECONDS="${POLYDATA_POLYGON_RPC_HEALTH_TIMEOUT_SECONDS:-8}"
HEALTH_STATE_DIR="${POLYDATA_POLYGON_RPC_HEALTH_STATE_DIR:-${XDG_RUNTIME_DIR:-/tmp}/polydata-polygon-rpc-health}"
FAILURE_COUNT_FILE="${HEALTH_STATE_DIR}/consecutive-transport-failures"

if ! [[ "$RESTART_FAILURE_THRESHOLD" =~ ^[1-9][0-9]*$ ]] || (( RESTART_FAILURE_THRESHOLD > 100 )); then
  printf '[polygon-rpc-health] invalid restart failure threshold: %s\n' "$RESTART_FAILURE_THRESHOLD" >&2
  exit 64
fi

umask 077
mkdir -p "$HEALTH_STATE_DIR"

reset_transport_failures() {
  rm -f "$FAILURE_COUNT_FILE"
}

record_transport_failure() {
  local previous=0
  local next
  if [[ -f "$FAILURE_COUNT_FILE" ]]; then
    read -r previous < "$FAILURE_COUNT_FILE" || previous=0
  fi
  [[ "$previous" =~ ^[0-9]+$ ]] || previous=0
  next=$((previous + 1))
  printf '%s\n' "$next" > "${FAILURE_COUNT_FILE}.tmp"
  mv -f "${FAILURE_COUNT_FILE}.tmp" "$FAILURE_COUNT_FILE"
  printf '%s' "$next"
}

log() {
  printf '[polygon-rpc-health] %s\n' "$*" >&2
}

check_rpc() {
  POLYDATA_POLYGON_HEALTH_RPC_URL="$RPC_URL" \
  POLYDATA_POLYGON_HEALTH_MAX_LAG="$MAX_LAG_BLOCKS" \
  POLYDATA_POLYGON_HEALTH_TIMEOUT="$RPC_TIMEOUT_SECONDS" \
    python3 - <<'PY'
import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

rpc_url = os.environ["POLYDATA_POLYGON_HEALTH_RPC_URL"]
max_lag = max(0, int(os.environ["POLYDATA_POLYGON_HEALTH_MAX_LAG"]))
rpc_timeout = max(0.1, float(os.environ["POLYDATA_POLYGON_HEALTH_TIMEOUT"]))
parsed = urllib.parse.urlparse(rpc_url)
if parsed.scheme not in {"http", "https"}:
    raise SystemExit("Polygon RPC URL must use HTTP(S)")
if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
    raise SystemExit("Polygon RPC must use the local SSH tunnel")


def rpc(method):
    body = json.dumps(
        {"jsonrpc": "2.0", "method": method, "params": [], "id": 1}
    ).encode("utf-8")
    request = urllib.request.Request(
        rpc_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=rpc_timeout) as response:
            payload = json.load(response)
    except (TimeoutError, socket.timeout):
        print(f"{method} timed out while Bor may be busy", file=sys.stderr)
        raise SystemExit(77)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            print(f"{method} timed out while Bor may be busy", file=sys.stderr)
            raise SystemExit(77) from exc
        print(
            f"{method} transport failed: {type(exc.reason).__name__}",
            file=sys.stderr,
        )
        raise SystemExit(78) from exc
    if payload.get("error"):
        raise RuntimeError(f"{method} failed: {payload['error']}")
    return payload.get("result")


chain_id = int(str(rpc("eth_chainId")), 16)
if chain_id != 137:
    print(f"unexpected Polygon chain id: {chain_id}", file=sys.stderr)
    raise SystemExit(76)

client = str(rpc("web3_clientVersion") or "")
if "bor" not in client.lower():
    print("self-hosted RPC is not a Bor client", file=sys.stderr)
    raise SystemExit(76)

block_number = int(str(rpc("eth_blockNumber")), 16)
syncing = rpc("eth_syncing")
lag = 0
if isinstance(syncing, dict):
    current = int(str(syncing.get("currentBlock") or hex(block_number)), 16)
    highest = int(str(syncing.get("highestBlock") or hex(current)), 16)
    lag = max(0, highest - current)
if lag > max_lag:
    print(f"self-hosted Polygon node is stale: lag={lag} blocks", file=sys.stderr)
    raise SystemExit(75)

print(f"chain=137 client=bor block={block_number} lag={lag}")
PY
}

status=0
if check_rpc; then
  reset_transport_failures
  log "self-hosted Polygon RPC healthy"
  exit 0
else
  status=$?
fi

if (( status == 75 )); then
  # A reachable Bor node may legitimately trail mainnet while restoring or
  # crossing an upgrade. The indexers use their configured fallback until it
  # catches up, so report a degraded state without failing the systemd unit.
  reset_transport_failures
  log "DEGRADED_SYNCING: tunnel is healthy but the remote Bor node is still catching up; not restarting SSH"
  exit 0
fi
if (( status == 76 )); then
  reset_transport_failures
  log "remote endpoint is not Polygon Bor; refusing to restart-loop the tunnel"
  exit 1
fi
if (( status == 77 )); then
  # A long historical receipt/getter batch can keep Bor's HTTP worker busy for
  # more than the probe timeout. Restarting the SSH tunnel cannot repair that
  # remote load and instead destroys the in-flight integrity snapshot.
  reset_transport_failures
  log "DEGRADED_BUSY: Bor RPC probe timed out; tunnel left intact"
  exit 0
fi

failure_count="$(record_transport_failure)"
if (( failure_count < RESTART_FAILURE_THRESHOLD )); then
  log "TRANSIENT_TRANSPORT_FAILURE: ${failure_count}/${RESTART_FAILURE_THRESHOLD}; tunnel left intact"
  exit 0
fi

log "RPC transport failed ${failure_count} consecutive times; restarting ${TUNNEL_UNIT} once"
systemctl --user restart "$TUNNEL_UNIT"
sleep 3
reset_transport_failures
post_status=0
if check_rpc; then
  log "self-hosted Polygon RPC recovered"
  exit 0
else
  post_status=$?
fi
if (( post_status == 75 )); then
  log "self-hosted Polygon RPC transport recovered; node remains DEGRADED_SYNCING"
  exit 0
fi
if (( post_status == 77 )); then
  log "tunnel restarted but Bor RPC remains busy; no restart loop"
  exit 0
fi
exit "$post_status"
