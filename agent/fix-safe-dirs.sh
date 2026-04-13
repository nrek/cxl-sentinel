#!/usr/bin/env bash
set -euo pipefail

# CXL Sentinel — register monitored repo paths as git safe.directory (system-wide).
#
# The sentinel agent runs as an unprivileged user that does not own the git
# repos it monitors.  Git 2.35+ blocks operations in repos owned by another
# user unless the path is listed in safe.directory.
#
# This script:
#   1. Reads the agent YAML config (default: /etc/sentinel/agent.yaml)
#   2. Extracts every repos[].path entry
#   3. Resolves symlinks to the canonical path (readlink -f)
#   4. Adds each path to git config --system safe.directory (idempotent)
#
# Usage:
#   sudo bash agent/fix-safe-dirs.sh                          # default config
#   sudo bash agent/fix-safe-dirs.sh /etc/sentinel/agent.yaml # explicit path
#
# Safe to re-run — duplicates are skipped.

CONFIG="${1:-/etc/sentinel/agent.yaml}"
VENV_PY="/opt/sentinel/venv/bin/python"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (sudo bash fix-safe-dirs.sh)"
    exit 1
fi

if [[ ! -f "$CONFIG" ]]; then
    log_error "Config not found: $CONFIG"
    exit 1
fi

# Use the agent's own venv Python (has pyyaml) to extract repo paths.
# Falls back to system python3 with a regex if the venv is missing.
if [[ -x "$VENV_PY" ]]; then
    PYTHON="$VENV_PY"
else
    PYTHON="python3"
fi

PATHS=$("$PYTHON" -c "
import yaml, sys
with open('$CONFIG') as f:
    cfg = yaml.safe_load(f)
for r in cfg.get('repos', []):
    p = r.get('path', '')
    if p:
        print(p)
" 2>/dev/null) || true

if [[ -z "$PATHS" ]]; then
    log_warn "No repo paths found in $CONFIG — nothing to register"
    exit 0
fi

# Collect what is already registered
EXISTING=$(git config --system --get-all safe.directory 2>/dev/null || true)

ADDED=0
while IFS= read -r raw_path; do
    # Resolve symlinks; fall back to raw path if readlink fails (path may not exist yet)
    canonical=$(readlink -f "$raw_path" 2>/dev/null || echo "$raw_path")

    # Skip if already present (check both raw and canonical)
    if echo "$EXISTING" | grep -qxF "$canonical" 2>/dev/null; then
        log_info "Already registered: $canonical"
        continue
    fi
    if [[ "$canonical" != "$raw_path" ]] && echo "$EXISTING" | grep -qxF "$raw_path" 2>/dev/null; then
        log_info "Already registered (raw path): $raw_path"
        continue
    fi

    git config --system --add safe.directory "$canonical"
    log_info "Added safe.directory: $canonical"
    ADDED=$((ADDED + 1))
done <<< "$PATHS"

if [[ $ADDED -gt 0 ]]; then
    log_info "Registered $ADDED new safe.directory entries in /etc/gitconfig"
else
    log_info "All repo paths were already registered"
fi
