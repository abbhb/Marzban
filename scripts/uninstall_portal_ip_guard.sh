#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this uninstaller as root." >&2
  exit 1
fi

systemctl disable --now marzban-portal-ip-guard.service 2>/dev/null || true

if command -v nft >/dev/null && nft list table inet marzban_portal_guard >/dev/null 2>&1; then
  nft delete table inet marzban_portal_guard
fi

rm -f /etc/systemd/system/marzban-portal-ip-guard.service
rm -f /etc/default/marzban-portal-ip-guard
rm -f /usr/local/libexec/marzban-portal-ip-guard
systemctl daemon-reload
systemctl reset-failed marzban-portal-ip-guard.service 2>/dev/null || true
