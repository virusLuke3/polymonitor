#!/usr/bin/env bash
set -euo pipefail

if [[ "${POLYDATA_POLYGON_RPC_ASKPASS:-0}" == "1" ]]; then
  printf '%s\n' "${POLYDATA_POLYGON_RPC_SSH_PASSWORD:-${ssh_pwd:-}}"
  exit 0
fi

local_port="${POLYDATA_POLYGON_RPC_LOCAL_PORT:-28545}"
remote_port="${POLYDATA_POLYGON_RPC_REMOTE_PORT:-18545}"
target="${POLYDATA_POLYGON_RPC_SSH_TARGET:-}"
identity_file="${POLYDATA_POLYGON_RPC_SSH_IDENTITY_FILE:-}"
password="${POLYDATA_POLYGON_RPC_SSH_PASSWORD:-${ssh_pwd:-}}"

if [[ -n "${ssh_ip:-}" && -n "${ssh_user:-}" ]]; then
  target="${ssh_user}@${ssh_ip}"
fi
if [[ -z "$target" ]]; then
  echo "Polygon RPC SSH target is not configured" >&2
  exit 78
fi

ssh_args=(
  -N
  -L "127.0.0.1:${local_port}:127.0.0.1:${remote_port}"
  -o ConnectTimeout=10
  -o ConnectionAttempts=1
  -o ExitOnForwardFailure=yes
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=2
  -o TCPKeepAlive=yes
  -o IPQoS=none
  -o KexAlgorithms=curve25519-sha256
  -o StrictHostKeyChecking=accept-new
)

if [[ -n "$password" ]]; then
  export POLYDATA_POLYGON_RPC_SSH_PASSWORD="$password"
  export POLYDATA_POLYGON_RPC_ASKPASS=1
  export SSH_ASKPASS="$0"
  export SSH_ASKPASS_REQUIRE=force
  export DISPLAY="${DISPLAY:-:0}"
  ssh_args+=(
    -o BatchMode=no
    -o PreferredAuthentications=password,keyboard-interactive
    -o PubkeyAuthentication=no
    -o NumberOfPasswordPrompts=1
  )
  exec setsid -w ssh "${ssh_args[@]}" "$target"
fi

if [[ -z "$identity_file" ]]; then
  echo "Polygon RPC SSH identity file or password is required" >&2
  exit 78
fi
ssh_args+=(
  -i "$identity_file"
  -o BatchMode=yes
  -o IdentitiesOnly=yes
)
exec ssh "${ssh_args[@]}" "$target"
