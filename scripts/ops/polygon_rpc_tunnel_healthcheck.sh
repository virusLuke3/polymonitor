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

log() {
  printf '[polygon-rpc-health] %s\n' "$*" >&2
}

check_rpc() {
  POLYDATA_POLYGON_HEALTH_RPC_URL="$RPC_URL" \
  POLYDATA_POLYGON_HEALTH_MAX_LAG="$MAX_LAG_BLOCKS" \
    python3 - <<'PY'
import json
import os
import sys
import urllib.parse
import urllib.request

rpc_url = os.environ["POLYDATA_POLYGON_HEALTH_RPC_URL"]
max_lag = max(0, int(os.environ["POLYDATA_POLYGON_HEALTH_MAX_LAG"]))
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
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.load(response)
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
  log "self-hosted Polygon RPC healthy"
  exit 0
else
  status=$?
fi

if (( status == 75 )); then
  log "tunnel is healthy but the remote Bor node is stale; not restarting SSH"
  exit 1
fi
if (( status == 76 )); then
  log "remote endpoint is not Polygon Bor; refusing to restart-loop the tunnel"
  exit 1
fi

log "RPC check failed; restarting ${TUNNEL_UNIT} once"
systemctl --user restart "$TUNNEL_UNIT"
sleep 3
check_rpc
log "self-hosted Polygon RPC recovered"
