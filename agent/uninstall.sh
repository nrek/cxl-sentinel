#!/usr/bin/env bash
set -euo pipefail

# CXL Sentinel Agent -- Uninstall Script
# Run as root: sudo bash uninstall.sh

SERVICE_NAME="sentinel-agent"
SERVICE_USER="sentinel"
INSTALL_DIR="/opt/sentinel"
CONFIG_DIR="/etc/sentinel"
STATE_DIR="/var/lib/sentinel"
LOG_DIR="/var/log/sentinel"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}[ERROR]${NC} This script must be run as root (sudo bash uninstall.sh)"
    exit 1
fi

# --- Stop and remove service ---

if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    log_info "Stopping $SERVICE_NAME service"
    systemctl stop "$SERVICE_NAME"
fi

if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    log_info "Disabling $SERVICE_NAME service"
    systemctl disable "$SERVICE_NAME"
fi

if [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
    log_info "Removing systemd unit file"
    rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    systemctl daemon-reload
fi

# --- Remove directories ---

if [[ -d "$INSTALL_DIR" ]]; then
    log_info "Removing $INSTALL_DIR"
    rm -rf "$INSTALL_DIR"
fi

if [[ -d "$CONFIG_DIR" ]]; then
    log_info "Removing $CONFIG_DIR"
    rm -rf "$CONFIG_DIR"
fi

if [[ -d "$STATE_DIR" ]]; then
    log_info "Removing $STATE_DIR"
    rm -rf "$STATE_DIR"
fi

# Preserve logs for review
if [[ -d "$LOG_DIR" ]]; then
    log_warn "Log directory preserved at $LOG_DIR (remove manually if desired)"
fi

# --- Remove system user ---

if id "$SERVICE_USER" &>/dev/null; then
    log_info "Removing system user: $SERVICE_USER"
    userdel "$SERVICE_USER" 2>/dev/null || true
fi

echo ""
log_info "Uninstall complete"
echo ""
