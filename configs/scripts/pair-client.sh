#!/usr/bin/env bash
# ==============================================================================
# Universal Syncthing Client Auto-Pairing Script
# Pairs any Linux client (PC/laptop) with your server's Syncthing drive.
# ==============================================================================
set -e

# Parse CLI arguments
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --server-id|-s) SERVER_ID="$2"; shift 2 ;;
        --server-name|-n) SERVER_NAME="$2"; shift 2 ;;
        --folder-id|-f) FOLDER_ID="$2"; shift 2 ;;
        --folder-label|-l) FOLDER_LABEL="$2"; shift 2 ;;
        --target-dir|-d) TARGET_DIR="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--server-id <ID>] [--server-name <NAME>] [--folder-id <ID>] [--folder-label <LABEL>] [--target-dir <PATH>]"
            exit 0
            ;;
        *) shift ;;
    esac
done

# Defaults / placeholders (can be overridden by flags, env vars, or server dynamic templating)
SERVER_ID="${SERVER_ID:-}"
SERVER_NAME="${SERVER_NAME:-Home Server}"
FOLDER_ID="${FOLDER_ID:-shared}"
FOLDER_LABEL="${FOLDER_LABEL:-Shared}"
TARGET_DIR="${TARGET_DIR:-${HOME}/drive}"

# If SERVER_ID is not provided, prompt interactively if running in a terminal
if [ -z "$SERVER_ID" ]; then
    if [ -t 0 ]; then
        read -rp "Enter Server Syncthing Device ID: " SERVER_ID
    fi
fi

if [ -z "$SERVER_ID" ]; then
    echo "❌ Error: SERVER_ID is required to pair."
    echo "   Usage: $0 --server-id <DEVICE_ID> [--server-name <NAME>]"
    exit 1
fi

echo "╔══════════════════════════════════════════════════════════════════════╗"
printf "║  %-68s║\n" "🔗 ${SERVER_NAME} — Client Auto-Pairing"
echo "╚══════════════════════════════════════════════════════════════════════╝"

# 1. Check and install syncthing if not present
if ! command -v syncthing >/dev/null 2>&1; then
    echo "⚙️  Syncthing not found. Attempting installation..."
    if command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --needed --noconfirm syncthing
    elif command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y syncthing
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y syncthing
    else
        echo "❌ Unsupported package manager. Please install syncthing manually."
        exit 1
    fi
fi

# 2. Ensure target drive directory exists
mkdir -p "$TARGET_DIR"

# 3. Enable and start Syncthing user service
echo "🚀 Starting Syncthing systemd user service..."
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user enable --now syncthing 2>/dev/null || syncthing --no-browser &
else
    syncthing --no-browser &
fi

# Wait for Syncthing API to become ready
echo "⏳ Waiting for Syncthing daemon to initialize..."
for i in {1..30}; do
    if syncthing cli show system >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# 4. Get this machine's Device ID
CLIENT_DEVICE_ID=$(syncthing cli show system 2>/dev/null | grep -i '"myID"' | awk '{print $2}' | tr -d '",')

if [ -z "$CLIENT_DEVICE_ID" ]; then
    echo "❌ Failed to retrieve local Syncthing Device ID."
    exit 1
fi

echo "🔑 Local Device ID: $CLIENT_DEVICE_ID"

# 5. Add Server Device
echo "🔗 Pairing with $SERVER_NAME ($SERVER_ID)..."
syncthing cli config devices add --device-id "$SERVER_ID" --name "$SERVER_NAME" 2>/dev/null || true
syncthing cli config devices "$SERVER_ID" compression set always 2>/dev/null || true

# 6. Configure shared folder
echo "📁 Configuring shared folder '$FOLDER_ID' at $TARGET_DIR..."
syncthing cli config folders add --id "$FOLDER_ID" --label "$FOLDER_LABEL" --path "$TARGET_DIR" 2>/dev/null || true
syncthing cli config folders "$FOLDER_ID" devices add --device-id "$SERVER_ID" 2>/dev/null || true
syncthing cli config folders "$FOLDER_ID" filesystem-watcher enabled set true 2>/dev/null || true
syncthing cli config folders "$FOLDER_ID" rescan-interval set 300 2>/dev/null || true

# Set default compression for future devices
syncthing cli config defaults device compression set always 2>/dev/null || true

echo ""
echo "══════════════════════════════════════════════════════════════════════"
echo "✨ Client pairing configuration completed successfully!"
echo "📍 Synced Folder: $TARGET_DIR"
echo "🆔 Your Device ID: $CLIENT_DEVICE_ID"
echo "══════════════════════════════════════════════════════════════════════"
