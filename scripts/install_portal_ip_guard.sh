#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "${script_dir}/.." && pwd)"
database_path="${DATABASE_PATH:-/root/marzban/data/db.sqlite3}"
panel_port="${PANEL_PORT:-443}"
sync_interval="${SYNC_INTERVAL:-15}"

if [[ ! "${panel_port}" =~ ^[1-9][0-9]*$ ]] || (( panel_port > 65535 )); then
  echo "PANEL_PORT must be an integer between 1 and 65535." >&2
  exit 1
fi
if [[ ! "${sync_interval}" =~ ^[1-9][0-9]*$ ]] || (( sync_interval > 3600 )); then
  echo "SYNC_INTERVAL must be an integer between 1 and 3600." >&2
  exit 1
fi

command -v nft >/dev/null
command -v python3 >/dev/null
command -v systemctl >/dev/null
test -r "${database_path}"

install -d -m 0755 /usr/local/libexec
install -m 0700 "${script_dir}/portal_ip_guard.py" /usr/local/libexec/marzban-portal-ip-guard
install -m 0644 "${repo_dir}/systemd/marzban-portal-ip-guard.service" /etc/systemd/system/marzban-portal-ip-guard.service

umask 0077
{
  printf 'DATABASE_PATH=%q\n' "${database_path}"
  printf 'PANEL_PORT=%q\n' "${panel_port}"
  printf 'SYNC_INTERVAL=%q\n' "${sync_interval}"
} > /etc/default/marzban-portal-ip-guard

systemctl daemon-reload
systemctl enable --now marzban-portal-ip-guard.service
systemctl --no-pager --full status marzban-portal-ip-guard.service
