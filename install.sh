#!/usr/bin/env bash
# ==============================================================================
# 🍍 Tinarchy Server Ecosystem - Master Interactive Installer & Configurator
# ==============================================================================
# Complete freedom of customization:
# - Dashboard branding, display name, project name, subtitle, icon, port, credentials
# - Modular selection of all services and ecosystem components
# - Auto-downloads selected services if not already installed
# - Immediately launches the dashboard upon completion
# ==============================================================================
set -eo pipefail

# ─── Colors & Visual Styles ───────────────────────────────────────────────────
BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
MAGENTA='\033[35m'
BLUE='\033[34m'
NC='\033[0m'

# ─── Command-line Arguments ───────────────────────────────────────────────────
AUTO_YES=false
for arg in "$@"; do
    case "$arg" in
        -h|--help)
            echo "Usage: ./install.sh [OPTIONS]"
            echo ""
            echo "Interactive server installer for Tinarchy / Pinedash ecosystem."
            echo "Gives complete freedom in choosing dashboard branding and services."
            echo "Auto-downloads selected services if not already present, and launches"
            echo "the dashboard immediately when setup is complete."
            echo ""
            echo "Options:"
            echo "  -h, --help    Show this help message"
            echo "  -y, --yes     Non-interactive mode (accept all defaults)"
            exit 0
            ;;
        -y|--yes)
            AUTO_YES=true
            ;;
    esac
done

# ─── Privilege Check ──────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${YELLOW}⚡ Root privileges required. Escalating with sudo...${NC}"
    exec sudo "$0" "$@"
fi

TARGET_USER="${SUDO_USER:-$USER}"
[ -z "$TARGET_USER" ] && TARGET_USER=$(id -un)
USER_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
[ -z "$USER_HOME" ] && USER_HOME="$HOME"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"

# ─── OS & Architecture Detection ──────────────────────────────────────────────
ARCH="$(uname -m)"
OS_FAMILY="unknown"

if [ -f /etc/arch-release ]; then
    OS_FAMILY="arch"
elif [ -f /etc/debian_version ]; then
    OS_FAMILY="debian"
elif [ -f /etc/fedora-release ]; then
    OS_FAMILY="fedora"
fi

SYS_HOST="$(cat /etc/hostname 2>/dev/null || uname -n || echo 'tinarchy-server')"
SYS_HOST="$(echo "$SYS_HOST" | tr -d '[:space:]')"

# ─── Read Existing Configurations (if any) ────────────────────────────────────
EXISTING_SERVER_NAME=""
EXISTING_PROJECT_NAME=""
EXISTING_BRANDING_SUBTITLE=""
EXISTING_APP_ICON=""
EXISTING_PORT=""
EXISTING_SSH_USER=""
EXISTING_TAILSCALE_DOMAIN=""
EXISTING_OWNER_EMAIL=""
EXISTING_ADMIN_PASSWORD=""
EXISTING_STORAGE_DIR=""

EXISTING_ENABLE_TINARCHY="true"
EXISTING_ENABLE_NGINX="true"
EXISTING_ENABLE_SYNCTHING="true"
EXISTING_ENABLE_SUWAYOMI="true"
EXISTING_ENABLE_SYNCYOMI="false"
EXISTING_ENABLE_JELLYFIN="true"
EXISTING_ENABLE_TOR="true"
EXISTING_ENABLE_TAILSCALE="true"
EXISTING_ENABLE_TERMINAL="true"
EXISTING_ENABLE_DRIVE_ENGINE="true"
EXISTING_ENABLE_FILEBROWSER="false"
EXISTING_ENABLE_COUCHDB="false"
EXISTING_ENABLE_POWERDOWN="false"

