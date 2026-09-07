#!/bin/sh
# Launcher script for Tinarchy Server Dashboard
set -e

TINARCHY_DIR="${TINARCHY_DIR:-/usr/share/tinarchy}"

cd "$TINARCHY_DIR"
exec /usr/bin/python3 "$TINARCHY_DIR/server.py" "$@"
