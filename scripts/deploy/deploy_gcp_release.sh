#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEPLOY_HOST="${DEPLOY_HOST:-}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"
DEPLOY_USER="${DEPLOY_USER:-}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/polyData}"
DEPLOY_TARGET_SHA="${DEPLOY_TARGET_SHA:-HEAD}"
DEPLOY_RESTART_UNITS="${DEPLOY_RESTART_UNITS:-polydata-api.service}"
DEPLOY_STATE_DIR="${DEPLOY_STATE_DIR:-.local/state/polydata-deploy}"
DEPLOY_DRY_RUN="${DEPLOY_DRY_RUN:-0}"
DEPLOY_SSH_KEY="${DEPLOY_SSH_KEY:-}"
DEPLOY_INSTALL_DEPENDENCIES="${DEPLOY_INSTALL_DEPENDENCIES:-1}"

: "${DEPLOY_HOST:?Set DEPLOY_HOST}"
: "${DEPLOY_USER:?Set DEPLOY_USER}"

read -r -a RESTART_UNITS <<< "${DEPLOY_RESTART_UNITS}"
if [[ "${#RESTART_UNITS[@]}" -eq 0 ]]; then
  echo "At least one GCP restart unit is required." >&2
  exit 1
fi
for unit in "${RESTART_UNITS[@]}"; do
  if [[ ! "${unit}" =~ ^polydata-[a-zA-Z0-9@_.-]+\.(service|timer|target)$ ]]; then
    echo "Refusing invalid restart unit: ${unit}" >&2
    exit 1
  fi
done

SSH_OPTIONS=(
  -p "${DEPLOY_PORT}"
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=yes
)
SCP_OPTIONS=(
  -P "${DEPLOY_PORT}"
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=yes
)
if [[ -n "${DEPLOY_SSH_KEY}" ]]; then
  SSH_OPTIONS+=(-i "${DEPLOY_SSH_KEY}")
  SCP_OPTIONS+=(-i "${DEPLOY_SSH_KEY}")
fi
REMOTE="${DEPLOY_USER}@${DEPLOY_HOST}"
TARGET_SHA="$(git -C "${ROOT_DIR}" rev-parse "${DEPLOY_TARGET_SHA}^{commit}")"
REMOTE_STATE_PATH="${DEPLOY_STATE_DIR}/current.json"

BASE_SHA="$(
  ssh "${SSH_OPTIONS[@]}" "${REMOTE}" \
    "if test -f '${REMOTE_STATE_PATH}'; then python3 -c 'import json; print(json.load(open(\"${REMOTE_STATE_PATH}\"))[\"target_sha\"])'; else git -C '${DEPLOY_PATH}' rev-parse HEAD; fi"
)"
git -C "${ROOT_DIR}" merge-base --is-ancestor "${BASE_SHA}" "${TARGET_SHA}" || {
  echo "Remote base ${BASE_SHA} is not an ancestor of target ${TARGET_SHA}." >&2
  exit 1
}

RELEASE_DIR="$(mktemp -d)"
REMOTE_RELEASE_DIR=""
cleanup() {
  rm -rf -- "${RELEASE_DIR}"
  if [[ -n "${REMOTE_RELEASE_DIR}" ]]; then
    ssh "${SSH_OPTIONS[@]}" "${REMOTE}" "rm -rf -- '${REMOTE_RELEASE_DIR}'" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
python3 "${ROOT_DIR}/scripts/deploy/gcp_release.py" build \
  --repo "${ROOT_DIR}" \
  --base "${BASE_SHA}" \
  --target "${TARGET_SHA}" \
  --output "${RELEASE_DIR}/release"

ENTRY_COUNT="$(
  python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["entries"]))' \
    "${RELEASE_DIR}/release/manifest.json"
)"
if [[ "${ENTRY_COUNT}" == "0" ]]; then
  echo "No GCP backend files changed between ${BASE_SHA:0:12} and ${TARGET_SHA:0:12}."
  exit 0
fi

REMOTE_RELEASE_DIR="/tmp/polydata-release-${TARGET_SHA}"
ssh "${SSH_OPTIONS[@]}" "${REMOTE}" "mkdir -p '${REMOTE_RELEASE_DIR}'"
scp "${SCP_OPTIONS[@]}" \
  "${ROOT_DIR}/scripts/deploy/gcp_release.py" \
  "${RELEASE_DIR}/release/manifest.json" \
  "${RELEASE_DIR}/release/payload.tar.gz" \
  "${REMOTE}:${REMOTE_RELEASE_DIR}/"

ssh "${SSH_OPTIONS[@]}" "${REMOTE}" \
  "python3 '${REMOTE_RELEASE_DIR}/gcp_release.py' preflight --root '${DEPLOY_PATH}' --manifest '${REMOTE_RELEASE_DIR}/manifest.json'"

