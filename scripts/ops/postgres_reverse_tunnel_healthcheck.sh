#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${POLYDATA_ENV_FILE:-$HOME/.config/polydata/polydata.env}"
TUNNEL_UNIT="${POLYDATA_TUNNEL_UNIT:-polydata-db-reverse-tunnel.service}"
EXPECTED_TUNNEL_UNIT="polydata-db-reverse-tunnel.service"
REMOTE_APP_DIR="${POLYDATA_REMOTE_APP_DIR:-/opt/polyData}"
FAILURE_THRESHOLD="${POLYDATA_TUNNEL_HEALTH_FAILURE_THRESHOLD:-3}"
RESTART_WINDOW_SECONDS="${POLYDATA_TUNNEL_HEALTH_RESTART_WINDOW_SECONDS:-1800}"
MAX_RESTARTS="${POLYDATA_TUNNEL_HEALTH_MAX_RESTARTS:-3}"
BACKOFF_SECONDS="${POLYDATA_TUNNEL_HEALTH_BACKOFF_SECONDS:-1800}"
LOCAL_STATE_DIR="${POLYDATA_OPERATIONS_LOCAL_STATE_DIR:-$HOME/.local/state/polydata-operations}"
RECOVERY_STATE="${LOCAL_STATE_DIR}/tunnel-recovery.json"
HEARTBEAT_FILE="${LOCAL_STATE_DIR}/tunnel-health.json"
REMOTE_HEARTBEAT_RELATIVE=".local/state/polydata-operations/tunnel-health.json"
PYTHON_BIN="${POLYDATA_PYTHON_BIN:-python3}"
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
  printf '[tunnel-health] %s\n' "$*" >&2
}

validate_positive_integer() {
  local name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    log "$name must be a positive integer"
    exit 2
  fi
}

configure_ssh_identity() {
  local identity="${POLYDATA_GCP_SSH_IDENTITY_FILE:-${POLYDATA_GCP_TUNNEL_HEALTH_SSH_IDENTITY_FILE:-${POLYDATA_GCP_TUNNEL_SSH_IDENTITY_FILE:-${POLYDATA_GCP_SSH_KEY_PATH:-}}}}"
  if [[ -n "$identity" ]]; then
    SSH_OPTS+=(-o IdentitiesOnly=yes -i "$identity")
  fi
}

remote_dependency_check() {
  local target="$1"
  local postgres_port="$2"
  local clickhouse_port="$3"
  timeout 30s ssh \
    "${SSH_OPTS[@]}" \
    "$target" \
    "cd '$REMOTE_APP_DIR' && POLYDATA_HEALTHCHECK_POSTGRES_PORT='$postgres_port' POLYDATA_HEALTHCHECK_CLICKHOUSE_PORT='$clickhouse_port' .venv/bin/python3 - <<'PY'
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import ProxyHandler, Request, build_opener

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
result = {'postgres': 'unhealthy', 'clickhouse': 'unknown'}

try:
    from scripts.db import db
    with db.get_db(readonly=True) as connection:
        row = connection.execute('SELECT 1').fetchone()
    if row and int(row[0]) == 1:
        result['postgres'] = 'healthy'
except Exception:
    pass

enabled = os.environ.get('POLYDATA_ORDERFILLED_CLICKHOUSE_READ_ENABLED', '0').lower() in {'1', 'true', 'yes', 'on'}
if not enabled:
    result['clickhouse'] = 'disabled'
else:
    try:
        raw_url = os.environ.get('POLYDATA_ORDERFILLED_CLICKHOUSE_HTTP_URL', '')
        parsed = urlsplit(raw_url)
        port = int(os.environ.get('POLYDATA_HEALTHCHECK_CLICKHOUSE_PORT', '18123'))
        url = urlunsplit((parsed.scheme or 'http', f'127.0.0.1:{port}', parsed.path, '', ''))
        headers = {'Content-Type': 'text/plain'}
        user = os.environ.get('POLYDATA_ORDERFILLED_CLICKHOUSE_USER')
        password = os.environ.get('CLICKHOUSE_PASSWORD')
        if user:
            headers['X-ClickHouse-User'] = user
        if password:
            headers['X-ClickHouse-Key'] = password
        request = Request(url, data=b'SELECT 1 FORMAT TabSeparated', headers=headers, method='POST')
        response = build_opener(ProxyHandler({})).open(request, timeout=8)
        try:
            if int(getattr(response, 'status', 200)) == 200 and response.read(64).strip() == b'1':
                result['clickhouse'] = 'healthy'
            else:
                result['clickhouse'] = 'unhealthy'
        finally:
            response.close()
    except Exception:
        result['clickhouse'] = 'unhealthy'

print(json.dumps(result, separators=(',', ':')))
ok = result['postgres'] == 'healthy' and result['clickhouse'] in {'healthy', 'disabled'}
raise SystemExit(0 if ok else 1)
PY"
}

