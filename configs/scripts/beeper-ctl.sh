#!/usr/bin/env bash
# ==============================================================================
# Beeper Bridge Manager (bbctl) Control Script for Tinarchy
# Documentation: configs/beeper/README.md
# ==============================================================================

set -euo pipefail

BBCTL_BIN="${BBCTL_BIN:-/home/tin/.local/bin/bbctl}"
if ! command -v "$BBCTL_BIN" >/dev/null 2>&1; then
    if command -v bbctl >/dev/null 2>&1; then
        BBCTL_BIN="$(command -v bbctl)"
    else
        echo "Error: bbctl binary not found." >&2
        exit 1
    fi
fi

case "${1:-status}" in
    status)
        echo "=== Beeper Account Status ==="
        "$BBCTL_BIN" whoami || true
        echo ""
        echo "=== Active Bridge Services ==="
        systemctl list-units 'bbctl@*' --state=active --no-legend --no-pager || echo "No active bridges running."
        ;;
    login)
        shift || true
        exec "$BBCTL_BIN" login "$@"
        ;;
    login-password)
        shift || true
        exec "$BBCTL_BIN" login-password "$@"
        ;;
    logout)
        exec "$BBCTL_BIN" logout
        ;;
    whoami)
        exec "$BBCTL_BIN" whoami
        ;;
    start|enable)
        if [ -z "${2:-}" ]; then
            echo "Usage: beeper start <bridge-name> (e.g., beeper start sh-whatsapp)"
            exit 1
        fi
        BRIDGE="$2"
        echo "Starting and enabling Beeper bridge: bbctl@${BRIDGE}.service..."
        sudo systemctl enable --now "bbctl@${BRIDGE}.service"
        sudo systemctl status "bbctl@${BRIDGE}.service" --no-pager || true
        ;;
    stop|disable)
        if [ -z "${2:-}" ]; then
            echo "Usage: beeper stop <bridge-name> (e.g., beeper stop sh-whatsapp)"
            exit 1
        fi
        BRIDGE="$2"
        echo "Stopping Beeper bridge: bbctl@${BRIDGE}.service..."
        sudo systemctl disable --now "bbctl@${BRIDGE}.service"
        ;;
    restart)
        if [ -z "${2:-}" ]; then
            echo "Usage: beeper restart <bridge-name> (e.g., beeper restart sh-whatsapp)"
            exit 1
        fi
        BRIDGE="$2"
        echo "Restarting Beeper bridge: bbctl@${BRIDGE}.service..."
        sudo systemctl restart "bbctl@${BRIDGE}.service"
        sudo systemctl status "bbctl@${BRIDGE}.service" --no-pager || true
        ;;
    logs)
        if [ -z "${2:-}" ]; then
            echo "Usage: beeper logs <bridge-name> (e.g., beeper logs sh-whatsapp)"
            exit 1
        fi
        BRIDGE="$2"
        exec journalctl -u "bbctl@${BRIDGE}.service" -f
        ;;
    bridges|list)
        echo "=== Supported Official Bridges ==="
        echo "  • sh-whatsapp   : WhatsApp Web bridge"
        echo "  • sh-telegram   : Telegram bridge"
        echo "  • sh-signal     : Signal Messenger bridge"
        echo "  • sh-discord    : Discord bridge"
        echo "  • sh-slack      : Slack workspace bridge"
        echo "  • sh-gmessages  : Google Messages (RCS) bridge"
        echo "  • sh-googlechat : Google Chat bridge"
        echo "  • sh-meta       : Meta / Instagram / Messenger bridge"
        echo "  • sh-twitter    : Twitter / X DM bridge"
        echo "  • sh-bluesky    : Bluesky DM bridge"
        echo "  • sh-irc        : IRC / Heisenbridge"
        echo "  • sh-linkedin   : LinkedIn messaging bridge"
        echo ""
        echo "=== Active Running Bridges ==="
        systemctl list-units 'bbctl@*' --state=active --no-legend --no-pager || echo "None active"
        ;;
    *)
        echo "Usage: beeper {status|login|login-password|logout|whoami|bridges|start <bridge>|stop <bridge>|restart <bridge>|logs <bridge>}"
        exit 1
        ;;
esac
