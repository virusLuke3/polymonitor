#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_SOURCE_DIR="${ROOT_DIR}/deploy/systemd"
RENDERED_DIR="$(mktemp -d)"
trap 'rm -rf -- "${RENDERED_DIR}"' EXIT

while IFS= read -r -d '' source; do
  unit="${source##*/}"
  sed \
    -e "s|/__POLYDATA_REPO_ROOT__|${ROOT_DIR}|g" \
    -e "s|%h/develop/polymarket/githubProjects/polymonitor|${ROOT_DIR}|g" \
    "${source}" > "${RENDERED_DIR}/${unit}"
done < <(
  find "${UNIT_SOURCE_DIR}" -maxdepth 1 -type f \
    \( -name '*.service' -o -name '*.timer' -o -name '*.target' \) \
    -print0
)

SYSTEMD_UNIT_PATH="${RENDERED_DIR}:/usr/lib/systemd/system" \
  systemd-analyze verify \
  "${RENDERED_DIR}"/*.service \
  "${RENDERED_DIR}"/*.timer \
  "${RENDERED_DIR}"/*.target
