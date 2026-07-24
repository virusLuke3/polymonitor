#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${POLYDATA_ENV_FILE:-$HOME/.config/polydata/polydata.env}"
TUNNEL_UNIT="${POLYDATA_TUNNEL_UNIT:-polydata-db-reverse-tunnel.service}"
REMOTE_APP_DIR="${POLYDATA_REMOTE_APP_DIR:-/opt/polyData}"
FAILURE_THRESHOLD="${POLYDATA_TUNNEL_HEALTH_FAILURE_THRESHOLD:-3}"
STATE_DIR="${XDG_RUNTIME_DIR:-/tmp}/polydata-db-reverse-tunnel-healthcheck"
FAILURE_FILE="${STATE_DIR}/consecutive-failures"
SSH_OPTS=(
  -o BatchMode=yes
  -o ConnectTimeout=8
  -o ConnectionAttempts=1
  -o IPQoS=none
  -o KexAlgorithms=curve25519-sha256
)

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

log() {
  printf '[postgres-tunnel-health] %s\n' "$*" >&2
}

remote_pg_check() {
  local target="$1"
  local port="$2"
  timeout 25s ssh \
    "${SSH_OPTS[@]}" \
    "$target" \
    "cd '$REMOTE_APP_DIR' && POLYDATA_HEALTHCHECK_POSTGRES_PORT='$port' .venv/bin/python3 - <<'PY'
import os
from pathlib import Path

env_path = Path.home() / '.config' / 'polydata' / 'polydata.env'
if env_path.exists():
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('\"')
        if key and key not in os.environ:
            os.environ[key] = value

os.environ['POLYDATA_POSTGRES_HOST'] = '127.0.0.1'
os.environ['POLYDATA_POSTGRES_PORT'] = os.environ.get('POLYDATA_HEALTHCHECK_POSTGRES_PORT', '45432')

from scripts.db import db

with db.get_db(readonly=True) as conn:
    row = conn.execute('SELECT 1').fetchone()
    if not row or int(row[0]) != 1:
        raise SystemExit('unexpected PostgreSQL healthcheck result')
PY"
}

restart_tunnel() {
  log "restarting $TUNNEL_UNIT after failed remote PostgreSQL check"
  systemctl --user restart "$TUNNEL_UNIT"
}

record_failure() {
  local failures=0
  mkdir -p "$STATE_DIR"
  if [[ -f "$FAILURE_FILE" ]]; then
    read -r failures < "$FAILURE_FILE" || failures=0
  fi
  [[ "$failures" =~ ^[0-9]+$ ]] || failures=0
  failures=$((failures + 1))
  printf '%s\n' "$failures" > "$FAILURE_FILE"
  printf '%s\n' "$failures"
}

clear_failures() {
  rm -f "$FAILURE_FILE"
}

main() {
  load_env_file "$ENV_FILE"
  local target="${POLYDATA_GCP_SSH_TARGET:-}"
  local remote_port="${POLYDATA_REMOTE_POSTGRES_PORT:-45432}"
  if [[ -z "$target" ]]; then
    log "POLYDATA_GCP_SSH_TARGET is not set; skipping"
    exit 0
  fi

  if remote_pg_check "$target" "$remote_port"; then
    clear_failures
    log "remote PostgreSQL tunnel healthy"
    exit 0
  fi

  local failures
  failures=$(record_failure)
  if (( failures < FAILURE_THRESHOLD )); then
    log "remote PostgreSQL check failed (${failures}/${FAILURE_THRESHOLD}); keeping the current tunnel"
    exit 0
  fi

  restart_tunnel
  sleep 4

  if remote_pg_check "$target" "$remote_port"; then
    clear_failures
    log "remote PostgreSQL tunnel recovered"
    exit 0
  fi

  log "remote PostgreSQL tunnel still unhealthy after restart"
  exit 1
}

main "$@"
