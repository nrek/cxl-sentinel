#!/usr/bin/env bash
set -euo pipefail

# CXL Sentinel Agent -- Install Script
# Run as root: sudo bash install.sh
#
# This script:
#   1. Creates the sentinel system user
#   2. Creates required directories
#   3. Copies agent code to /opt/sentinel/
#   4. Creates a Python venv and installs dependencies
#   5. Copies example config if no config exists
#   6. Installs the systemd unit file
#   7. Sets file permissions

INSTALL_DIR="/opt/sentinel"
CONFIG_DIR="/etc/sentinel"
LOG_DIR="/var/log/sentinel"
STATE_DIR="/var/lib/sentinel"
SERVICE_NAME="sentinel-agent"
SERVICE_USER="sentinel"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# --- Pre-flight checks ---

if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (sudo bash install.sh)"
    exit 1
fi

REQUIRED_CMDS=("python3" "git" "systemctl")
for cmd in "${REQUIRED_CMDS[@]}"; do
    if ! command -v "$cmd" &>/dev/null; then
        log_error "Required command not found: $cmd"
        exit 1
    fi
done

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 10 ]]; then
    log_error "Python 3.10+ is required, found $PYTHON_VERSION"
    exit 1
fi
log_info "Python $PYTHON_VERSION detected"

# Determine source directory (where this script lives)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# If run from the repo root (agent/install.sh), adjust
if [[ -f "$SCRIPT_DIR/agent.py" ]]; then
    AGENT_SRC="$SCRIPT_DIR"
    REPO_ROOT="$(dirname "$SCRIPT_DIR")"
elif [[ -f "$SCRIPT_DIR/agent/agent.py" ]]; then
    AGENT_SRC="$SCRIPT_DIR/agent"
    REPO_ROOT="$SCRIPT_DIR"
else
    log_error "Cannot find agent source files. Run from the repo root or agent/ directory."
    exit 1
fi

# --- Create system user ---

if ! id "$SERVICE_USER" &>/dev/null; then
    log_info "Creating system user: $SERVICE_USER"
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
else
    log_info "System user '$SERVICE_USER' already exists"
fi

# --- Create directories ---

log_info "Creating directories"
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$LOG_DIR" "$STATE_DIR"

# --- Copy agent code ---
# When install.sh is run from /opt/sentinel (in-place upgrade), AGENT_SRC is
# $INSTALL_DIR/agent. We must NOT rm that tree before copying — stage first.

STAGING_DIR="$(mktemp -d)"
cleanup_staging() { rm -rf "$STAGING_DIR"; }
trap cleanup_staging EXIT

log_info "Copying agent code to $INSTALL_DIR/"
cp -a "$AGENT_SRC/." "$STAGING_DIR/"
rm -rf "$INSTALL_DIR/agent"
mkdir -p "$INSTALL_DIR/agent"
cp -a "$STAGING_DIR/." "$INSTALL_DIR/agent/"

trap - EXIT
cleanup_staging

if [[ -f "$REPO_ROOT/VERSION" ]]; then
    cp "$REPO_ROOT/VERSION" "$INSTALL_DIR/VERSION"
fi

# --- Create virtual environment ---

if [[ ! -d "$INSTALL_DIR/venv" ]]; then
    log_info "Creating Python virtual environment"
    python3 -m venv "$INSTALL_DIR/venv"
else
    log_info "Virtual environment already exists, upgrading pip"
fi

"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/agent/requirements.txt"
log_info "Dependencies installed"

# --- Config file ---

if [[ ! -f "$CONFIG_DIR/agent.yaml" ]]; then
    log_info "Copying example config to $CONFIG_DIR/agent.yaml"
    cp "$INSTALL_DIR/agent/agent.yaml.example" "$CONFIG_DIR/agent.yaml"
    log_warn "You MUST edit $CONFIG_DIR/agent.yaml before starting the service"
else
    log_info "Config file already exists at $CONFIG_DIR/agent.yaml (not overwritten)"
fi

# --- Systemd unit ---

log_info "Installing systemd service"
cp "$INSTALL_DIR/agent/sentinel-agent.service" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload

# --- Permissions ---

log_info "Setting file permissions"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" "$STATE_DIR" "$LOG_DIR"
chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_DIR/agent.yaml"
chmod 0600 "$CONFIG_DIR/agent.yaml"
chmod 0700 "$STATE_DIR"
chmod 0755 "$LOG_DIR"

# --- Done ---

echo ""
log_info "Installation complete!"
echo ""
echo "  Next steps:"
echo "    1. Edit the config:    sudo nano $CONFIG_DIR/agent.yaml"
echo "    2. Enable the service: sudo systemctl enable --now $SERVICE_NAME"
echo "    3. Check status:       sudo systemctl status $SERVICE_NAME"
echo "    4. View logs:          sudo journalctl -u $SERVICE_NAME -f"
echo ""
