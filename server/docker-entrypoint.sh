#!/bin/sh
set -eu

key_dir="${BIBLEIT_DATA_DIR}/ssh"
host_key="${BIBLEIT_SSH_HOST_KEY:-${key_dir}/ssh_host_ed25519_key}"

mkdir -p "$key_dir"
if [ ! -f "$host_key" ]; then
    ssh-keygen -q -t ed25519 -N '' -f "$host_key"
fi

export BIBLEIT_SSH_SYSTEM_DIR="${BIBLEIT_SSH_SYSTEM_DIR:-$key_dir}"
exec /app/bin/bibleit_server foreground
