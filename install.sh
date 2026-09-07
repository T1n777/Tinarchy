#!/usr/bin/env bash
# ==============================================================================
# 🍍 Tinarchy Server Ecosystem - Master Interactive Installer & Configurator
# ==============================================================================
# Prompts for each server/service individually upfront, prompts for modifiable
# server personal settings (identity, credentials, paths), batch installs
# packages, deploys configurations, enables services, and credits creators.
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
            echo "Prompts for each server individually and all modifiable personal settings upfront,"
            echo "batch installs packages, applies configs, enables services, and credits creators."
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
            AUTO_YES=true
            ;;
    esac
done

# ─── Read Existing Configurations (if any) ────────────────────────────────────
EXISTING_SERVER_NAME=""
EXISTING_PROJECT_NAME=""
EXISTING_BRANDING_SUBTITLE=""
EXISTING_APP_ICON=""
EXISTING_SSH_USER=""
EXISTING_TAILSCALE_DOMAIN=""
EXISTING_OWNER_EMAIL=""
EXISTING_ADMIN_PASSWORD=""
EXISTING_STORAGE_DIR=""

if [ -f "$REPO_ROOT/.env" ]; then
    EXISTING_SERVER_NAME=$(grep -E '^SERVER_NAME=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_PROJECT_NAME=$(grep -E '^PROJECT_NAME=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_BRANDING_SUBTITLE=$(grep -E '^BRANDING_SUBTITLE=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_APP_ICON=$(grep -E '^APP_ICON=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_SSH_USER=$(grep -E '^SSH_USER=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_TAILSCALE_DOMAIN=$(grep -E '^TAILSCALE_DOMAIN=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_OWNER_EMAIL=$(grep -E '^OWNER_EMAIL=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_ADMIN_PASSWORD=$(grep -E '^ADMIN_PASSWORD=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    EXISTING_STORAGE_DIR=$(grep -E '^STORAGE_DIR=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
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

# ─── PHASE 1A: Service Selection Prompts ──────────────────────────────────────
echo -e "${CYAN}─── 1. Interactive Service Selection ──────────────────────────────────${NC}"
echo -e "Select which server components and daemons you want to activate."
echo ""

# 1. Core Dashboard
echo -e "${CYAN}[1/10]${NC} ${BOLD}Tinarchy Dashboard Control Center${NC}"
echo -e "       ${DIM}Telemetry UI, Pywal Dynamic Theming, Tailscale Whois RBAC & API daemon (:8085)${NC}"
echo -e "       ${DIM}Creator: ${GREEN}Yatin Rajesh (@T1n777)${NC} - https://github.com/T1n777/Tinarchy${NC}"
ask_choice "Install and configure Tinarchy Dashboard?" "y" INSTALL_TINARCHY
echo ""

# 2. Nginx Reverse Proxy
echo -e "${CYAN}[2/10]${NC} ${BOLD}Nginx Reverse Proxy & SSL Engine${NC}"
echo -e "       ${DIM}High-performance HTTP/2 reverse proxy for Ports 80, 443, 8080 with TLS 1.3${NC}"
echo -e "       ${DIM}Creator: ${GREEN}Igor Sysoev & NGINX Team${NC} - https://nginx.org${NC}"
ask_choice "Install and configure Nginx Reverse Proxy?" "y" INSTALL_NGINX
echo ""

# 3. Syncthing Full Drive Sync
echo -e "${CYAN}[3/10]${NC} ${BOLD}Syncthing Continuous Folder Sync${NC}"
echo -e "       ${DIM}Private, decentralized continuous file sync for drive directory with LZ4 compression${NC}"
echo -e "       ${DIM}Creator: ${GREEN}Jakob Borg & The Syncthing Foundation${NC} - https://syncthing.net${NC}"
ask_choice "Install and configure Syncthing Full Folder Sync?" "y" INSTALL_SYNCTHING
echo ""

# 4. Suwayomi Manga Server
echo -e "${CYAN}[4/10]${NC} ${BOLD}Suwayomi Server (Manga Library)${NC}"
echo -e "       ${DIM}Free and open source manga reader server compatible with Tachiyomi / Mihon (:4567)${NC}"
echo -e "       ${DIM}Creator: ${GREEN}The Suwayomi Project Contributors${NC} - https://github.com/Suwayomi${NC}"
ask_choice "Install and configure Suwayomi Manga Server?" "y" INSTALL_SUWAYOMI
echo ""

# 5. SyncYomi Reading Progress Sync
echo -e "${CYAN}[5/10]${NC} ${BOLD}SyncYomi (Manga Progress Sync Daemon)${NC}"
echo -e "       ${DIM}Automated reading history and progress synchronization across all client devices (:8282)${NC}"
echo -e "       ${DIM}Creator: ${GREEN}The SyncYomi Project Contributors${NC} - https://github.com/SyncYomi/SyncYomi${NC}"
ask_choice "Install and configure SyncYomi Daemon?" "n" INSTALL_SYNCYOMI
echo ""

# 6. Jellyfin Media Server
echo -e "${CYAN}[6/10]${NC} ${BOLD}Jellyfin Media Server${NC}"
echo -e "       ${DIM}The volunteer-built media streaming system for movies, TV series and home media (:8096)${NC}"
echo -e "       ${DIM}Creator: ${GREEN}The Jellyfin Project & Community${NC} - https://jellyfin.org${NC}"
ask_choice "Install and configure Jellyfin Media Server?" "y" INSTALL_JELLYFIN
echo ""

# 7. Tor Anonymity Proxy & Global Exit Node
echo -e "${CYAN}[7/10]${NC} ${BOLD}Tor SOCKS5 Proxy & Global Exit Node${NC}"
echo -e "       ${DIM}Standalone onion proxy (:9050) with automated Tailscale WireGuard NAT exit routing${NC}"
echo -e "       ${DIM}Creator: ${GREEN}The Tor Project${NC} - https://www.torproject.org${NC}"
ask_choice "Install and configure Tor Proxy & Exit Node?" "y" INSTALL_TOR
echo ""

# 8. Tailscale Mesh Network & SSH
echo -e "${CYAN}[8/10]${NC} ${BOLD}Tailscale WireGuard Mesh & Tailscale SSH${NC}"
echo -e "       ${DIM}Encrypted zero-config mesh overlay network with keyless SSH terminal access${NC}"
echo -e "       ${DIM}Creator: ${GREEN}Avery Pennarun, Brad Fitzpatrick & Tailscale Inc.${NC} - https://tailscale.com${NC}"
ask_choice "Install and configure Tailscale & Tailscale SSH?" "y" INSTALL_TAILSCALE
echo ""

# 9. Persistent Terminal Ecosystem (tmux + Zsh)
echo -e "${CYAN}[9/10]${NC} ${BOLD}Persistent Terminal Ecosystem (tmux + Zsh)${NC}"
echo -e "       ${DIM}Auto-attaching tmux (:main), 50K scrollback, instant Esc, and low-latency Zsh shell${NC}"
echo -e "       ${DIM}Creator: ${GREEN}Nicholas Marriott (tmux)${NC} & ${GREEN}Paul Falstad / Zsh Development Group${NC}"
ask_choice "Install Persistent Terminal Ecosystem (tmux + Zsh)?" "y" INSTALL_TERMINAL
echo ""

# 10. Unified Drive Engine & Cloud Backups
echo -e "${CYAN}[10/10]${NC} ${BOLD}Unified Drive Engine & Rclone Cloud Backups${NC}"
echo -e "       ${DIM}Drive folder hierarchy, local symlinks, and automated cloud backups${NC}"
echo -e "       ${DIM}Creator: ${GREEN}Tinarchy Team${NC} & ${GREEN}Nick Craig-Wood (Rclone)${NC} - https://rclone.org${NC}"
ask_choice "Install Unified Drive Engine & Cloud Backups?" "y" INSTALL_DRIVE_ENGINE
echo ""

# Optional 11: Headless Laptop Powerdown
INSTALL_POWERDOWN=false
if [ -d /sys/class/power_supply ] && grep -q -i "battery" /sys/class/power_supply/*/type 2>/dev/null; then
    echo -e "${YELLOW}⚡ Laptop battery hardware detected!${NC}"
    echo -e "       ${DIM}Configures 0-Watt DPMS display powerdown after 3min console inactivity and lid sleep${NC}"
    ask_choice "Configure Headless Laptop Display Powerdown & Lid Handling?" "y" INSTALL_POWERDOWN
    echo ""
fi

# ─── PHASE 1B: Server Personalization & Modifiable Settings ───────────────────
echo -e "${CYAN}─── 2. Server Personalization & Settings ───────────────────────────────${NC}"
echo -e "Configure instance branding, identity, storage paths, and credentials."
echo -e "Press ${BOLD}Enter${NC} to accept the bracketed default values."
echo ""

# 1. Server Display Name
DETECTED_HOST_PRETTY="$(echo "$SYS_HOST" | sed 's/[-_]/ /g' | awk '{for(i=1;i<=NF;i++)sub(/./,toupper(substr($i,1,1)),$i)}1')"
DEFAULT_SERVER_NAME="${EXISTING_SERVER_NAME:-$DETECTED_HOST_PRETTY}"
ask_input "Server Display Name" "$DEFAULT_SERVER_NAME" CFG_SERVER_NAME

# 2. Project / Suite Name
DEFAULT_PROJECT_NAME="${EXISTING_PROJECT_NAME:-Tinarchy}"
ask_input "Project / Suite Name" "$DEFAULT_PROJECT_NAME" CFG_PROJECT_NAME

# 3. Branding Subtitle
DEFAULT_SUBTITLE="${EXISTING_BRANDING_SUBTITLE:-Server Control Center}"
ask_input "Branding Subtitle" "$DEFAULT_SUBTITLE" CFG_BRANDING_SUBTITLE

# 4. App Icon / Emoji
DEFAULT_ICON="${EXISTING_APP_ICON:-🍍}"
ask_input "Server Emoji Icon" "$DEFAULT_ICON" CFG_APP_ICON

# 5. Primary SSH User
DEFAULT_SSH_USER="${EXISTING_SSH_USER:-$TARGET_USER}"
ask_input "Primary SSH Username" "$DEFAULT_SSH_USER" CFG_SSH_USER

# 6. Tailscale MagicDNS Domain
MAGIC_SUFFIX="$(tailscale status --json 2>/dev/null | grep -o '"MagicDNSSuffix": *"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
DETECTED_DOMAIN=""
[ -n "$MAGIC_SUFFIX" ] && DETECTED_DOMAIN="${SYS_HOST}.${MAGIC_SUFFIX}"
DEFAULT_TS_DOMAIN="${EXISTING_TAILSCALE_DOMAIN:-$DETECTED_DOMAIN}"
ask_input "Tailscale MagicDNS Domain" "$DEFAULT_TS_DOMAIN" CFG_TAILSCALE_DOMAIN

# 7. Owner Email
DETECTED_EMAIL="$(tailscale status --json 2>/dev/null | grep -o '"LoginName": *"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
DEFAULT_OWNER_EMAIL="${EXISTING_OWNER_EMAIL:-$DETECTED_EMAIL}"
ask_input "Owner Email (Tailscale Identity)" "$DEFAULT_OWNER_EMAIL" CFG_OWNER_EMAIL

# 8. Web Admin Password
DEFAULT_ADMIN_PASS="${EXISTING_ADMIN_PASSWORD:-changeme}"
ask_input "Dashboard Web Admin Password" "$DEFAULT_ADMIN_PASS" CFG_ADMIN_PASSWORD true

# 9. Unified Drive Storage Directory
DEFAULT_STORAGE_DIR="${EXISTING_STORAGE_DIR:-$USER_HOME/drive}"
ask_input "Unified Drive Storage Directory" "$DEFAULT_STORAGE_DIR" CFG_STORAGE_DIR

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
echo -e " ${BOLD}Activated Services:${NC}"
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
format_summary "Headless Display 0W Powerdown"       "$INSTALL_POWERDOWN"

echo ""
echo -e " ${BOLD}Personal Server Settings:${NC}"
echo -e "   • Server Display Name : ${BOLD}${CFG_SERVER_NAME}${NC} (${CFG_APP_ICON})"
echo -e "   • Project Suite Name  : ${BOLD}${CFG_PROJECT_NAME}${NC}"
echo -e "   • Branding Subtitle   : ${BOLD}${CFG_BRANDING_SUBTITLE}${NC}"
echo -e "   • Primary SSH User    : ${BOLD}${CFG_SSH_USER}${NC}"
echo -e "   • Tailscale Domain    : ${BOLD}${CFG_TAILSCALE_DOMAIN:-None}${NC}"
echo -e "   • Owner Email         : ${BOLD}${CFG_OWNER_EMAIL:-None}${NC}"
echo -e "   • Web Admin Password  : ${BOLD}********${NC}"
echo -e "   • Drive Storage Path  : ${BOLD}${CFG_STORAGE_DIR}${NC}"
echo -e "${CYAN}───────────────────────────────────────────────────────────────────────${NC}"

ask_choice "Proceed with batch installation and configuration?" "y" PROCEED_INSTALL
if [ "$PROCEED_INSTALL" != "true" ]; then
    echo -e "${YELLOW}Installation aborted by user. No changes were made.${NC}"
    exit 0
fi

echo ""
echo -e "${GREEN}🚀 Beginning batch installation and configuration...${NC}"
echo ""

# ─── PHASE 2: Consolidated Dependency Resolution ──────────────────────────────
PACKAGES_TO_INSTALL=()

case "$OS_FAMILY" in
    arch)
        [ "$INSTALL_TINARCHY" = "true" ]     && PACKAGES_TO_INSTALL+=('python' 'python-pillow' 'python-requests')
        [ "$INSTALL_NGINX" = "true" ]        && PACKAGES_TO_INSTALL+=('nginx')
        [ "$INSTALL_SYNCTHING" = "true" ]    && PACKAGES_TO_INSTALL+=('syncthing')
        [ "$INSTALL_JELLYFIN" = "true" ]     && PACKAGES_TO_INSTALL+=('jellyfin-server' 'jellyfin-web')
        [ "$INSTALL_TOR" = "true" ]          && PACKAGES_TO_INSTALL+=('tor' 'iptables')
        [ "$INSTALL_TAILSCALE" = "true" ]    && PACKAGES_TO_INSTALL+=('tailscale')
        [ "$INSTALL_TERMINAL" = "true" ]     && PACKAGES_TO_INSTALL+=('tmux' 'zsh')
        [ "$INSTALL_DRIVE_ENGINE" = "true" ] && PACKAGES_TO_INSTALL+=('rclone')
        ;;
    debian)
        [ "$INSTALL_TINARCHY" = "true" ]     && PACKAGES_TO_INSTALL+=('python3' 'python3-pil' 'python3-requests')
        [ "$INSTALL_NGINX" = "true" ]        && PACKAGES_TO_INSTALL+=('nginx')
        [ "$INSTALL_SYNCTHING" = "true" ]    && PACKAGES_TO_INSTALL+=('syncthing')
        [ "$INSTALL_JELLYFIN" = "true" ]     && PACKAGES_TO_INSTALL+=('jellyfin')
        [ "$INSTALL_TOR" = "true" ]          && PACKAGES_TO_INSTALL+=('tor' 'iptables')
        [ "$INSTALL_TAILSCALE" = "true" ]    && PACKAGES_TO_INSTALL+=('tailscale')
        [ "$INSTALL_TERMINAL" = "true" ]     && PACKAGES_TO_INSTALL+=('tmux' 'zsh')
        [ "$INSTALL_DRIVE_ENGINE" = "true" ] && PACKAGES_TO_INSTALL+=('rclone')
        ;;
    fedora)
        [ "$INSTALL_TINARCHY" = "true" ]     && PACKAGES_TO_INSTALL+=('python3' 'python3-pillow' 'python3-requests')
        [ "$INSTALL_NGINX" = "true" ]        && PACKAGES_TO_INSTALL+=('nginx')
        [ "$INSTALL_SYNCTHING" = "true" ]    && PACKAGES_TO_INSTALL+=('syncthing')
        [ "$INSTALL_JELLYFIN" = "true" ]     && PACKAGES_TO_INSTALL+=('jellyfin')
        [ "$INSTALL_TOR" = "true" ]          && PACKAGES_TO_INSTALL+=('tor' 'iptables')
        [ "$INSTALL_TAILSCALE" = "true" ]    && PACKAGES_TO_INSTALL+=('tailscale')
        [ "$INSTALL_TERMINAL" = "true" ]     && PACKAGES_TO_INSTALL+=('tmux' 'zsh')
        [ "$INSTALL_DRIVE_ENGINE" = "true" ] && PACKAGES_TO_INSTALL+=('rclone')
        ;;
esac

# Batch install packages via package manager
if [ ${#PACKAGES_TO_INSTALL[@]} -gt 0 ]; then
    echo -e "${CYAN}📦 Installing ${#PACKAGES_TO_INSTALL[@]} package dependencies:${NC} ${PACKAGES_TO_INSTALL[*]}"
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

# ─── PHASE 3: Apply Configurations & Deploy Services ──────────────────────────

# 1. Setup and update .env configuration file
echo -e "${CYAN}⚙️ Writing server personal settings to .env...${NC}"
if [ ! -f "$REPO_ROOT/.env" ] && [ -f "$REPO_ROOT/.env.example" ]; then
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
fi

update_env_var() {
    local key="$1"
    local val="$2"
    local file="$REPO_ROOT/.env"
    if [ ! -f "$file" ]; then
        touch "$file"
    fi
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=\"${val}\"|" "$file"
    elif grep -q "^# *${key}=" "$file" 2>/dev/null; then
        sed -i "s|^# *${key}=.*|${key}=\"${val}\"|" "$file"
    else
        echo "${key}=\"${val}\"" >> "$file"
    fi
}

update_env_var "SERVER_NAME" "$CFG_SERVER_NAME"
update_env_var "PROJECT_NAME" "$CFG_PROJECT_NAME"
update_env_var "BRANDING_SUBTITLE" "$CFG_BRANDING_SUBTITLE"
update_env_var "APP_ICON" "$CFG_APP_ICON"
update_env_var "SSH_USER" "$CFG_SSH_USER"
update_env_var "TAILSCALE_DOMAIN" "$CFG_TAILSCALE_DOMAIN"
update_env_var "OWNER_EMAIL" "$CFG_OWNER_EMAIL"
update_env_var "ADMIN_PASSWORD" "$CFG_ADMIN_PASSWORD"
update_env_var "STORAGE_DIR" "$CFG_STORAGE_DIR"
update_env_var "ENABLE_SYNCYOMI" "$INSTALL_SYNCYOMI"

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
with open(cfg_file, 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null || true
chown "$TARGET_USER:$TARGET_USER" "$REPO_ROOT/app_config.json" 2>/dev/null || true

# 2. Drive Hierarchy Scaffolding
DRIVE_ROOT="${CFG_STORAGE_DIR:-$USER_HOME/drive}"
if [ "$INSTALL_DRIVE_ENGINE" = "true" ]; then
    echo -e "${CYAN}📂 Scaffolding drive hierarchy at $DRIVE_ROOT...${NC}"
    mkdir -p "$DRIVE_ROOT"/{notes,shared/backups,Media/{Manga,Movies,Shows,Music}}
    WALL_DIR="$USER_HOME/Wall"
    mkdir -p "$WALL_DIR"
    [ ! -e "$DRIVE_ROOT/Wallpapers" ] && ln -sfn "$WALL_DIR" "$DRIVE_ROOT/Wallpapers"

    # Install drive-sync script
    if [ -f "$REPO_ROOT/configs/scripts/tinarchy-drive-sync" ]; then
        cp "$REPO_ROOT/configs/scripts/tinarchy-drive-sync" /usr/local/bin/tinarchy-drive-sync
        chmod +x /usr/local/bin/tinarchy-drive-sync
        ln -sfn /usr/local/bin/tinarchy-drive-sync /usr/local/bin/pinedash-drive-sync
    fi

    # Deploy drive sync systemd unit
    if [ -f "$REPO_ROOT/configs/systemd/pinedash-drive-sync.service" ]; then
        cp "$REPO_ROOT/configs/systemd/pinedash-drive-sync.service" /etc/systemd/system/
    fi

    # Deploy rclone timer if available
    if [ -f "$REPO_ROOT/configs/systemd/rclone-drive-backup.timer" ]; then
        cp "$REPO_ROOT/configs/systemd/rclone-drive-backup.timer" /etc/systemd/system/
        cp "$REPO_ROOT/configs/systemd/rclone-drive-backup.service" /etc/systemd/system/
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
    if [ -f "$REPO_ROOT/configs/nginx/nginx.conf" ]; then
        # Backup existing
        [ -f /etc/nginx/nginx.conf ] && cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak."$(date +%s)"
        cp "$REPO_ROOT/configs/nginx/nginx.conf" /etc/nginx/nginx.conf
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
    systemctl enable "syncthing@$TARGET_USER.service" || true
    systemctl start "syncthing@$TARGET_USER.service" || true

    sleep 2
    if command -v syncthing >/dev/null 2>&1; then
        syncthing cli config defaults device compression set always 2>/dev/null || true
        DEV_ID=$(syncthing device-id 2>/dev/null || echo "")
        if [ -n "$DEV_ID" ]; then
            syncthing cli config devices "$DEV_ID" compression set always 2>/dev/null || true
            if ! syncthing cli config folders list 2>/dev/null | grep -q "shared-drive"; then
                syncthing cli config folders add \
                    --id shared-drive \
                    --label "Shared Drive" \
                    --path "$DRIVE_ROOT" \
                    --type sendreceive 2>/dev/null || true
            fi
            echo -e "${GREEN}✅ Syncthing device ID configured:${NC} ${BOLD}$DEV_ID${NC}"
            echo -e "${GREEN}✅ Folder 'shared-drive' mapped to $DRIVE_ROOT with compression='always'.${NC}"
        fi
    fi
fi

# 6. SyncYomi Installation
if [ "$INSTALL_SYNCYOMI" = "true" ]; then
    echo -e "${CYAN}📖 Installing and deploying SyncYomi...${NC}"
    if [ -x "$REPO_ROOT/configs/scripts/install-syncyomi.sh" ]; then
        "$REPO_ROOT/configs/scripts/install-syncyomi.sh" || true
    fi
fi

# 7. Tor Anonymity Proxy & Global Exit Node
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

# 8. Tinarchy Dashboard Service
if [ "$INSTALL_TINARCHY" = "true" ]; then
    echo -e "${CYAN}🍍 Deploying Tinarchy Dashboard systemd unit...${NC}"
    if [ -f "$REPO_ROOT/configs/systemd/tinarchy.service" ]; then
        sed "s/User=pineapple/User=$TARGET_USER/g; s|/home/pineapple|$USER_HOME|g" \
            "$REPO_ROOT/configs/systemd/tinarchy.service" > /etc/systemd/system/tinarchy.service
        ln -sfn /etc/systemd/system/tinarchy.service /etc/systemd/system/server-dashboard.service
    fi
fi

# 9. Headless Laptop Powerdown
if [ "$INSTALL_POWERDOWN" = "true" ]; then
    echo -e "${CYAN}💻 Applying Headless Laptop 0-Watt DPMS & Lid Management...${NC}"
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

# ─── PHASE 4: Reload and Enable Systemd Services ──────────────────────────────
echo ""
echo -e "${CYAN}⚡ Reloading systemd daemon and starting services...${NC}"
systemctl daemon-reload

start_and_enable() {
    local svc="$1"
    local name="$2"
    if systemctl list-unit-files "$svc" >/dev/null 2>&1 || [ -f "/etc/systemd/system/$svc" ]; then
        echo -ne "  Starting ${BOLD}${name}${NC} (${svc})... "
        systemctl enable --now "$svc" 2>/dev/null || true
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            echo -e "${GREEN}active (running)${NC}"
        else
            echo -e "${YELLOW}enabled (queued/inactive)${NC}"
        fi
    fi
}

[ "$INSTALL_TAILSCALE" = "true" ]    && start_and_enable "tailscaled.service" "Tailscale"
[ "$INSTALL_TOR" = "true" ]          && start_and_enable "tor.service" "Tor Proxy"
[ "$INSTALL_NGINX" = "true" ]        && start_and_enable "nginx.service" "Nginx Reverse Proxy"
[ "$INSTALL_SYNCTHING" = "true" ]    && start_and_enable "syncthing@$TARGET_USER.service" "Syncthing Sync"
[ "$INSTALL_SUWAYOMI" = "true" ]     && start_and_enable "suwayomi-server.service" "Suwayomi Manga"
[ "$INSTALL_JELLYFIN" = "true" ]     && start_and_enable "jellyfin.service" "Jellyfin Media"
[ "$INSTALL_SYNCYOMI" = "true" ]     && start_and_enable "syncyomi.service" "SyncYomi Manga Sync"
[ "$INSTALL_DRIVE_ENGINE" = "true" ] && start_and_enable "pinedash-drive-sync.service" "Drive Sync Boot"
[ "$INSTALL_POWERDOWN" = "true" ]    && start_and_enable "console-screen-blank.service" "Console Screen Blank"
[ "$INSTALL_TINARCHY" = "true" ]     && start_and_enable "tinarchy.service" "Tinarchy Dashboard"

# ─── PHASE 5: Creator Credits & Completion Banner ─────────────────────────────
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
echo -e "  ⚡ ${BOLD}tmux${NC}                   : ${GREEN}Nicholas Marriott & Contributors${NC} (https://github.com/tmux)"
echo -e "  🐚 ${BOLD}Zsh${NC}                    : ${GREEN}Paul Falstad & Zsh Development Group${NC} (https://zsh.org)"
echo -e "  ☁️  ${BOLD}Rclone${NC}                 : ${GREEN}Nick Craig-Wood & Contributors${NC} (https://rclone.org)"
echo -e "${CYAN} ═══════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}${BOLD}🎉 Installation and configuration finished successfully!${NC}"
echo ""
echo -e "  ${BOLD}Access your server dashboard:${NC}"
if [ -n "$CFG_TAILSCALE_DOMAIN" ]; then
    echo -e "  • Tailscale HTTPS : ${CYAN}https://${CFG_TAILSCALE_DOMAIN}/${NC} (or http://127.0.0.1:8085)"
else
    echo -e "  • Dashboard HTTP  : ${CYAN}http://127.0.0.1:8085/${NC}"
fi
echo -e "  • Syncthing GUI   : ${CYAN}/syncthing/${NC} (Port 8384)"
echo -e "  • Syncthing Guide : ${CYAN}/syncthing${NC}"
echo -e "  • Suwayomi Manga  : ${CYAN}/manga/${NC} (Port 4567)"
if [ "$INSTALL_SYNCYOMI" = "true" ]; then
echo -e "  • SyncYomi Web UI : ${CYAN}http://127.0.0.1:8282${NC}"
fi
if [ "$INSTALL_JELLYFIN" = "true" ]; then
echo -e "  • Jellyfin Media  : ${CYAN}:8096${NC}"
fi
echo ""
