#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${POLYMONITOR_VENV_DIR:-${ROOT_DIR}/.venv}/bin/python"
RUFF_BIN="${POLYMONITOR_VENV_DIR:-${ROOT_DIR}/.venv}/bin/ruff"

if [[ ! -x "${PYTHON_BIN}" || ! -x "${RUFF_BIN}" ]]; then
  echo "Development environment is missing. Run scripts/dev/bootstrap.sh first." >&2
  exit 1
fi

cd "${ROOT_DIR}"
QA_CACHE_DIR="$(mktemp -d)"
trap 'rm -rf -- "${QA_CACHE_DIR}"' EXIT
export PYTHONPYCACHEPREFIX="${QA_CACHE_DIR}/pycache"
export PYTHONDONTWRITEBYTECODE=1

"${PYTHON_BIN}" "${ROOT_DIR}/scripts/qa/check_tracked_secrets.py"
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/qa/check_systemd_units.py"
"${PYTHON_BIN}" -m compileall -q \
  "${ROOT_DIR}/agent" \
  "${ROOT_DIR}/scripts" \
  "${ROOT_DIR}/telegram" \
  "${ROOT_DIR}/tests"

while IFS= read -r -d '' shell_file; do
  [[ -f "${ROOT_DIR}/${shell_file}" ]] || continue
  bash -n "${ROOT_DIR}/${shell_file}"
done < <(git -C "${ROOT_DIR}" ls-files -z "*.sh")

if command -v systemd-analyze >/dev/null 2>&1; then
  bash "${ROOT_DIR}/scripts/qa/verify_systemd_units.sh"
fi

"${RUFF_BIN}" check --no-cache \
  "${ROOT_DIR}/agent" \
  "${ROOT_DIR}/scripts" \
  "${ROOT_DIR}/telegram" \
  "${ROOT_DIR}/tests"
"${PYTHON_BIN}" -m pytest -q
npm --prefix "${ROOT_DIR}/webpage" audit --audit-level=high
npm --prefix "${ROOT_DIR}/webpage" run build

echo "Clean-checkout verification passed."