if [ -f "$REPO_ROOT/.env" ]; then
    EXISTING_SERVER_NAME=$(grep -E '^SERVER_NAME=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_PROJECT_NAME=$(grep -E '^PROJECT_NAME=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_BRANDING_SUBTITLE=$(grep -E '^BRANDING_SUBTITLE=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_APP_ICON=$(grep -E '^APP_ICON=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_PORT=$(grep -E '^PORT=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_SSH_USER=$(grep -E '^SSH_USER=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_TAILSCALE_DOMAIN=$(grep -E '^TAILSCALE_DOMAIN=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_OWNER_EMAIL=$(grep -E '^OWNER_EMAIL=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_ADMIN_PASSWORD=$(grep -E '^ADMIN_PASSWORD=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_STORAGE_DIR=$(grep -E '^STORAGE_DIR=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)

    [ "$(grep -E '^ENABLE_SUWAYOMI=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)" = "false" ] && EXISTING_ENABLE_SUWAYOMI="false"
    [ "$(grep -E '^ENABLE_JELLYFIN=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)" = "false" ] && EXISTING_ENABLE_JELLYFIN="false"
    [ "$(grep -E '^ENABLE_TOR=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)" = "false" ] && EXISTING_ENABLE_TOR="false"
    [ "$(grep -E '^ENABLE_TAILSCALE_SSH=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)" = "false" ] && EXISTING_ENABLE_TAILSCALE="false"
    [ "$(grep -E '^ENABLE_SYNCTHING=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)" = "false" ] && EXISTING_ENABLE_SYNCTHING="false"
    [ "$(grep -E '^ENABLE_SYNCYOMI=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)" = "true" ] && EXISTING_ENABLE_SYNCYOMI="true"
    [ "$(grep -E '^ENABLE_FILEBROWSER=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)" = "true" ] && EXISTING_ENABLE_FILEBROWSER="true"
    [ "$(grep -E '^ENABLE_COUCHDB=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)" = "true" ] && EXISTING_ENABLE_COUCHDB="true"
    EXISTING_HARDWARE_MEMORY_PROFILE=$(grep -E '^HARDWARE_MEMORY_PROFILE=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
fi

# ─── Header Banner ────────────────────────────────────────────────────────────
clear 2>/dev/null || true
echo -e "${CYAN}${BOLD}"
cat << 'EOF'
 🍍  ═══════════════════════════════════════════════════════════════════
       _____ _                      _           
      |_   _(_)_ __   __ _ _ __ ___| |__  _   _ 
        | | | | '_ \ / _` | '__/ __| '_ \| | | |
        | | | | | | | (_| | | | (__| | | | |_| |
        |_| |_|_| |_|\__,_|_|  \___|_| |_|\__, |
                                          |___/ 
      Translucent Glassmorphic Linux Server Control Center
 ═══════════════════════════════════════════════════════════════════════
EOF
echo -e "${NC}"
echo -e "  ${DIM}Detected Host:${NC}  ${BOLD}${SYS_HOST}${NC} (${OS_FAMILY^} Linux on ${ARCH})"
echo -e "  ${DIM}Target User:${NC}    ${BOLD}${TARGET_USER}${NC} (${USER_HOME})"
echo -e "  ${DIM}Repository:${NC}     ${BOLD}${REPO_ROOT}${NC}"
echo ""

# Helper to ask yes/no question
ask_choice() {
    local prompt="$1"
    local default="$2"
    local result_var="$3"
    local yn="[Y/n]"
    [ "$default" = "n" ] && yn="[y/N]"

    if [ "$AUTO_YES" = "true" ]; then
        echo -e "  ${BOLD}${prompt}${NC} ${DIM}${yn}${NC}: ${GREEN}${default}${NC} (auto)"
        case "$default" in
            y|yes) eval "$result_var=true"; return 0 ;;
            n|no)  eval "$result_var=false"; return 0 ;;
        esac
    fi

    while true; do
        echo -ne "  ${BOLD}${prompt}${NC} ${DIM}${yn}${NC}: "
        local reply=""
        read -r reply </dev/tty 2>/dev/null || read -r reply || reply=""
        reply=$(echo "$reply" | tr '[:upper:]' '[:lower:]' | xargs)
        if [ -z "$reply" ]; then
            reply="$default"
        fi
        case "$reply" in
            y|yes) eval "$result_var=true"; return 0 ;;
            n|no)  eval "$result_var=false"; return 0 ;;
            *) echo -e "    ${YELLOW}Please enter 'y' or 'n'.${NC}" ;;
        esac
    done
}

# Helper to ask text input with defaults
ask_input() {
    local prompt="$1"
    local default="$2"
    local result_var="$3"
    local secret="${4:-false}"

    local def_display="$default"
    [ "$secret" = "true" ] && [ -n "$default" ] && def_display="********"

    if [ "$AUTO_YES" = "true" ]; then
        if [ "$secret" = "true" ]; then
            echo -e "  ${BOLD}${prompt}${NC} [default: ********]: (auto)"
        else
            echo -e "  ${BOLD}${prompt}${NC} [default: ${default}]: ${GREEN}${default}${NC} (auto)"
        fi
        eval "$result_var=\"\$default\""
        return 0
    fi

    while true; do
        if [ -n "$def_display" ]; then
            echo -ne "  ${BOLD}${prompt}${NC} ${DIM}[${def_display}]${NC}: "
        else
            echo -ne "  ${BOLD}${prompt}${NC}: "
        fi

        local reply=""
        if [ "$secret" = "true" ]; then
            read -r -s reply </dev/tty 2>/dev/null || read -r -s reply || reply=""
            echo ""
        else
            read -r reply </dev/tty 2>/dev/null || read -r reply || reply=""
        fi

        reply=$(echo "$reply" | xargs)
        if [ -z "$reply" ]; then
            reply="$default"
        fi
        eval "$result_var=\"\$reply\""
        return 0
    done
}

# ─── PHASE 1: Complete Dashboard Branding & Personalization Prompts ───────────
echo -e "${CYAN}─── 1. Dashboard Branding & Personalization ───────────────────────────${NC}"
echo -e "Configure what your dashboard will look like and how it identifies itself."
echo -e "Press ${BOLD}Enter${NC} to accept the bracketed default values."
echo ""

# 1. Project / Suite Name
DEFAULT_PROJECT_NAME="${EXISTING_PROJECT_NAME:-Tinarchy}"
ask_input "Project / Suite Name" "$DEFAULT_PROJECT_NAME" CFG_PROJECT_NAME

# 2. Server Display Name
DETECTED_HOST_PRETTY="$(echo "$SYS_HOST" | sed 's/[-_]/ /g' | awk '{for(i=1;i<=NF;i++)sub(/./,toupper(substr($i,1,1)),$i)}1')"
DEFAULT_SERVER_NAME="${EXISTING_SERVER_NAME:-$DETECTED_HOST_PRETTY}"
ask_input "Server Display Name (Tile Title)" "$DEFAULT_SERVER_NAME" CFG_SERVER_NAME

# 3. Branding Subtitle
DEFAULT_SUBTITLE="${EXISTING_BRANDING_SUBTITLE:-Server Control Center}"
ask_input "Branding Subtitle" "$DEFAULT_SUBTITLE" CFG_BRANDING_SUBTITLE

# 4. App Icon / Emoji
DEFAULT_ICON="${EXISTING_APP_ICON:-🍍}"
ask_input "Server Emoji Icon" "$DEFAULT_ICON" CFG_APP_ICON

# 5. Dashboard Port
DEFAULT_PORT="${EXISTING_PORT:-8085}"
ask_input "Dashboard Internal HTTP Port" "$DEFAULT_PORT" CFG_PORT

# 6. Web Admin Password
DEFAULT_ADMIN_PASS="${EXISTING_ADMIN_PASSWORD:-changeme}"
ask_input "Dashboard Web Admin Password" "$DEFAULT_ADMIN_PASS" CFG_ADMIN_PASSWORD true

# 7. Primary SSH / System User
DEFAULT_SSH_USER="${EXISTING_SSH_USER:-$TARGET_USER}"
ask_input "Primary System / SSH Username" "$DEFAULT_SSH_USER" CFG_SSH_USER

# 8. Unified Drive Storage Directory
DEFAULT_STORAGE_DIR="${EXISTING_STORAGE_DIR:-$USER_HOME/drive}"
ask_input "Unified Drive Storage Directory" "$DEFAULT_STORAGE_DIR" CFG_STORAGE_DIR

# 9. Tailscale MagicDNS Domain (optional)
MAGIC_SUFFIX="$(tailscale status --json 2>/dev/null | grep -o '"MagicDNSSuffix": *"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
DETECTED_DOMAIN=""
[ -n "$MAGIC_SUFFIX" ] && DETECTED_DOMAIN="${SYS_HOST}.${MAGIC_SUFFIX}"
DEFAULT_TS_DOMAIN="${EXISTING_TAILSCALE_DOMAIN:-$DETECTED_DOMAIN}"
ask_input "Tailscale MagicDNS Domain (optional)" "$DEFAULT_TS_DOMAIN" CFG_TAILSCALE_DOMAIN

# 10. Owner Email (optional)
DETECTED_EMAIL="$(tailscale status --json 2>/dev/null | grep -o '"LoginName": *"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
DEFAULT_OWNER_EMAIL="${EXISTING_OWNER_EMAIL:-$DETECTED_EMAIL}"
ask_input "Owner Email (Tailscale Identity)" "$DEFAULT_OWNER_EMAIL" CFG_OWNER_EMAIL

echo ""

# ─── PHASE 2: Complete Freedom of Modular Service Selection ───────────────────
echo -e "${CYAN}─── 2. Modular Service Selection ───────────────────────────────────────${NC}"
echo -e "You have complete freedom to choose exactly which services and components"
echo -e "to activate. Any service you select will be automatically downloaded and"
echo -e "configured if not already installed."
echo ""

# 1. Core Dashboard
echo -e "${CYAN}[1/13]${NC} ${BOLD}Dashboard Backend & Web UI (:8085)${NC}"
echo -e "        ${DIM}Telemetry UI, Pywal Dynamic Theming, Tailscale Whois RBAC & API daemon${NC}"
echo -e "        ${DIM}Creator: ${GREEN}Yatin Rajesh (@T1n777)${NC} - https://github.com/T1n777/Tinarchy${NC}"
ask_choice "Install and activate ${CFG_PROJECT_NAME} Dashboard?" "y" INSTALL_TINARCHY
echo ""

# 2. Nginx Reverse Proxy
echo -e "${CYAN}[2/13]${NC} ${BOLD}Nginx Reverse Proxy & SSL Engine (:80, :8080, :443)${NC}"
echo -e "        ${DIM}High-performance HTTP/2 reverse proxy with unified subpath & WebSocket routing${NC}"
echo -e "        ${DIM}Creator: ${GREEN}Igor Sysoev & NGINX Team${NC} - https://nginx.org${NC}"
ask_choice "Install and activate Nginx Reverse Proxy?" "y" INSTALL_NGINX
echo ""

# 3. Syncthing Full Drive Sync
echo -e "${CYAN}[3/13]${NC} ${BOLD}Syncthing Continuous Folder Sync (:8384 / :22000)${NC}"
echo -e "        ${DIM}Private, decentralized continuous file sync for drive directory with LZ4 compression${NC}"
echo -e "        ${DIM}Creator: ${GREEN}Jakob Borg & The Syncthing Foundation${NC} - https://syncthing.net${NC}"
DEF_SYNC="$([ "$EXISTING_ENABLE_SYNCTHING" = "true" ] && echo 'y' || echo 'n')"
ask_choice "Install and activate Syncthing Full Folder Sync?" "$DEF_SYNC" INSTALL_SYNCTHING
echo ""

# 4. Suwayomi Manga Server
echo -e "${CYAN}[4/13]${NC} ${BOLD}Suwayomi Server (Manga Library & Reader) (:4567)${NC}"
echo -e "        ${DIM}Free and open source manga reader server compatible with Tachiyomi / Mihon${NC}"
echo -e "        ${DIM}Creator: ${GREEN}The Suwayomi Project Contributors${NC} - https://github.com/Suwayomi${NC}"
DEF_SUW="$([ "$EXISTING_ENABLE_SUWAYOMI" = "true" ] && echo 'y' || echo 'n')"
ask_choice "Install and activate Suwayomi Manga Server?" "$DEF_SUW" INSTALL_SUWAYOMI
echo ""

# 5. SyncYomi Reading Progress Sync
echo -e "${CYAN}[5/13]${NC} ${BOLD}SyncYomi (Manga Progress Sync Daemon) (:8282)${NC}"
echo -e "        ${DIM}Automated reading history and progress synchronization across all client devices${NC}"
echo -e "        ${DIM}Creator: ${GREEN}The SyncYomi Project Contributors${NC} - https://github.com/SyncYomi/SyncYomi${NC}"
DEF_SYNCYOMI="$([ "$EXISTING_ENABLE_SYNCYOMI" = "true" ] && echo 'y' || echo 'n')"
ask_choice "Install and activate SyncYomi Daemon?" "$DEF_SYNCYOMI" INSTALL_SYNCYOMI
echo ""

# 6. Jellyfin Media Server
echo -e "${CYAN}[6/13]${NC} ${BOLD}Jellyfin Media Server (:8096)${NC}"
echo -e "        ${DIM}The volunteer-built media streaming system for movies, TV series and home media${NC}"
echo -e "        ${DIM}Creator: ${GREEN}The Jellyfin Project & Community${NC} - https://jellyfin.org${NC}"
DEF_JELL="$([ "$EXISTING_ENABLE_JELLYFIN" = "true" ] && echo 'y' || echo 'n')"
ask_choice "Install and activate Jellyfin Media Server?" "$DEF_JELL" INSTALL_JELLYFIN
echo ""

# 7. Tor Anonymity Proxy & Global Exit Node
echo -e "${CYAN}[7/13]${NC} ${BOLD}Tor SOCKS5 Proxy & Global Exit Node (:9050)${NC}"
echo -e "        ${DIM}Standalone onion proxy with automated Tailscale WireGuard NAT exit routing${NC}"
echo -e "        ${DIM}Creator: ${GREEN}The Tor Project${NC} - https://www.torproject.org${NC}"
DEF_TOR="$([ "$EXISTING_ENABLE_TOR" = "true" ] && echo 'y' || echo 'n')"
ask_choice "Install and activate Tor Proxy & Exit Node?" "$DEF_TOR" INSTALL_TOR
echo ""

# 8. Tailscale Mesh Network & SSH
echo -e "${CYAN}[8/13]${NC} ${BOLD}Tailscale WireGuard Mesh & Keyless SSH (:22)${NC}"
echo -e "        ${DIM}Encrypted zero-config mesh overlay network with keyless SSH terminal access${NC}"
echo -e "        ${DIM}Creator: ${GREEN}Avery Pennarun, Brad Fitzpatrick & Tailscale Inc.${NC} - https://tailscale.com${NC}"
DEF_TS="$([ "$EXISTING_ENABLE_TAILSCALE" = "true" ] && echo 'y' || echo 'n')"
ask_choice "Install and activate Tailscale & Tailscale SSH?" "$DEF_TS" INSTALL_TAILSCALE
echo ""

# 9. Persistent Terminal Ecosystem (tmux + Zsh)
echo -e "${CYAN}[9/13]${NC} ${BOLD}Persistent Terminal Ecosystem (tmux + Zsh)${NC}"
echo -e "        ${DIM}Auto-attaching tmux (:main), 50K scrollback, instant Esc, and low-latency Zsh shell${NC}"
echo -e "        ${DIM}Creator: ${GREEN}Nicholas Marriott (tmux)${NC} & ${GREEN}Paul Falstad / Zsh Development Group${NC}"
ask_choice "Install Persistent Terminal Ecosystem (tmux + Zsh)?" "y" INSTALL_TERMINAL
echo ""

# 10. Unified Drive Engine & Cloud Backups
echo -e "${CYAN}[10/13]${NC} ${BOLD}Unified Drive Engine & Rclone Cloud Backups${NC}"
echo -e "         ${DIM}Drive folder hierarchy, local symlinks, and automated cloud backups${NC}"
echo -e "         ${DIM}Creator: ${GREEN}Tinarchy Team${NC} & ${GREEN}Nick Craig-Wood (Rclone)${NC} - https://rclone.org${NC}"
ask_choice "Install Unified Drive Engine & Cloud Backups?" "y" INSTALL_DRIVE_ENGINE
echo ""

# 11. FileBrowser Quantum Web File Manager
echo -e "${CYAN}[11/13]${NC} ${BOLD}FileBrowser Quantum Web File Manager (:8081 / :8082)${NC}"
echo -e "         ${DIM}Modern web file manager with real-time drive mirror synchronization${NC}"
echo -e "         ${DIM}Creator: ${GREEN}FileBrowser Authors & Community${NC} - https://filebrowser.org${NC}"
DEF_FB="$([ "$EXISTING_ENABLE_FILEBROWSER" = "true" ] && echo 'y' || echo 'n')"
ask_choice "Install and activate FileBrowser Quantum?" "$DEF_FB" INSTALL_FILEBROWSER
echo ""

# 12. Obsidian LiveSync CouchDB Database
echo -e "${CYAN}[12/13]${NC} ${BOLD}Obsidian LiveSync CouchDB Database (:5984)${NC}"
echo -e "         ${DIM}Real-time end-to-end encrypted synchronization backend for Obsidian markdown notes${NC}"
echo -e "         ${DIM}Creator: ${GREEN}The Apache Software Foundation & Obsidian-LiveSync${NC}"
DEF_COUCH="$([ "$EXISTING_ENABLE_COUCHDB" = "true" ] && echo 'y' || echo 'n')"
ask_choice "Install and activate Obsidian LiveSync (CouchDB)?" "$DEF_COUCH" INSTALL_COUCHDB
echo ""

# 13. Headless Powerdown & Display Inactivity Sleep Daemon
echo -e "${CYAN}[13/13]${NC} ${BOLD}Headless Powerdown & Display Sleep Daemon${NC}"
echo -e "         ${DIM}0-Watt DPMS display powerdown after 60s inactivity, input wake-up, and ACPI lid handling${NC}"
echo -e "         ${DIM}Creator: ${GREEN}Tinarchy Team${NC}"
DEF_POWER="y"
if ! grep -q -i "battery" /sys/class/power_supply/*/type 2>/dev/null && [ ! -d /sys/class/backlight ]; then
    DEF_POWER="n"
fi
ask_choice "Install Display Inactivity Sleep & ACPI Power Management?" "$DEF_POWER" INSTALL_POWERDOWN
echo ""

# ─── Summary Table ────────────────────────────────────────────────────────────
echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e " ${BOLD}INSTALLATION & PERSONALIZATION SUMMARY${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
format_summary() {
    local name="$1"
    local flag="$2"
    if [ "$flag" = "true" ]; then
        echo -e "   ${GREEN}✔${NC}  ${BOLD}${name}${NC}"
    else
        echo -e "   ${DIM}✖  ${name} (Skipped)${NC}"
    fi
}
echo -e " ${BOLD}Personal Server Settings:${NC}"
echo -e "   • Project Suite Name  : ${BOLD}${CFG_PROJECT_NAME}${NC}"
echo -e "   • Server Display Name : ${BOLD}${CFG_SERVER_NAME}${NC} (${CFG_APP_ICON})"
echo -e "   • Branding Subtitle   : ${BOLD}${CFG_BRANDING_SUBTITLE}${NC}"
echo -e "   • Dashboard HTTP Port : ${BOLD}${CFG_PORT}${NC}"
echo -e "   • Primary System User : ${BOLD}${CFG_SSH_USER}${NC}"
echo -e "   • Drive Storage Path  : ${BOLD}${CFG_STORAGE_DIR}${NC}"
echo -e "   • Tailscale Domain    : ${BOLD}${CFG_TAILSCALE_DOMAIN:-None}${NC}"
echo -e "   • Owner Email         : ${BOLD}${CFG_OWNER_EMAIL:-None}${NC}"
echo -e "   • Web Admin Password  : ${BOLD}********${NC}"
echo ""
echo -e " ${BOLD}Selected Services & Modules:${NC}"
format_summary "Tinarchy Dashboard Backend (:8085)" "$INSTALL_TINARCHY"
format_summary "Nginx Reverse Proxy & SSL (:80, :443)" "$INSTALL_NGINX"
format_summary "Syncthing Full Drive Sync (:8384)"   "$INSTALL_SYNCTHING"
format_summary "Suwayomi Manga Server (:4567)"       "$INSTALL_SUWAYOMI"
format_summary "SyncYomi Manga Sync Daemon (:8282)"  "$INSTALL_SYNCYOMI"
format_summary "Jellyfin Media Server (:8096)"       "$INSTALL_JELLYFIN"
format_summary "Tor Proxy & Exit Node (:9050)"       "$INSTALL_TOR"
format_summary "Tailscale & Tailscale SSH (:22)"     "$INSTALL_TAILSCALE"
format_summary "Persistent Terminal (tmux + Zsh)"    "$INSTALL_TERMINAL"
format_summary "Unified Drive Sync & Rclone Backups" "$INSTALL_DRIVE_ENGINE"
format_summary "FileBrowser Quantum (:8081 / :8082)" "$INSTALL_FILEBROWSER"
format_summary "Obsidian LiveSync CouchDB (:5984)"   "$INSTALL_COUCHDB"
format_summary "Display Inactivity Sleep & DPMS 0W"  "$INSTALL_POWERDOWN"

echo -e "${CYAN}───────────────────────────────────────────────────────────────────────${NC}"

ask_choice "Proceed with batch installation, auto-downloads, and deployment?" "y" PROCEED_INSTALL
if [ "$PROCEED_INSTALL" != "true" ]; then
    echo -e "${YELLOW}Installation aborted by user. No changes were made.${NC}"
    exit 0
fi

echo ""
echo -e "${GREEN}🚀 Beginning automated installation and service deployment...${NC}"
echo ""

# ─── PHASE 3: Smart Auto-Downloads (Only if not already downloaded) ───────────
echo -e "${CYAN}─── 3. Checking Dependencies & Auto-Downloading Services ──────────────${NC}"

# Package manager batch list
PACKAGES_TO_INSTALL=()

# 1. Python core dependencies
if [ "$INSTALL_TINARCHY" = "true" ]; then
    case "$OS_FAMILY" in
        arch)   PACKAGES_TO_INSTALL+=('python' 'python-pillow' 'python-requests') ;;
        debian) PACKAGES_TO_INSTALL+=('python3' 'python3-pil' 'python3-requests') ;;
        fedora) PACKAGES_TO_INSTALL+=('python3' 'python3-pillow' 'python3-requests') ;;
    esac
fi

# 2. Nginx
if [ "$INSTALL_NGINX" = "true" ]; then
    if ! command -v nginx >/dev/null 2>&1; then
        PACKAGES_TO_INSTALL+=('nginx')
    else
        echo -e "  ${GREEN}✅ Nginx is already installed ($(command -v nginx))${NC}"
    fi
fi

# 3. Syncthing
if [ "$INSTALL_SYNCTHING" = "true" ]; then
    if ! command -v syncthing >/dev/null 2>&1; then
        PACKAGES_TO_INSTALL+=('syncthing')
    else
        echo -e "  ${GREEN}✅ Syncthing is already installed ($(command -v syncthing))${NC}"
    fi
fi

# 4. Tor & iptables
if [ "$INSTALL_TOR" = "true" ]; then
    if ! command -v tor >/dev/null 2>&1; then
        PACKAGES_TO_INSTALL+=('tor')
    else
        echo -e "  ${GREEN}✅ Tor is already installed ($(command -v tor))${NC}"
    fi
    if ! command -v iptables >/dev/null 2>&1; then
        PACKAGES_TO_INSTALL+=('iptables')
    fi
fi

# 5. Tailscale
if [ "$INSTALL_TAILSCALE" = "true" ]; then
    if ! command -v tailscale >/dev/null 2>&1; then
        PACKAGES_TO_INSTALL+=('tailscale')
    else
        echo -e "  ${GREEN}✅ Tailscale is already installed ($(command -v tailscale))${NC}"
    fi
fi

# 6. Terminal (tmux + Zsh)
if [ "$INSTALL_TERMINAL" = "true" ]; then
    if ! command -v tmux >/dev/null 2>&1; then
        PACKAGES_TO_INSTALL+=('tmux')
    else
        echo -e "  ${GREEN}✅ tmux is already installed ($(command -v tmux))${NC}"
    fi
    if ! command -v zsh >/dev/null 2>&1; then
        PACKAGES_TO_INSTALL+=('zsh')
    else
        echo -e "  ${GREEN}✅ Zsh is already installed ($(command -v zsh))${NC}"
    fi
fi

# 7. Rclone
if [ "$INSTALL_DRIVE_ENGINE" = "true" ]; then
    if ! command -v rclone >/dev/null 2>&1; then
        PACKAGES_TO_INSTALL+=('rclone')
    else
        echo -e "  ${GREEN}✅ Rclone is already installed ($(command -v rclone))${NC}"
    fi
fi

# 8. CouchDB
if [ "$INSTALL_COUCHDB" = "true" ]; then
    if ! command -v couchdb >/dev/null 2>&1 && [ ! -x /usr/lib/couchdb/bin/couchdb ]; then
        PACKAGES_TO_INSTALL+=('couchdb')
    else
        echo -e "  ${GREEN}✅ CouchDB is already installed${NC}"
    fi
fi

# 9. Jellyfin
if [ "$INSTALL_JELLYFIN" = "true" ]; then
    if ! command -v jellyfin >/dev/null 2>&1 && ! command -v jellyfin-server >/dev/null 2>&1; then
        case "$OS_FAMILY" in
            arch)   PACKAGES_TO_INSTALL+=('jellyfin-server' 'jellyfin-web') ;;
            debian) PACKAGES_TO_INSTALL+=('jellyfin') ;;
            fedora) PACKAGES_TO_INSTALL+=('jellyfin') ;;
        esac
    else
        echo -e "  ${GREEN}✅ Jellyfin is already installed${NC}"
    fi
fi

# 10. ACPI daemon (for powerdown)
if [ "$INSTALL_POWERDOWN" = "true" ]; then
    if ! command -v acpid >/dev/null 2>&1; then
        PACKAGES_TO_INSTALL+=('acpid')
    fi
fi

# Batch install package manager packages if any
if [ ${#PACKAGES_TO_INSTALL[@]} -gt 0 ]; then
    echo -e "${CYAN}📦 Installing ${#PACKAGES_TO_INSTALL[@]} system packages:${NC} ${PACKAGES_TO_INSTALL[*]}"
    case "$OS_FAMILY" in
        arch)
            pacman -S --needed --noconfirm "${PACKAGES_TO_INSTALL[@]}" || true
            ;;
        debian)
            apt-get update -y
            apt-get install -y "${PACKAGES_TO_INSTALL[@]}" || true
            ;;
        fedora)
            dnf install -y "${PACKAGES_TO_INSTALL[@]}" || true
            ;;
        *)
            echo -e "${YELLOW}⚠️ Unknown OS family. Please install manually:${NC} ${PACKAGES_TO_INSTALL[*]}"
            ;;
    esac
fi

# Fallback Tailscale auto-download if package manager didn't install it
if [ "$INSTALL_TAILSCALE" = "true" ] && ! command -v tailscale >/dev/null 2>&1; then
    echo -e "  ${CYAN}📥 Auto-downloading Tailscale via official installer...${NC}"
    curl -fsSL https://tailscale.com/install.sh | sh || true
fi

# Fallback Rclone auto-download if package manager didn't install it
if [ "$INSTALL_DRIVE_ENGINE" = "true" ] && ! command -v rclone >/dev/null 2>&1; then
    echo -e "  ${CYAN}📥 Auto-downloading Rclone via official installer...${NC}"
    curl https://rclone.org/install.sh | bash 2>/dev/null || true
fi

# ── Custom Auto-Downloads (Suwayomi, SyncYomi, FileBrowser) ────────────────────

# Suwayomi Manga Server Auto-Download
if [ "$INSTALL_SUWAYOMI" = "true" ]; then
    if [ -f "/opt/suwayomi/suwayomi-server.jar" ] || command -v suwayomi-server >/dev/null 2>&1; then
        echo -e "  ${GREEN}✅ Suwayomi Server is already installed, skipping download.${NC}"
    else
        echo -e "  ${CYAN}📥 Auto-downloading Suwayomi Server jar from GitHub releases...${NC}"
        if ! command -v java >/dev/null 2>&1; then
            echo -e "  ${CYAN}☕ Installing Java runtime for Suwayomi...${NC}"
            case "$OS_FAMILY" in
                arch)   pacman -S --needed --noconfirm jre-openjdk-headless || true ;;
                debian) apt-get install -y default-jre-headless || true ;;
                fedora) dnf install -y java-latest-openjdk-headless || true ;;
            esac
        fi
        mkdir -p /opt/suwayomi
        SUWAYOMI_RELEASE_JSON=$(curl -sSL https://api.github.com/repos/Suwayomi/Suwayomi-Server/releases/latest 2>/dev/null || true)
        SUWAYOMI_JAR_URL=$(echo "$SUWAYOMI_RELEASE_JSON" | grep -o 'https://[^"]*Suwayomi-Server[^"]*\.jar' | head -n 1 || true)
        if [ -z "$SUWAYOMI_JAR_URL" ]; then
            SUWAYOMI_JAR_URL="https://github.com/Suwayomi/Suwayomi-Server/releases/download/v1.1.1/Suwayomi-Server-v1.1.1.jar"
        fi
        echo -e "     ${DIM}Fetching: $SUWAYOMI_JAR_URL${NC}"
        curl -sSL "$SUWAYOMI_JAR_URL" -o /opt/suwayomi/suwayomi-server.jar || true
        chmod 644 /opt/suwayomi/suwayomi-server.jar 2>/dev/null || true
        echo -e "  ${GREEN}✅ Suwayomi Server downloaded to /opt/suwayomi/suwayomi-server.jar${NC}"
    fi

    if ! id -u suwayomi >/dev/null 2>&1; then
        useradd -r -s /usr/bin/nologin -d /var/lib/suwayomi -m suwayomi 2>/dev/null || useradd -r -s /bin/false -d /var/lib/suwayomi -m suwayomi 2>/dev/null || true
    fi
    mkdir -p /var/lib/suwayomi
    chown -R suwayomi:suwayomi /var/lib/suwayomi 2>/dev/null || true

    if [ -f "$REPO_ROOT/configs/systemd/suwayomi-server.service" ]; then
        cp "$REPO_ROOT/configs/systemd/suwayomi-server.service" /etc/systemd/system/
    fi
    mkdir -p /etc/suwayomi
    if [ -f "$REPO_ROOT/configs/suwayomi/suwayomi-env.conf" ]; then
        cp "$REPO_ROOT/configs/suwayomi/suwayomi-env.conf" /etc/suwayomi/server.conf
    fi
    if [ -f "$REPO_ROOT/configs/scripts/suwayomi-trigger-sync" ]; then
        cp "$REPO_ROOT/configs/scripts/suwayomi-trigger-sync" /usr/local/bin/
        chmod 755 /usr/local/bin/suwayomi-trigger-sync
    fi
    mkdir -p /etc/systemd/system/suwayomi-server.service.d/
    if [ -f "$REPO_ROOT/configs/systemd/suwayomi-server-sync-triggers.conf" ]; then
        cp "$REPO_ROOT/configs/systemd/suwayomi-server-sync-triggers.conf" /etc/systemd/system/suwayomi-server.service.d/sync-triggers.conf
    fi
    if [ -f "$REPO_ROOT/configs/systemd/suwayomi-server-cpu-throttle.conf" ]; then
        cp "$REPO_ROOT/configs/systemd/suwayomi-server-cpu-throttle.conf" /etc/systemd/system/suwayomi-server.service.d/cpu-throttle.conf
    fi
    if [ -f "$REPO_ROOT/configs/systemd/suwayomi-server-display.conf" ]; then
        cp "$REPO_ROOT/configs/systemd/suwayomi-server-display.conf" /etc/systemd/system/suwayomi-server.service.d/display.conf
    fi
    if [ -f "$REPO_ROOT/configs/systemd/suwayomi-server-java-library-path.conf" ]; then
        cp "$REPO_ROOT/configs/systemd/suwayomi-server-java-library-path.conf" /etc/systemd/system/suwayomi-server.service.d/java-library-path.conf
    fi

    # X Virtual Framebuffer (Xvfb) & AWT libraries for Headless Chromium / JCEF Turnstile bypass
    if ! command -v Xvfb >/dev/null 2>&1 || ! ldconfig -p 2>/dev/null | grep -q libXtst; then
        echo -e "  ${CYAN}🖥️ Installing Xvfb & X11 AWT libraries for headless Suwayomi browser engine...${NC}"
        case "$OS_FAMILY" in
            arch)   pacman -S --needed --noconfirm xorg-server-xvfb libxtst libxi || true ;;
            debian) apt-get install -y xvfb libxtst6 libxi6 || true ;;
            fedora) dnf install -y xorg-x11-server-Xvfb libXtst libXi || true ;;
        esac
    fi
    if [ -f "$REPO_ROOT/configs/systemd/xvfb.service" ]; then
        cp "$REPO_ROOT/configs/systemd/xvfb.service" /etc/systemd/system/
        systemctl daemon-reload 2>/dev/null || true
        if command -v Xvfb >/dev/null 2>&1; then
            systemctl enable --now xvfb.service 2>/dev/null || true
        fi
    fi

    # FlareSolverr Docker Compose Setup (Optional Cloudflare Clearance)
    if command -v docker >/dev/null 2>&1; then
        if [ -f "$REPO_ROOT/configs/docker/docker-compose.flaresolverr.yml" ]; then
            mkdir -p /opt/flaresolverr
            cp "$REPO_ROOT/configs/docker/docker-compose.flaresolverr.yml" /opt/flaresolverr/docker-compose.yml
        fi
    fi
fi

# SyncYomi Auto-Download
if [ "$INSTALL_SYNCYOMI" = "true" ]; then
    if command -v syncyomi >/dev/null 2>&1; then
        echo -e "  ${GREEN}✅ SyncYomi is already installed ($(command -v syncyomi)), skipping download.${NC}"
    else
        echo -e "  ${CYAN}📥 Auto-downloading and configuring SyncYomi...${NC}"
        if [ -x "$REPO_ROOT/configs/scripts/install-syncyomi.sh" ]; then
            "$REPO_ROOT/configs/scripts/install-syncyomi.sh" || true
        fi
    fi
    if [ -f "$REPO_ROOT/configs/scripts/syncyomi-suwayomi-bridge" ]; then
        cp "$REPO_ROOT/configs/scripts/syncyomi-suwayomi-bridge" /usr/local/bin/
        chmod 755 /usr/local/bin/syncyomi-suwayomi-bridge
    fi
    if [ -f "$REPO_ROOT/configs/systemd/syncyomi-suwayomi-bridge.service" ]; then
        cp "$REPO_ROOT/configs/systemd/syncyomi-suwayomi-bridge.service" /etc/systemd/system/
        systemctl enable --now syncyomi-suwayomi-bridge.service 2>/dev/null || true
    fi
fi

# FileBrowser Quantum Auto-Download
if [ "$INSTALL_FILEBROWSER" = "true" ]; then
    if command -v filebrowser >/dev/null 2>&1 || [ -x /usr/local/bin/filebrowser ]; then
        echo -e "  ${GREEN}✅ FileBrowser is already installed ($(command -v filebrowser 2>/dev/null || echo '/usr/local/bin/filebrowser')), skipping download.${NC}"
    else
        echo -e "  ${CYAN}📥 Auto-downloading FileBrowser binary...${NC}"
        curl -fsSL https://raw.githubusercontent.com/filebrowser/get/master/get.sh | bash || true
    fi
    if [ -x /usr/local/bin/filebrowser ] && [ ! -e /usr/local/bin/filebrowser-quantum ]; then
        ln -sfn /usr/local/bin/filebrowser /usr/local/bin/filebrowser-quantum
    fi
    mkdir -p /etc/filebrowser
    if [ ! -f /etc/filebrowser/config.yaml ] && [ -f "$REPO_ROOT/configs/filebrowser/config.yaml" ]; then
        sed "s|/home/pineapple|$USER_HOME|g" "$REPO_ROOT/configs/filebrowser/config.yaml" > /etc/filebrowser/config.yaml
    fi
    if [ -f "$REPO_ROOT/configs/systemd/filebrowser-quantum.service" ]; then
        sed "s/User=pineapple/User=$TARGET_USER/g; s/Group=pineapple/Group=$TARGET_USER/g; s|/home/pineapple|$USER_HOME|g" \
            "$REPO_ROOT/configs/systemd/filebrowser-quantum.service" > /etc/systemd/system/filebrowser-quantum.service
    fi
fi

# ─── PHASE 4: Apply Configurations & Deploy Services ──────────────────────────
echo ""
echo -e "${CYAN}─── 4. Applying Configurations & Deploying Services ────────────────────${NC}"

# 1. Setup and update .env configuration file
echo -e "${CYAN}⚙️ Writing server settings to .env...${NC}"
if [ ! -f "$REPO_ROOT/.env" ] && [ -f "$REPO_ROOT/.env.example" ]; then
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
fi

update_env_var() {
    local key="$1"
    local val="$2"
    local file="$REPO_ROOT/.env"
    [ ! -f "$file" ] && touch "$file"
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=\"${val}\"|" "$file"
    elif grep -q "^# *${key}=" "$file" 2>/dev/null; then
        sed -i "s|^# *${key}=.*|${key}=\"${val}\"|" "$file"
    else
        echo "${key}=\"${val}\"" >> "$file"
    fi
}

update_env_var "PROJECT_NAME" "$CFG_PROJECT_NAME"
update_env_var "SERVER_NAME" "$CFG_SERVER_NAME"
update_env_var "BRANDING_SUBTITLE" "$CFG_BRANDING_SUBTITLE"
update_env_var "APP_ICON" "$CFG_APP_ICON"
update_env_var "PORT" "$CFG_PORT"
update_env_var "SSH_USER" "$CFG_SSH_USER"
update_env_var "TAILSCALE_DOMAIN" "$CFG_TAILSCALE_DOMAIN"
update_env_var "OWNER_EMAIL" "$CFG_OWNER_EMAIL"
update_env_var "ADMIN_PASSWORD" "$CFG_ADMIN_PASSWORD"
update_env_var "STORAGE_DIR" "$CFG_STORAGE_DIR"

# Service toggle flags
update_env_var "ENABLE_SUWAYOMI" "$INSTALL_SUWAYOMI"
update_env_var "ENABLE_JELLYFIN" "$INSTALL_JELLYFIN"
update_env_var "ENABLE_TOR" "$INSTALL_TOR"
update_env_var "ENABLE_TAILSCALE_SSH" "$INSTALL_TAILSCALE"
update_env_var "ENABLE_SYNCTHING" "$INSTALL_SYNCTHING"
update_env_var "ENABLE_SYNCYOMI" "$INSTALL_SYNCYOMI"
update_env_var "ENABLE_FILEBROWSER" "$INSTALL_FILEBROWSER"
update_env_var "ENABLE_COUCHDB" "$INSTALL_COUCHDB"

chown "$TARGET_USER:$TARGET_USER" "$REPO_ROOT/.env" 2>/dev/null || true

# Update app_config.json if python is available
python3 -c "
import json, os
cfg_file = os.path.join('$REPO_ROOT', 'app_config.json')
try:
    with open(cfg_file, 'r') as f:
        data = json.load(f)
except Exception:
    data = {}
data['server_name'] = '$CFG_SERVER_NAME'
data['project_name'] = '$CFG_PROJECT_NAME'
data['display_name'] = '$CFG_SERVER_NAME'
data['branding_subtitle'] = '$CFG_BRANDING_SUBTITLE'
data['app_icon'] = '$CFG_APP_ICON'
data['port'] = int('$CFG_PORT')
with open(cfg_file, 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null || true
chown "$TARGET_USER:$TARGET_USER" "$REPO_ROOT/app_config.json" 2>/dev/null || true

# 2. Drive Hierarchy Scaffolding
DRIVE_ROOT="${CFG_STORAGE_DIR:-$USER_HOME/drive}"
if [ "$INSTALL_DRIVE_ENGINE" = "true" ]; then
    echo -e "${CYAN}📂 Scaffolding drive hierarchy at $DRIVE_ROOT...${NC}"
    mkdir -p "$DRIVE_ROOT"/{notes,backups,Media/{Manga,Movies,Shows,Music}}
    WALL_DIR="$USER_HOME/Wall"
    mkdir -p "$WALL_DIR"
    [ ! -e "$DRIVE_ROOT/Wallpapers" ] && ln -sfn "$WALL_DIR" "$DRIVE_ROOT/Wallpapers"

    if [ ! -f "$DRIVE_ROOT/.stignore" ]; then
        cat << 'STIGNORE_EOF' > "$DRIVE_ROOT/.stignore"
(?d)$RECYCLE.BIN
(?d).Trash-*
(?d)System Volume Information
(?d).syncthing.*.tmp
(?d).filebrowser.db*
(?d).cache
(?d)Wallpapers
(?d)Media/Manga
(?d)/shared
STIGNORE_EOF
        chown "$TARGET_USER:$TARGET_USER" "$DRIVE_ROOT/.stignore" 2>/dev/null || true
    fi

    if [ -f "$REPO_ROOT/configs/scripts/tinarchy-drive-sync" ]; then
        cp "$REPO_ROOT/configs/scripts/tinarchy-drive-sync" /usr/local/bin/tinarchy-drive-sync
        chmod +x /usr/local/bin/tinarchy-drive-sync
        ln -sfn /usr/local/bin/tinarchy-drive-sync /usr/local/bin/pinedash-drive-sync
    fi

    if [ -f "$REPO_ROOT/configs/systemd/pinedash-drive-sync.service" ]; then
        cp "$REPO_ROOT/configs/systemd/pinedash-drive-sync.service" /etc/systemd/system/
    fi

    if [ -f "$REPO_ROOT/configs/scripts/backup-drive-to-gdrive.sh" ]; then
        cp "$REPO_ROOT/configs/scripts/backup-drive-to-gdrive.sh" /usr/local/bin/backup-drive-to-gdrive
        chmod +x /usr/local/bin/backup-drive-to-gdrive
    fi

    if [ -f "$REPO_ROOT/configs/systemd/rclone-drive-backup.timer" ]; then
        cp "$REPO_ROOT/configs/systemd/rclone-drive-backup.timer" /etc/systemd/system/
        sed "s/User=pineapple/User=$TARGET_USER/g; s/Group=pineapple/Group=$TARGET_USER/g; s|/home/pineapple|$USER_HOME|g" \
            "$REPO_ROOT/configs/systemd/rclone-drive-backup.service" > /etc/systemd/system/rclone-drive-backup.service
    fi

    chown -R "$TARGET_USER:$TARGET_USER" "$DRIVE_ROOT" "$WALL_DIR" 2>/dev/null || true
    echo -e "${GREEN}✅ Unified drive structure initialized at $DRIVE_ROOT${NC}"
fi

# 3. Persistent Terminal (tmux + Zsh)
if [ "$INSTALL_TERMINAL" = "true" ]; then
    echo -e "${CYAN}🐚 Deploying persistent tmux and low-latency Zsh environment...${NC}"
    [ -f "$REPO_ROOT/configs/tmux/tmux.conf" ] && cp "$REPO_ROOT/configs/tmux/tmux.conf" "$USER_HOME/.tmux.conf"
    [ -f "$REPO_ROOT/configs/zsh/zshrc" ] && cp "$REPO_ROOT/configs/zsh/zshrc" "$USER_HOME/.zshrc"
    chown "$TARGET_USER:$TARGET_USER" "$USER_HOME/.tmux.conf" "$USER_HOME/.zshrc" 2>/dev/null || true
    echo -e "${GREEN}✅ Terminal configurations applied (.tmux.conf, .zshrc)${NC}"
fi

# 4. Nginx Reverse Proxy
if [ "$INSTALL_NGINX" = "true" ]; then
    echo -e "${CYAN}🌐 Deploying Nginx reverse proxy configuration...${NC}"
    mkdir -p /var/cache/nginx/suwayomi
    chown -R http:http /var/cache/nginx/suwayomi 2>/dev/null || chown -R www-data:www-data /var/cache/nginx/suwayomi 2>/dev/null || chown -R nginx:nginx /var/cache/nginx/suwayomi 2>/dev/null || true
    if [ -f "$REPO_ROOT/configs/nginx/nginx.conf" ]; then
        [ -f /etc/nginx/nginx.conf ] && cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak."$(date +%s)"
        if ! id -u pineapple >/dev/null 2>&1; then
            sed "s/user pineapple pineapple;/user $TARGET_USER $TARGET_USER;/g" "$REPO_ROOT/configs/nginx/nginx.conf" > /etc/nginx/nginx.conf
        else
            cp "$REPO_ROOT/configs/nginx/nginx.conf" /etc/nginx/nginx.conf
        fi
        if nginx -t 2>/dev/null; then
            echo -e "${GREEN}✅ Nginx syntax verified successfully.${NC}"
        else
            echo -e "${YELLOW}⚠️ Nginx syntax check had warnings or missing SSL certs; check /etc/nginx/nginx.conf${NC}"
        fi
    fi
fi

# 5. Syncthing Continuous Sync
if [ "$INSTALL_SYNCTHING" = "true" ]; then
    echo -e "${CYAN}🔄 Configuring Syncthing full drive sync with compression...${NC}"
    systemctl enable "syncthing@$TARGET_USER.service" 2>/dev/null || true
    systemctl start "syncthing@$TARGET_USER.service" 2>/dev/null || true

    sleep 2
    if command -v syncthing >/dev/null 2>&1; then
        sudo -u "$TARGET_USER" syncthing cli config defaults device compression set always 2>/dev/null || true
        sudo -u "$TARGET_USER" syncthing cli config defaults folder path set "$DRIVE_ROOT" 2>/dev/null || true
        sudo -u "$TARGET_USER" syncthing cli config options local-ann-enabled set false 2>/dev/null || true
        DEV_ID=$(sudo -u "$TARGET_USER" syncthing device-id 2>/dev/null || syncthing device-id 2>/dev/null || echo "")
        if [ -n "$DEV_ID" ]; then
            sudo -u "$TARGET_USER" syncthing cli config devices "$DEV_ID" compression set always 2>/dev/null || true
            SHARED_FID="${SYNCTHING_SHARED_FOLDER_ID:-shared}"
            SHARED_FLABEL="${SYNCTHING_SHARED_FOLDER_LABEL:-Shared}"
            EXISTING_FOLDERS=$(sudo -u "$TARGET_USER" syncthing cli config folders list 2>/dev/null || echo "")
            if echo "$EXISTING_FOLDERS" | grep -q "^${SHARED_FID}$"; then
                echo -e "${GREEN}✅ Folder '${SHARED_FID}' already exists in Syncthing.${NC}"
            elif [ -n "$EXISTING_FOLDERS" ] && [ "$SHARED_FID" = "shared" ] && echo "$EXISTING_FOLDERS" | grep -q -E "obsidian-vault|antigravity-share|default"; then
                echo -e "${YELLOW}ℹ️  Existing Syncthing folders detected (${EXISTING_FOLDERS//$'\n'/, }). Preserving current setup without forcing folder '${SHARED_FID}'.${NC}"
            else
                sudo -u "$TARGET_USER" syncthing cli config folders add \
                    --id "$SHARED_FID" \
                    --label "$SHARED_FLABEL" \
                    --path "$DRIVE_ROOT" \
                    --type sendreceive 2>/dev/null || true
                echo -e "${GREEN}✅ Folder '${SHARED_FID}' mapped to $DRIVE_ROOT with compression='always'.${NC}"
            fi
            echo -e "${GREEN}✅ Syncthing device ID configured:${NC} ${BOLD}$DEV_ID${NC}"
        fi
    fi
fi

# 6. Tor Anonymity Proxy & Global Exit Node
if [ "$INSTALL_TOR" = "true" ]; then
    echo -e "${CYAN}🧅 Configuring Tor SOCKS5 & Exit Node permissions...${NC}"
    [ -f "$REPO_ROOT/tor_exit_node.sh" ] && chmod +x "$REPO_ROOT/tor_exit_node.sh"
    [ -f "$REPO_ROOT/configs/scripts/tor_exit_node.sh" ] && chmod +x "$REPO_ROOT/configs/scripts/tor_exit_node.sh"
    
    SUDOERS_FILE="/etc/sudoers.d/99-tor-exit"
    echo "%wheel ALL=(ALL) NOPASSWD: $REPO_ROOT/tor_exit_node.sh *, $USER_HOME/server-dashboard/tor_exit_node.sh *" > "$SUDOERS_FILE"
    echo "%sudo ALL=(ALL) NOPASSWD: $REPO_ROOT/tor_exit_node.sh *, $USER_HOME/server-dashboard/tor_exit_node.sh *" >> "$SUDOERS_FILE"
    chmod 440 "$SUDOERS_FILE"
    echo -e "${GREEN}✅ Tor exit node sudoers rule configured at $SUDOERS_FILE${NC}"
fi

# 7. Tinarchy Dashboard Service Unit
if [ "$INSTALL_TINARCHY" = "true" ]; then
    echo -e "${CYAN}🍍 Deploying ${CFG_PROJECT_NAME} Dashboard systemd unit...${NC}"
    cat << EOF > /etc/systemd/system/tinarchy.service
[Unit]
Description=${CFG_PROJECT_NAME} Server Management Dashboard
After=network.target tailscaled.service
Wants=tailscaled.service

[Service]
Type=simple
User=${TARGET_USER}
WorkingDirectory=${REPO_ROOT}
ExecStart=/usr/bin/python3 ${REPO_ROOT}/server.py
Restart=always
RestartSec=5
EnvironmentFile=-${REPO_ROOT}/.env

[Install]
WantedBy=multi-user.target
EOF
    ln -sfn /etc/systemd/system/tinarchy.service /etc/systemd/system/server-dashboard.service
fi

# 8. Headless Display Sleep & Powerdown
if [ "$INSTALL_POWERDOWN" = "true" ]; then
    echo -e "${CYAN}💻 Applying Headless 0-Watt DPMS, Inactivity Sleep & Lid Management...${NC}"
    if [ -f "$REPO_ROOT/configs/scripts/tinarchy-display-sleep" ]; then
        install -m 755 "$REPO_ROOT/configs/scripts/tinarchy-display-sleep" /usr/local/bin/tinarchy-display-sleep
        ln -sfn /usr/local/bin/tinarchy-display-sleep /usr/local/bin/screen-off
        ln -sfn /usr/local/bin/tinarchy-display-sleep /usr/local/bin/screen-on
        ln -sfn /usr/local/bin/tinarchy-display-sleep /usr/local/bin/screen-toggle
    fi
    if [ -f "$REPO_ROOT/configs/systemd/tinarchy-display-sleep.service" ]; then
        cp "$REPO_ROOT/configs/systemd/tinarchy-display-sleep.service" /etc/systemd/system/
    fi
    if [ -f "$REPO_ROOT/configs/scripts/acpi-handler.sh" ]; then
        cp "$REPO_ROOT/configs/scripts/acpi-handler.sh" /etc/acpi/handler.sh
        chmod 755 /etc/acpi/handler.sh
    fi
    cat << 'UDEV_EOF' > /etc/udev/rules.d/90-backlight-power.rules
ACTION=="add|change", SUBSYSTEM=="backlight", RUN+="/bin/chmod a+w /sys/class/backlight/%k/bl_power /sys/class/backlight/%k/brightness"
UDEV_EOF
    udevadm trigger --subsystem-match=backlight 2>/dev/null || true

    if [ -f "$REPO_ROOT/configs/systemd/console-screen-blank.service" ]; then
        cp "$REPO_ROOT/configs/systemd/console-screen-blank.service" /etc/systemd/system/
    fi
    if [ -f "$REPO_ROOT/configs/systemd/getty-powersave.conf" ]; then
        mkdir -p /etc/systemd/system/getty@.service.d/
        cp "$REPO_ROOT/configs/systemd/getty-powersave.conf" /etc/systemd/system/getty@.service.d/powersave.conf
    fi
    if [ -f "$REPO_ROOT/configs/scripts/console-powersave.sh" ]; then
        cp "$REPO_ROOT/configs/scripts/console-powersave.sh" /etc/profile.d/console-powersave.sh
    fi
fi

# 9. Autonomous Resource Governor & Dynamic Network Autotuner
if [ -f "$REPO_ROOT/configs/scripts/tinarchy-resource-governor.py" ]; then
    echo -e "${CYAN}🌡️ Installing Tinarchy Autonomous Resource & Thermal Governor...${NC}"
    install -m 755 "$REPO_ROOT/configs/scripts/tinarchy-resource-governor.py" /usr/local/bin/tinarchy-resource-governor
    mkdir -p /var/log/tinarchy /etc/default
    if [ -f "$REPO_ROOT/configs/systemd/tinarchy-resource-governor.service" ]; then
        cp "$REPO_ROOT/configs/systemd/tinarchy-resource-governor.service" /etc/systemd/system/
    fi
fi

if [ -f "$REPO_ROOT/configs/scripts/tinarchy-net-autotune.py" ]; then
    echo -e "${CYAN}🌐 Installing Multicore Dynamic Network Autotuner...${NC}"
    install -m 755 "$REPO_ROOT/configs/scripts/tinarchy-net-autotune.py" /usr/local/bin/tinarchy-net-autotune
    if [ -f "$REPO_ROOT/configs/systemd/tinarchy-net-autotune.service" ]; then
        cp "$REPO_ROOT/configs/systemd/tinarchy-net-autotune.service" /etc/systemd/system/
    fi
fi

if [ -f "$REPO_ROOT/configs/scripts/suwayomi-precache-thumbnails" ]; then
    echo -e "${CYAN}📚 Installing Suwayomi Dual-Tier Thumbnail Pre-Cacher...${NC}"
    install -m 755 "$REPO_ROOT/configs/scripts/suwayomi-precache-thumbnails" /usr/local/bin/suwayomi-precache-thumbnails
    if [ -f "$REPO_ROOT/configs/systemd/suwayomi-precache.service" ]; then
        cp "$REPO_ROOT/configs/systemd/suwayomi-precache.service" /etc/systemd/system/
        sed -i "s/User=tin/User=$TARGET_USER/g" /etc/systemd/system/suwayomi-precache.service
    fi
    if [ -f "$REPO_ROOT/configs/systemd/suwayomi-precache.timer" ]; then
        cp "$REPO_ROOT/configs/systemd/suwayomi-precache.timer" /etc/systemd/system/
    fi
fi

# 10. High-Performance Virtual Memory & Network Sysctl Tuning (Adaptive Hardware Profiling)
if [ -f "$REPO_ROOT/configs/sysctl/99-server-optimization.conf" ]; then
    echo -e "${CYAN}🚀 Configuring kernel virtual memory & BBR network sysctl optimizations...${NC}"
    cp "$REPO_ROOT/configs/sysctl/99-server-optimization.conf" /etc/sysctl.d/

    # Auto-detect Swap Architecture (ZRAM vs Physical Disk Swap)
    MEM_PROFILE="${EXISTING_HARDWARE_MEMORY_PROFILE:-auto}"
    if [ "$MEM_PROFILE" = "auto" ] || [ -z "$MEM_PROFILE" ]; then
        if grep -q "zram" /proc/swaps 2>/dev/null || [ -e /dev/zram0 ]; then
            MEM_PROFILE="zram"
        else
            MEM_PROFILE="disk-swap"
        fi
    fi

    if [ "$MEM_PROFILE" = "zram" ] && [ -f "$REPO_ROOT/configs/sysctl/profiles/zram.conf" ]; then
        echo -e "${GREEN}   ⚡ Hardware Detected: Compressed ZRAM (/dev/zram0). Applying 3.3x RAM-expansion profile...${NC}"
        cat "$REPO_ROOT/configs/sysctl/profiles/zram.conf" >> /etc/sysctl.d/99-server-optimization.conf
    else
        echo -e "${GREEN}   ⚡ Hardware Detected: Physical Disk Swap. Applying low-swappiness disk protection profile...${NC}"
    fi

    sysctl --system >/dev/null 2>&1 || true
fi

# 11. Hardware RAM-Disk Tmpfiles Rules
if [ -d "$REPO_ROOT/configs/tmpfiles" ]; then
    echo -e "${CYAN}💾 Configuring RAM-Disk tmpfiles for instant media transcode caching...${NC}"
    cp "$REPO_ROOT/configs/tmpfiles/"*.conf /etc/tmpfiles.d/ 2>/dev/null || true
    systemd-tmpfiles --create /etc/tmpfiles.d/jellyfin-ramdisk.conf 2>/dev/null || true
fi

# 12. PESU WiFi Keepalive Daemon Service
if [ -f "$REPO_ROOT/configs/systemd/pesu-wifi.service" ]; then
    echo -e "${CYAN}📡 Deploying PESU WiFi Login Manager & Daemon unit...${NC}"
    cp "$REPO_ROOT/configs/systemd/pesu-wifi.service" /etc/systemd/system/
fi

# 13. Jellyfin High-Performance Configs (RAM-Disk Transcodes & Cache)
if [ -d "/etc/jellyfin" ] && [ -d "$REPO_ROOT/configs/jellyfin" ]; then
    echo -e "${CYAN}🍿 Applying Jellyfin RAM-disk transcode and caching optimizations...${NC}"
    cp -n "$REPO_ROOT/configs/jellyfin/"*.xml /etc/jellyfin/ 2>/dev/null || true
    chown -R jellyfin:jellyfin /etc/jellyfin/*.xml 2>/dev/null || true
fi

# ─── PHASE 5: Reload and Manage Systemd Services ──────────────────────────────
echo ""
echo -e "${CYAN}⚡ Managing systemd services...${NC}"
systemctl daemon-reload

manage_service() {
    local svc="$1"
    local name="$2"
    local enabled="$3"

    if [ "$enabled" = "true" ]; then
        if systemctl list-unit-files "$svc" >/dev/null 2>&1 || [ -f "/etc/systemd/system/$svc" ] || [ -f "/usr/lib/systemd/system/$svc" ]; then
            echo -ne "  Starting ${BOLD}${name}${NC} (${svc})... "
            systemctl enable --now "$svc" 2>/dev/null || true
            if systemctl is-active --quiet "$svc" 2>/dev/null; then
                echo -e "${GREEN}active (running)${NC}"
            else
                echo -e "${YELLOW}enabled (queued/inactive)${NC}"
            fi
        fi
    else
        # If disabled by user, stop if currently running
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            echo -ne "  Stopping unselected ${DIM}${name}${NC} (${svc})... "
            systemctl stop "$svc" 2>/dev/null || true
            systemctl disable "$svc" 2>/dev/null || true
            echo -e "${DIM}stopped${NC}"
        fi
    fi
}

manage_service "tailscaled.service" "Tailscale" "$INSTALL_TAILSCALE"
manage_service "tor.service" "Tor Proxy" "$INSTALL_TOR"
manage_service "nginx.service" "Nginx Reverse Proxy" "$INSTALL_NGINX"
manage_service "syncthing@$TARGET_USER.service" "Syncthing Sync" "$INSTALL_SYNCTHING"
manage_service "xvfb.service" "Xvfb Virtual Display (:99)" "$INSTALL_SUWAYOMI"
manage_service "suwayomi-server.service" "Suwayomi Manga" "$INSTALL_SUWAYOMI"
manage_service "suwayomi-precache.timer" "Suwayomi Thumbnail Pre-Cacher Timer" "$INSTALL_SUWAYOMI"
manage_service "jellyfin.service" "Jellyfin Media" "$INSTALL_JELLYFIN"
manage_service "syncyomi.service" "SyncYomi Manga Sync" "$INSTALL_SYNCYOMI"
manage_service "syncyomi-suwayomi-bridge.service" "SyncYomi-Suwayomi Bridge" "$INSTALL_SYNCYOMI"
manage_service "tinarchy-resource-governor.service" "Autonomous Resource Governor" "true"
manage_service "tinarchy-net-autotune.service" "Dynamic Network Tuner" "true"
manage_service "pesu-wifi.service" "PESU WiFi Portal Daemon" "true"
manage_service "filebrowser-quantum.service" "FileBrowser Quantum" "$INSTALL_FILEBROWSER"
manage_service "couchdb.service" "Obsidian LiveSync CouchDB" "$INSTALL_COUCHDB"
manage_service "pinedash-drive-sync.service" "Drive Sync Boot" "$INSTALL_DRIVE_ENGINE"
manage_service "acpid.service" "ACPI Event Daemon" "$INSTALL_POWERDOWN"
manage_service "tinarchy-display-sleep.service" "Display Inactivity Sleep" "$INSTALL_POWERDOWN"
manage_service "console-screen-blank.service" "Console Screen Blank" "$INSTALL_POWERDOWN"
manage_service "tinarchy.service" "${CFG_PROJECT_NAME} Dashboard" "$INSTALL_TINARCHY"

# ─── PHASE 6: Creator Credits & Acknowledgements ──────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}"
cat << 'EOF'
 ═══════════════════════════════════════════════════════════════════════
                 ⭐ CREATOR CREDITS & ACKNOWLEDGEMENTS ⭐
 ═══════════════════════════════════════════════════════════════════════
EOF
echo -e "${NC}"
echo -e "  🍍 ${BOLD}Tinarchy / Pinedash${NC}    : ${GREEN}Yatin Rajesh (@T1n777)${NC} (Control center & ecosystem)"
echo -e "  🌐 ${BOLD}NGINX${NC}                  : ${GREEN}Igor Sysoev & F5/NGINX Team${NC} (https://nginx.org)"
echo -e "  🔄 ${BOLD}Syncthing${NC}              : ${GREEN}Jakob Borg & The Syncthing Foundation${NC} (https://syncthing.net)"
echo -e "  📚 ${BOLD}Suwayomi Server${NC}        : ${GREEN}The Suwayomi Project Contributors${NC} (https://github.com/Suwayomi)"
echo -e "  📖 ${BOLD}SyncYomi${NC}               : ${GREEN}The SyncYomi Project Contributors${NC} (https://github.com/SyncYomi)"
echo -e "  🍿 ${BOLD}Jellyfin${NC}               : ${GREEN}The Jellyfin Project & Community${NC} (https://jellyfin.org)"
echo -e "  🧅 ${BOLD}Tor Project${NC}            : ${GREEN}Roger Dingledine, Nick Mathewson & Tor Project${NC} (https://torproject.org)"
echo -e "  🔑 ${BOLD}Tailscale${NC}              : ${GREEN}Avery Pennarun, Brad Fitzpatrick & Tailscale Inc.${NC} (https://tailscale.com)"
echo -e "  📂 ${BOLD}FileBrowser${NC}            : ${GREEN}FileBrowser Authors & Community${NC} (https://filebrowser.org)"
echo -e "  🔮 ${BOLD}CouchDB / LiveSync${NC}     : ${GREEN}Apache Software Foundation & vran-dev${NC}"
echo -e "  ⚡ ${BOLD}tmux${NC}                   : ${GREEN}Nicholas Marriott & Contributors${NC} (https://github.com/tmux)"
echo -e "  🐚 ${BOLD}Zsh${NC}                    : ${GREEN}Paul Falstad & Zsh Development Group${NC} (https://zsh.org)"
echo -e "  ☁️  ${BOLD}Rclone${NC}                 : ${GREEN}Nick Craig-Wood & Contributors${NC} (https://rclone.org)"
  echo -e "  🛡️  ${BOLD}FlareSolverr${NC}           : ${GREEN}The FlareSolverr Community${NC} (https://github.com/FlareSolverr/FlareSolverr)"
echo -e "${CYAN} ═══════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}${BOLD}🎉 Installation and configuration finished successfully!${NC}"
echo ""

# ─── PHASE 7: Immediate Dashboard Launch ──────────────────────────────────────
# Determine best accessible Dashboard URL
DASHBOARD_URL="http://127.0.0.1:${CFG_PORT:-8085}/"
if [ "$INSTALL_NGINX" = "true" ]; then
    if [ -n "$CFG_TAILSCALE_DOMAIN" ]; then
        DASHBOARD_URL="https://${CFG_TAILSCALE_DOMAIN}/"
    else
        TS_IP="$(tailscale ip -4 2>/dev/null || true)"
        if [ -n "$TS_IP" ]; then
            DASHBOARD_URL="http://${TS_IP}:8080/"
        else
            DASHBOARD_URL="http://127.0.0.1:8080/"
        fi
    fi
else
    TS_IP="$(tailscale ip -4 2>/dev/null || true)"
    if [ -n "$TS_IP" ]; then
        DASHBOARD_URL="http://${TS_IP}:${CFG_PORT:-8085}/"
    fi
fi

echo -e "  ${BOLD}Active Endpoints:${NC}"
echo -e "  • Dashboard Web UI : ${CYAN}${BOLD}${DASHBOARD_URL}${NC} (Port ${CFG_PORT:-8085})"
[ "$INSTALL_SYNCTHING" = "true" ]   && echo -e "  • Syncthing GUI    : ${CYAN}/syncthing/${NC} (Port 8384)"
[ "$INSTALL_SUWAYOMI" = "true" ]    && echo -e "  • Suwayomi Manga   : ${CYAN}/manga/${NC} (Port 4567)"
[ "$INSTALL_SYNCYOMI" = "true" ]    && echo -e "  • SyncYomi Web UI  : ${CYAN}http://127.0.0.1:8282${NC}"
[ "$INSTALL_JELLYFIN" = "true" ]    && echo -e "  • Jellyfin Media   : ${CYAN}:8096${NC}"
[ "$INSTALL_FILEBROWSER" = "true" ] && echo -e "  • FileBrowser      : ${CYAN}/files/${NC} (Port 8081/8082)"
[ "$INSTALL_COUCHDB" = "true" ]     && echo -e "  • CouchDB Fauxton  : ${CYAN}/couchdb/_utils/${NC} (Port 5984)"
echo ""

echo -e "${GREEN}${BOLD}🚀 Launching ${CFG_PROJECT_NAME} Dashboard immediately...${NC}"

# Open browser if a graphical session is active
LAUNCHED=false
if [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
    if command -v xdg-open >/dev/null 2>&1; then
        sudo -u "$TARGET_USER" DISPLAY="${DISPLAY:-:0}" WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-}" xdg-open "$DASHBOARD_URL" >/dev/null 2>&1 &
        LAUNCHED=true
    elif command -v open >/dev/null 2>&1; then
        open "$DASHBOARD_URL" >/dev/null 2>&1 &
        LAUNCHED=true
    fi
fi

# Fallback check: query loginctl or who for active graphical seat
if [ "$LAUNCHED" = "false" ]; then
    ACTIVE_SEAT_USER=$(loginctl list-sessions --no-legend 2>/dev/null | awk '{print $3}' | grep -v 'root' | head -n1 || echo "$TARGET_USER")
    if [ -n "$ACTIVE_SEAT_USER" ] && command -v xdg-open >/dev/null 2>&1; then
        sudo -u "$ACTIVE_SEAT_USER" DISPLAY=:0 xdg-open "$DASHBOARD_URL" >/dev/null 2>&1 &
        LAUNCHED=true
    fi
fi

if [ "$LAUNCHED" = "true" ]; then
    echo -e "  ${GREEN}✔ Dashboard opened in your browser at: ${CYAN}${BOLD}${DASHBOARD_URL}${NC}"
else
    echo -e "  ${DIM}💡 Running in headless terminal session. Open dashboard at:${NC}"
    echo -e "     👉 ${CYAN}${BOLD}${DASHBOARD_URL}${NC}"
fi
echo ""
