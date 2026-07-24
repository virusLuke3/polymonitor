#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${POLYMONITOR_VENV_DIR:-${ROOT_DIR}/.venv}"

expected_python="$(tr -d '[:space:]' < "${ROOT_DIR}/.python-version")"
actual_python="$("${PYTHON_BIN}" -c 'import platform; print(platform.python_version())')"
if [[ "${actual_python}" != "${expected_python}" ]]; then
  echo "Expected Python ${expected_python}, found ${actual_python} at ${PYTHON_BIN}" >&2
  exit 1
fi
if ! "${PYTHON_BIN}" -c "import ensurepip" >/dev/null 2>&1; then
  echo "Python venv support is missing. Install python3.10-venv and rerun bootstrap." >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is required. Install the version from .nvmrc." >&2
  exit 1
fi
expected_node="$(tr -d '[:space:]' < "${ROOT_DIR}/.nvmrc")"
actual_node="$(node --version | sed 's/^v//')"
if [[ "${actual_node}" != "${expected_node}" ]]; then
  echo "Expected Node ${expected_node}, found ${actual_node}. Run: nvm use" >&2
  exit 1
fi

"${PYTHON_BIN}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade "pip==25.3"
"${VENV_DIR}/bin/python" -m pip install -r "${ROOT_DIR}/scripts/requirements-dev.lock.txt"
npm --prefix "${ROOT_DIR}/webpage" ci

echo "Bootstrap complete."
echo "Python: ${VENV_DIR}/bin/python"
echo "Node: $(node --version)"