dependency_status() {
  local payload="$1"
  local key="$2"
  "$PYTHON_BIN" - "$payload" "$key" <<'PY'
import json
import sys

try:
    payload = json.loads(sys.argv[1])
    value = str(payload.get(sys.argv[2], 'unknown'))
except Exception:
    value = 'unknown'
print(value if value in {'healthy', 'unhealthy', 'unknown', 'disabled'} else 'unknown')
PY
}

update_recovery_state() {
  local action="$1"
  mkdir -p "$LOCAL_STATE_DIR"
  chmod 700 "$LOCAL_STATE_DIR"
  "$PYTHON_BIN" - "$RECOVERY_STATE" "$action" "$FAILURE_THRESHOLD" "$RESTART_WINDOW_SECONDS" "$MAX_RESTARTS" "$BACKOFF_SECONDS" <<'PY'
import json
import os
import sys
import tempfile
import time
from pathlib import Path

path = Path(sys.argv[1])
action = sys.argv[2]
threshold, window, maximum, backoff = map(int, sys.argv[3:])
now = int(time.time())
try:
    state = json.loads(path.read_text())
    if not isinstance(state, dict):
        state = {}
except Exception:
    state = {}
state.setdefault('consecutiveFailures', 0)
state.setdefault('restartAttempts', [])
state.setdefault('backoffUntil', 0)
state['restartAttempts'] = [
    int(value) for value in state['restartAttempts']
    if now - int(value) < window
]
decision = 'none'
if action == 'success':
    state['consecutiveFailures'] = 0
    state['lastSuccessAt'] = now
elif action == 'failure':
    state['consecutiveFailures'] = int(state['consecutiveFailures']) + 1
    state['lastFailureAt'] = now
    if now < int(state['backoffUntil']):
        decision = 'backoff'
    elif int(state['consecutiveFailures']) < threshold:
        decision = 'wait'
    elif len(state['restartAttempts']) >= maximum:
        state['backoffUntil'] = now + backoff
        state['consecutiveFailures'] = 0
        decision = 'backoff'
    else:
        state['restartAttempts'].append(now)
        state['consecutiveFailures'] = 0
        state['lastRestartAt'] = now
        state['backoffUntil'] = 0
        decision = 'restart'
state['lastDecision'] = decision
path.parent.mkdir(parents=True, exist_ok=True)
descriptor, temporary_name = tempfile.mkstemp(prefix='.tunnel-recovery.', dir=str(path.parent))
with os.fdopen(descriptor, 'w') as handle:
    json.dump(state, handle, sort_keys=True, separators=(',', ':'))
    handle.write('\n')
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(temporary_name, 0o600)
os.replace(temporary_name, path)
print(decision)
PY
}

build_heartbeat() {
  local overall="$1"
  local postgres="$2"
  local clickhouse="$3"
  local unit_status="$4"
  "$PYTHON_BIN" - "$RECOVERY_STATE" "$overall" "$postgres" "$clickhouse" "$unit_status" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    recovery = json.loads(Path(sys.argv[1]).read_text())
except Exception:
    recovery = {}
payload = {
    'schemaVersion': 'polymonitor.tunnel-heartbeat.v1',
    'observedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
    'status': sys.argv[2],
    'postgres': sys.argv[3],
    'clickhouse': sys.argv[4],
    'unit': sys.argv[5],
    'recovery': {
        'decision': recovery.get('lastDecision', 'none'),
        'consecutiveFailures': int(recovery.get('consecutiveFailures') or 0),
        'restartAttemptsInWindow': len(recovery.get('restartAttempts') or []),
        'backoffUntilEpoch': int(recovery.get('backoffUntil') or 0),
    },
}
print(json.dumps(payload, sort_keys=True, separators=(',', ':')))
PY
}

write_local_heartbeat() {
  local payload="$1"
  "$PYTHON_BIN" - "$HEARTBEAT_FILE" "$payload" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(sys.argv[2])
path.parent.mkdir(parents=True, exist_ok=True)
descriptor, temporary_name = tempfile.mkstemp(prefix='.tunnel-heartbeat.', dir=str(path.parent))
with os.fdopen(descriptor, 'w') as handle:
    json.dump(payload, handle, sort_keys=True, separators=(',', ':'))
    handle.write('\n')
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(temporary_name, 0o600)
os.replace(temporary_name, path)
PY
}

publish_remote_heartbeat() {
  local target="$1"
  local payload="$2"
  printf '%s\n' "$payload" | timeout 15s ssh "${SSH_OPTS[@]}" "$target" \
    "umask 077; mkdir -p \"\$HOME/.local/state/polydata-operations\"; temporary=\"\$HOME/${REMOTE_HEARTBEAT_RELATIVE}.tmp\"; cat > \"\$temporary\"; mv \"\$temporary\" \"\$HOME/${REMOTE_HEARTBEAT_RELATIVE}\"" \
    >/dev/null 2>&1
}

