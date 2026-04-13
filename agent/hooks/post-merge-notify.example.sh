#!/usr/bin/env bash
# Example git hook: after merge/pull, if the latest commit's first line starts with
# "[NOTIFY]", signal the Sentinel agent to run a scan immediately (skip the rest
# of scan_interval).
#
# Install (per repository, as root or the deploy user):
#   cp post-merge-notify.example.sh /var/www/your-app/.git/hooks/post-merge
#   chmod +x /var/www/your-app/.git/hooks/post-merge
#
# Requires: sentinel-agent running as a systemd service on this host.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
FIRST_LINE="$(git -C "$REPO_ROOT" log -1 --pretty=%s)"

if [[ "$FIRST_LINE" == "[NOTIFY]"* ]]; then
  if command -v systemctl &>/dev/null && systemctl is-active --quiet sentinel-agent 2>/dev/null; then
    systemctl kill -s SIGUSR1 sentinel-agent
  elif command -v pkill &>/dev/null; then
    pkill -USR1 -f 'python.*agent\.agent.*--mode service' || true
  fi
fi
