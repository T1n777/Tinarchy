#!/usr/bin/env bash
# ==============================================================================
# SyncYomi Installer & Daemon Setup Script for Tinarchy / Linux Servers
# ==============================================================================
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "❌ This installer must be run as root (or with sudo)."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "📦 Installing SyncYomi..."

# 1. Detect architecture
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  SYNCYOMI_ARCH="amd64" ;;
    aarch64|arm64) SYNCYOMI_ARCH="arm64" ;;
    armv7l)  SYNCYOMI_ARCH="armv7" ;;
    *) echo "❌ Unsupported architecture: $ARCH"; exit 1 ;;
esac

# 2. Check if already installed
if command -v syncyomi >/dev/null 2>&1; then
    echo "✅ SyncYomi binary already installed at $(command -v syncyomi) ($(syncyomi --version 2>&1 | head -n 1 || echo 'unknown'))"
else
    echo "🔍 Fetching latest SyncYomi release information..."
    LATEST_JSON=$(curl -sSL https://api.github.com/repos/SyncYomi/SyncYomi/releases/latest)

    # Try native package managers first if available
    INSTALL_SUCCESS=0

    # Arch Linux (.pkg.tar.zst)
    if [ "$INSTALL_SUCCESS" -eq 0 ] && command -v pacman >/dev/null 2>&1 && [ "$SYNCYOMI_ARCH" = "amd64" ]; then
        PKG_URL=$(echo "$LATEST_JSON" | grep -o 'https://[^"]*linux_amd64\.pkg\.tar\.zst' | head -n 1 || true)
        if [ -n "$PKG_URL" ]; then
            echo "📥 Downloading Arch package: $PKG_URL"
            TMP_PKG=$(mktemp /tmp/syncyomi-XXXXXX.pkg.tar.zst)
            curl -sSL "$PKG_URL" -o "$TMP_PKG"
            pacman -U --noconfirm "$TMP_PKG"
            rm -f "$TMP_PKG"
            INSTALL_SUCCESS=1
        fi
    fi

    # Debian / Ubuntu (.deb)
    if [ "$INSTALL_SUCCESS" -eq 0 ] && command -v dpkg >/dev/null 2>&1; then
        DEB_URL=$(echo "$LATEST_JSON" | grep -o "https://[^\"]*linux_${SYNCYOMI_ARCH}\.deb" | head -n 1 || true)
        if [ -n "$DEB_URL" ]; then
            echo "📥 Downloading Debian package: $DEB_URL"
            TMP_DEB=$(mktemp /tmp/syncyomi-XXXXXX.deb)
            curl -sSL "$DEB_URL" -o "$TMP_DEB"
            dpkg -i "$TMP_DEB" || apt-get install -f -y
            rm -f "$TMP_DEB"
            INSTALL_SUCCESS=1
        fi
    fi

    # Generic Binary Tarball Fallback
    if [ "$INSTALL_SUCCESS" -eq 0 ]; then
        TAR_URL=$(echo "$LATEST_JSON" | grep -o "https://[^\"]*linux_${SYNCYOMI_ARCH}\.tar\.gz" | head -n 1 || true)
        if [ -z "$TAR_URL" ]; then
            echo "❌ Could not find suitable release binary for linux_${SYNCYOMI_ARCH}"
            exit 1
        fi
        echo "📥 Downloading standalone binary: $TAR_URL"
        TMP_DIR=$(mktemp -d /tmp/syncyomi-XXXXXX)
        curl -sSL "$TAR_URL" -o "$TMP_DIR/syncyomi.tar.gz"
        tar -xzf "$TMP_DIR/syncyomi.tar.gz" -C "$TMP_DIR"
        install -Dm755 "$TMP_DIR/syncyomi" /usr/bin/syncyomi
        rm -rf "$TMP_DIR"
        INSTALL_SUCCESS=1
    fi
fi

# 3. Create dedicated system user & group
if ! id -u syncyomi >/dev/null 2>&1; then
    echo "👤 Creating system user and group 'syncyomi'..."
    useradd -r -s /usr/bin/nologin -d /var/lib/syncyomi -m syncyomi || useradd -r -s /bin/false -d /var/lib/syncyomi -m syncyomi
fi

# 4. Setup State Directory and default config
mkdir -p /var/lib/syncyomi
if [ ! -f /var/lib/syncyomi/config.toml ]; then
    echo "⚙️ Creating default config at /var/lib/syncyomi/config.toml..."
    cat <<'CONF' > /var/lib/syncyomi/config.toml
host = "0.0.0.0"
port = 8282
databaseType = "sqlite"
CONF
fi
chown -R syncyomi:syncyomi /var/lib/syncyomi
chmod 750 /var/lib/syncyomi

# 5. Install systemd service
SERVICE_SRC="$REPO_ROOT/configs/systemd/syncyomi.service"
if [ -f "$SERVICE_SRC" ]; then
    echo "📋 Deploying systemd unit..."
    cp "$SERVICE_SRC" /etc/systemd/system/syncyomi.service
    systemctl daemon-reload
    systemctl enable --now syncyomi.service
    echo "🚀 syncyomi.service is active and enabled."
fi

# 6. Enable in .env if present
ENV_FILE="$REPO_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
    if grep -q "ENABLE_SYNCYOMI=" "$ENV_FILE"; then
        sed -i 's/^ENABLE_SYNCYOMI=.*/ENABLE_SYNCYOMI=true/' "$ENV_FILE"
    else
        echo -e "\n# --- Optional Services ---\nENABLE_SYNCYOMI=true\nSYNCYOMI_PORT=8282" >> "$ENV_FILE"
    fi
    echo "✅ Activated ENABLE_SYNCYOMI=true in $ENV_FILE"
fi

echo ""
echo "🎉 SyncYomi setup completed successfully!"
echo "• Web UI: http://127.0.0.1:8282"
echo "• Dashboard Guide: /syncyomi"
echo "• If the dashboard is running, restart it to display the SyncYomi tile:"
echo "    sudo systemctl restart server-dashboard.service"
