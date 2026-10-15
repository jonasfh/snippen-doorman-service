#!/usr/bin/env bash
#
# Automated production installer for Snippen Doorman Service on Raspberry Pi OS.
# Usage:
#   sudo bash scripts/install_pi.sh [optional_path_to_wheel]
#

set -euo pipefail

# Configuration defaults
INSTALL_DIR="${INSTALL_DIR:-/opt/snippen-doorman-service}"
SERVICE_USER="${SERVICE_USER:-doorman}"
SERVICE_GROUP="${SERVICE_GROUP:-doorman}"
CONFIG_DIR="${CONFIG_DIR:-/etc/snippen-doorman}"
ENV_FILE="${CONFIG_DIR}/snippen-doorman.env"
DBUS_CONFIG_DIR="/etc/dbus-1/system.d"
SYSTEMD_DIR="/etc/systemd/system"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# 1. Require root execution
if [ "$(id -u)" -ne 0 ]; then
    echo "❌ Error: This script must be run as root (use sudo)." >&2
    exit 1
fi

echo "=========================================================="
echo "  🚀 Installing Snippen Doorman Service on Raspberry Pi   "
echo "=========================================================="

# 2. Install required Debian / Raspberry Pi OS packages
echo "📦 [1/7] Installing system dependencies (BlueZ, Python 3, rfkill)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    bluez \
    rfkill \
    libglib2.0-dev

# 3. Create dedicated service user and groups
echo "👤 [2/7] Configuring service user '${SERVICE_USER}' and groups..."
if ! getent group "${SERVICE_GROUP}" >/dev/null; then
    groupadd --system "${SERVICE_GROUP}"
fi

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    useradd --system \
        --gid "${SERVICE_GROUP}" \
        --home-dir "${INSTALL_DIR}" \
        --shell /usr/sbin/nologin \
        --comment "Snippen Doorman Service Daemon" \
        "${SERVICE_USER}"
fi

# Ensure user is member of bluetooth and netdev groups
usermod -aG bluetooth,netdev "${SERVICE_USER}" || true

# 4. Set up directory hierarchy
echo "📁 [3/7] Setting up installation directory at ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"
mkdir -p "${CONFIG_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_DIR}"
chmod 755 "${INSTALL_DIR}"

# 5. Set up Python virtual environment and install package
echo "🐍 [4/7] Setting up Python virtual environment..."
VENV_DIR="${INSTALL_DIR}/.venv"
if [ ! -d "${VENV_DIR}" ]; then
    python3 -m venv "${VENV_DIR}"
fi

WHEEL_PATH="${1:-}"
if [ -z "${WHEEL_PATH}" ]; then
    # Look for existing wheel in dist/
    if ls "${REPO_ROOT}/dist/"*.whl 1>/dev/null 2>&1; then
        WHEEL_PATH="$(ls -t "${REPO_ROOT}/dist/"*.whl | head -n1)"
    fi
fi

if [ -n "${WHEEL_PATH}" ] && [ -f "${WHEEL_PATH}" ]; then
    echo "   Installing from prebuilt wheel: ${WHEEL_PATH}..."
    "${VENV_DIR}/bin/pip" install --upgrade pip
    "${VENV_DIR}/bin/pip" install "${WHEEL_PATH}"
elif [ -f "${REPO_ROOT}/pyproject.toml" ]; then
    echo "   Installing directly from source repository at ${REPO_ROOT}..."
    "${VENV_DIR}/bin/pip" install --upgrade pip
    "${VENV_DIR}/bin/pip" install "${REPO_ROOT}"
else
    echo "❌ Error: Could not locate a .whl package or pyproject.toml to install." >&2
    exit 1
fi

# Copy web-config PWA assets if present
if [ -d "${REPO_ROOT}/tools/web-config" ]; then
    echo "🌐 Copying web-config PWA to ${INSTALL_DIR}/tools/web-config..."
    mkdir -p "${INSTALL_DIR}/tools"
    cp -r "${REPO_ROOT}/tools/web-config" "${INSTALL_DIR}/tools/"
fi

chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_DIR}"

# 6. Install configuration template if not present
echo "⚙️  [5/7] Configuring environment file..."
if [ ! -f "${ENV_FILE}" ]; then
    if [ -f "${REPO_ROOT}/default.env" ]; then
        cp "${REPO_ROOT}/default.env" "${ENV_FILE}"
    else
        cat << 'EOF' > "${ENV_FILE}"
# Snippen Doorman Service Configuration
SNIPPEN_DOORMAN_API_URL="https://vestreholmensameie.no/wp-json/snippen/v1/door"
SNIPPEN_DOORMAN_API_TOKEN=""
DOORMAN_LOCKS="ytterdor=AA:BB:CC:DD:EE:01:0123456789abcdef0123456789abcdef:1,fellesrom=AA:BB:CC:DD:EE:02:fedcba9876543210fedcba9876543210:1"
SNIPPEN_DOORMAN_SYNC_INTERVAL=60.0
SNIPPEN_LEAD_TIME_MINUTES=60
SNIPPEN_GRACE_PERIOD_MINUTES=15
EOF
    fi
    chown root:"${SERVICE_GROUP}" "${ENV_FILE}"
    chmod 640 "${ENV_FILE}"
    echo "   Created ${ENV_FILE} (permissions: 0640, root:${SERVICE_GROUP})."
else
    echo "   Existing ${ENV_FILE} preserved."
fi

# 7. Install D-Bus permissions and Systemd service
echo "🛡️  [6/7] Installing D-Bus policy and Systemd service..."
if [ -f "${REPO_ROOT}/systemd/snippen-doorman-dbus.conf" ]; then
    cp "${REPO_ROOT}/systemd/snippen-doorman-dbus.conf" "${DBUS_CONFIG_DIR}/snippen-doorman.conf"
    chmod 644 "${DBUS_CONFIG_DIR}/snippen-doorman.conf"
    if systemctl is-active --quiet dbus 2>/dev/null; then
        systemctl reload dbus || true
    fi
fi

if [ -f "${REPO_ROOT}/systemd/snippen-doorman.service" ]; then
    cp "${REPO_ROOT}/systemd/snippen-doorman.service" "${SYSTEMD_DIR}/snippen-doorman.service"
    chmod 644 "${SYSTEMD_DIR}/snippen-doorman.service"
    if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload
        systemctl enable snippen-doorman.service
    fi
fi

# 8. Unblock bluetooth via rfkill if blocked
echo "📶 [7/7] Checking Bluetooth hardware state..."
if command -v rfkill >/dev/null 2>&1; then
    rfkill unblock bluetooth || true
fi

echo ""
echo "=========================================================="
echo "  ✅ Installation of Snippen Doorman Service Complete!    "
echo "=========================================================="
echo ""
echo "Next steps:"
echo " 1. Edit credentials in ${ENV_FILE}:"
echo "      sudo nano ${ENV_FILE}"
echo " 2. Start the service:"
echo "      sudo systemctl start snippen-doorman"
echo " 3. Verify logs:"
echo "      journalctl -u snippen-doorman -f"
echo ""