if [[ "${DEPLOY_DRY_RUN}" == "1" ]]; then
  echo "GCP backend dry-run passed for ${TARGET_SHA:0:12}; no files or services changed."
  exit 0
fi

RECEIPT_PATH="$(
  ssh "${SSH_OPTIONS[@]}" "${REMOTE}" \
    "python3 '${REMOTE_RELEASE_DIR}/gcp_release.py' apply \
      --root '${DEPLOY_PATH}' \
      --manifest '${REMOTE_RELEASE_DIR}/manifest.json' \
      --payload '${REMOTE_RELEASE_DIR}/payload.tar.gz' \
      --backup-root '${DEPLOY_STATE_DIR}/backups'" \
    | sed -n 's/^release-applied receipt=//p'
)"
if [[ -z "${RECEIPT_PATH}" ]]; then
  echo "Remote apply did not return a receipt." >&2
  exit 1
fi

rollback() {
  echo "Deployment verification failed; rolling back ${TARGET_SHA:0:12}." >&2
  ssh "${SSH_OPTIONS[@]}" "${REMOTE}" \
    "python3 '${REMOTE_RELEASE_DIR}/gcp_release.py' rollback --root '${DEPLOY_PATH}' --receipt '${RECEIPT_PATH}'" || true
  sync_systemd_units || true
  for unit in "${RESTART_UNITS[@]}"; do
    ssh "${SSH_OPTIONS[@]}" "${REMOTE}" "systemctl --user restart '${unit}'" || true
  done
}
trap rollback ERR

SYSTEMD_PATHS="$(
  python3 -c '
import json, sys
for entry in json.load(open(sys.argv[1]))["entries"]:
    path = entry["path"]
    if path.startswith("deploy/systemd/") and entry["action"] == "upsert":
        print(path)
' "${RELEASE_DIR}/release/manifest.json"
)"
sync_systemd_units() {
  if [[ -z "${SYSTEMD_PATHS}" ]]; then
    return
  fi
  while IFS= read -r path; do
    unit="${path##*/}"
    ssh "${SSH_OPTIONS[@]}" "${REMOTE}" \
      "mkdir -p ~/.config/systemd/user; sed 's|/__POLYDATA_REPO_ROOT__|${DEPLOY_PATH}|g' '${DEPLOY_PATH}/${path}' > ~/.config/systemd/user/'${unit}'"
  done <<< "${SYSTEMD_PATHS}"
  ssh "${SSH_OPTIONS[@]}" "${REMOTE}" "systemctl --user daemon-reload"
}
sync_systemd_units

if [[ "${DEPLOY_INSTALL_DEPENDENCIES}" == "1" ]] && python3 -c '
import json, sys
paths = {entry["path"] for entry in json.load(open(sys.argv[1]))["entries"]}
raise SystemExit(0 if "scripts/requirements.lock.txt" in paths else 1)
' "${RELEASE_DIR}/release/manifest.json"; then
  ssh "${SSH_OPTIONS[@]}" "${REMOTE}" \
    "'${DEPLOY_PATH}/.venv/bin/python' -m pip install -r '${DEPLOY_PATH}/scripts/requirements.lock.txt'"
fi

for unit in "${RESTART_UNITS[@]}"; do
  ssh "${SSH_OPTIONS[@]}" "${REMOTE}" "systemctl --user restart '${unit}'"
done

REMOTE_RESTART_UNITS="${RESTART_UNITS[*]}"
ssh "${SSH_OPTIONS[@]}" "${REMOTE}" "
  set -eu
  healthy=0
  for attempt in \$(seq 1 30); do
    if curl -fsS --max-time 10 http://127.0.0.1:18500/health >/dev/null \
      && curl -fsS --max-time 15 'http://127.0.0.1:18500/content/latest?limit=1' >/dev/null \
      && curl -fsS --max-time 10 http://127.0.0.1/wm-api/health >/dev/null; then
      healthy=1
      break
    fi
    sleep 2
  done
  test \"\$healthy\" = 1
  for unit in ${REMOTE_RESTART_UNITS}; do
    systemctl --user is-active --quiet \"\$unit\"
  done
"

STATE_JSON="$(
  python3 -c 'import json,sys; print(json.dumps({"base_sha": sys.argv[1], "target_sha": sys.argv[2]}))' \
    "${BASE_SHA}" "${TARGET_SHA}"
)"
ssh "${SSH_OPTIONS[@]}" "${REMOTE}" "
  set -eu
  mkdir -p '${DEPLOY_STATE_DIR}'
  umask 077
  printf '%s\n' '${STATE_JSON}' > '${REMOTE_STATE_PATH}'
"
trap - ERR
echo "GCP backend release ${TARGET_SHA:0:12} deployed and verified."
