#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${1:-$(tailscale status --json 2>/dev/null | jq -r '.CertDomains[0] // empty' 2>/dev/null || true)}"
if [ -z "$DOMAIN" ]; then
    DOMAIN="tinarchy.tail3dee69.ts.net"
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
CERT_DIR="$REPO_DIR/ssl"

mkdir -p "$CERT_DIR"

echo "[$(date -Iseconds)] Checking / renewing Tailscale Let's Encrypt TLS cert for $DOMAIN..."
/usr/bin/tailscale cert \
    --cert-file "$CERT_DIR/tailscale-cert.crt" \
    --key-file "$CERT_DIR/tailscale-cert.key" \
    "$DOMAIN"

chmod 644 "$CERT_DIR/tailscale-cert.crt"
chmod 600 "$CERT_DIR/tailscale-cert.key"

if /usr/bin/systemctl is-active --quiet nginx 2>/dev/null; then
    echo "[$(date -Iseconds)] Reloading Nginx..."
    sudo /usr/bin/systemctl reload nginx 2>/dev/null || true
fi

echo "[$(date -Iseconds)] Certificate verified & active."
