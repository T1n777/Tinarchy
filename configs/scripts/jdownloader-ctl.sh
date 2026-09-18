#!/usr/bin/env bash
# ==============================================================================
# JDownloader 2 Headless Control Script for Tinarchy
# Documentation: https://support.jdownloader.org/en/knowledgebase/article/headless-settings
# ==============================================================================

set -euo pipefail

if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    USER_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
else
    USER_HOME="${HOME:-/home/tin}"
fi

JD_DIR="${JD_DIR:-$USER_HOME/jdownloader}"
JD_CFG="$JD_DIR/cfg/org.jdownloader.api.myjdownloader.MyJDownloaderSettings.json"

case "${1:-status}" in
    start)
        echo "Starting JDownloader 2 service..."
        sudo systemctl start jdownloader.service
        sudo systemctl status jdownloader.service --no-pager || true
        ;;
    stop)
        echo "Stopping JDownloader 2 service..."
        sudo systemctl stop jdownloader.service
        ;;
    restart)
        echo "Restarting JDownloader 2 service..."
        sudo systemctl restart jdownloader.service
        sudo systemctl status jdownloader.service --no-pager || true
        ;;
    status)
        sudo systemctl status jdownloader.service --no-pager || true
        ;;
    logs)
        exec journalctl -u jdownloader.service -f
        ;;
    login|setup)
        echo "=== MyJDownloader Headless Setup ==="
        read -rp "MyJDownloader Email: " email
        read -rsp "MyJDownloader Password: " password
        echo ""
        read -rp "Device Name [default: tinarchy]: " devicename
        devicename="${devicename:-tinarchy}"

        mkdir -p "$JD_DIR/cfg"
        python3 -c "
import json
cfg_path = '$JD_CFG'
data = {
    'email': '''$email''',
    'password': '''$password''',
    'devicename': '''$devicename''',
    'autoconnectenabledv2': True
}
with open(cfg_path, 'w') as f:
    json.dump(data, f, indent=2)
"
        chmod 600 "$JD_CFG"
        echo "Saved credentials to $JD_CFG with mode 600."
        echo "Restarting jdownloader.service..."
        sudo systemctl restart jdownloader.service
        echo "Done! You can manage your downloads at https://my.jdownloader.org"
        ;;
    console)
        echo "Stopping background service if running..."
        sudo systemctl stop jdownloader.service 2>/dev/null || true
        echo "Running JDownloader 2 interactively..."
        cd "$JD_DIR"
        exec java -Djava.awt.headless=true -jar JDownloader.jar -norestart
        ;;
    install)
        echo "=== Installing JDownloader 2 Headless ==="
        mkdir -p "$JD_DIR/cfg"
        if [ ! -f "$JD_DIR/JDownloader.jar" ]; then
            echo "Downloading JDownloader.jar..."
            curl -fsSL "http://installer.jdownloader.org/JDownloader.jar" -o "$JD_DIR/JDownloader.jar"
        fi
        echo "Initializing JDownloader 2 core..."
        (cd "$JD_DIR" && java -Djava.awt.headless=true -jar JDownloader.jar -norestart || true)
        echo "Installation complete! Run 'jdownloader login' to connect your MyJDownloader account."
        ;;
    *)
        echo "Usage: $(basename "$0") {start|stop|restart|status|logs|login|console|install}"
        exit 1
        ;;
esac