restart_tunnel() {
  if [[ "$TUNNEL_UNIT" != "$EXPECTED_TUNNEL_UNIT" ]]; then
    log "refusing recovery for non-allowlisted unit"
    return 1
  fi
  systemctl --user restart "$EXPECTED_TUNNEL_UNIT"
}

record_and_publish() {
  local target="$1"
  local overall="$2"
  local postgres="$3"
  local clickhouse="$4"
  local unit_status="$5"
  local heartbeat
  heartbeat="$(build_heartbeat "$overall" "$postgres" "$clickhouse" "$unit_status")"
  write_local_heartbeat "$heartbeat"
  if ! publish_remote_heartbeat "$target" "$heartbeat"; then
    log "remote heartbeat publish unavailable"
  fi
}

main() {
  load_env_file "$ENV_FILE"
  configure_ssh_identity
  validate_positive_integer POLYDATA_TUNNEL_HEALTH_FAILURE_THRESHOLD "$FAILURE_THRESHOLD"
  validate_positive_integer POLYDATA_TUNNEL_HEALTH_RESTART_WINDOW_SECONDS "$RESTART_WINDOW_SECONDS"
  validate_positive_integer POLYDATA_TUNNEL_HEALTH_MAX_RESTARTS "$MAX_RESTARTS"
  validate_positive_integer POLYDATA_TUNNEL_HEALTH_BACKOFF_SECONDS "$BACKOFF_SECONDS"

  local target="${POLYDATA_GCP_SSH_TARGET:-${POLYDATA_GCP_TUNNEL_HEALTH_SSH_TARGET:-${POLYDATA_GCP_TUNNEL_SSH_TARGET:-}}}"
  local postgres_port="${POLYDATA_REMOTE_POSTGRES_PORT:-45432}"
  local clickhouse_port="${POLYDATA_REMOTE_CLICKHOUSE_HTTP_PORT:-${POLYDATA_REMOTE_CLICKHOUSE_PORT:-18123}}"
  if [[ -z "$target" ]]; then
    log "no supported GCP SSH target is configured; no remote probe performed"
    exit 1
  fi

  local result=""
  local check_exit=0
  local unit_status="unhealthy"
  if systemctl --user is-active --quiet "$EXPECTED_TUNNEL_UNIT"; then
    unit_status="healthy"
  fi
  set +e
  result="$(remote_dependency_check "$target" "$postgres_port" "$clickhouse_port" 2>/dev/null)"
  check_exit=$?
  set -e
  local postgres
  local clickhouse
  postgres="$(dependency_status "$result" postgres)"
  clickhouse="$(dependency_status "$result" clickhouse)"

  if (( check_exit == 0 )) && [[ "$unit_status" == "healthy" ]]; then
    update_recovery_state success >/dev/null
    record_and_publish "$target" healthy "$postgres" "$clickhouse" "$unit_status"
    log "remote PostgreSQL and ClickHouse tunnel probes healthy"
    exit 0
  fi

  local decision
  decision="$(update_recovery_state failure)"
  record_and_publish "$target" unhealthy "$postgres" "$clickhouse" "$unit_status"
  if [[ "$decision" == "wait" ]]; then
    log "dependency probe failed; waiting for consecutive failure threshold"
    exit 0
  fi
  if [[ "$decision" == "backoff" ]]; then
    log "dependency probe failed; recovery suppressed by restart budget/backoff"
    exit 1
  fi
  if [[ "$decision" != "restart" ]]; then
    log "dependency probe failed; no recovery decision"
    exit 1
  fi

  log "restarting allowlisted reverse tunnel after confirmed failures"
  restart_tunnel
  sleep 4
  unit_status="unhealthy"
  if systemctl --user is-active --quiet "$EXPECTED_TUNNEL_UNIT"; then
    unit_status="healthy"
  fi

  set +e
  result="$(remote_dependency_check "$target" "$postgres_port" "$clickhouse_port" 2>/dev/null)"
  check_exit=$?
  set -e
  postgres="$(dependency_status "$result" postgres)"
  clickhouse="$(dependency_status "$result" clickhouse)"
  if (( check_exit == 0 )) && [[ "$unit_status" == "healthy" ]]; then
    update_recovery_state success >/dev/null
    record_and_publish "$target" healthy "$postgres" "$clickhouse" "$unit_status"
    log "reverse tunnel recovered"
    exit 0
  fi

  record_and_publish "$target" unhealthy "$postgres" "$clickhouse" "$unit_status"
  log "reverse tunnel remains unhealthy after bounded recovery"
  exit 1
}

main "$@"
