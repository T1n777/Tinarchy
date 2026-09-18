#!/usr/bin/env bash
# ==============================================================================
# 🍍 Tinarchy OS - Live ISO Build Engine
# ==============================================================================
# Builds a bootable hybrid UEFI/BIOS Arch Linux Live ISO with Tinarchy pre-loaded.
#
# Usage:
#   sudo ./packaging/iso/build.sh [OPTIONS]
#
# Options:
#   -o, --output <DIR>   Output directory for built ISO (default: dist/)
#   -w, --work <DIR>     Temporary work directory (default: /tmp/archiso-tinarchy)
#   -c, --clean          Clean temporary work directory before building
#   -h, --help           Show this help message and exit
# ==============================================================================
set -eo pipefail

BOLD='\033[1m'
CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROFILE_DIR="$SCRIPT_DIR"

OUT_DIR="$REPO_ROOT/dist"
WORK_DIR="/tmp/archiso-tinarchy"
CLEAN_FIRST=false

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help)
            echo "Usage: sudo $0 [OPTIONS]"
            echo ""
            echo "Builds the bootable Tinarchy OS Live ISO."
            echo ""
            echo "Options:"
            echo "  -o, --output <DIR>  Output directory for ISO (default: dist/)"
            echo "  -w, --work <DIR>    Temporary build workspace (default: /tmp/archiso-tinarchy)"
            echo "  -c, --clean         Clean build workspace prior to building"
            echo "  -h, --help          Show this help message and exit"
            exit 0
            ;;
        -o|--output)
            OUT_DIR="$2"
            shift 2
            ;;
        -w|--work)
            WORK_DIR="$2"
            shift 2
            ;;
        -c|--clean)
            CLEAN_FIRST=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}${BOLD}"
cat << 'EOF'
 🍍  ═══════════════════════════════════════════════════════════════════
        _____ _                      _           
       |_   _(_)_ __   __ _ _ __ ___| |__  _   _ 
        | | | | '_ \ / _` | '__/ __| '_ \| | | |
        | | | | | | | (_| | | | (__| | | | |_| |
        |_| |_|_| |_|\__,_|_|  \___|_| |_|\__, |
                                          |___/ 
        Tinarchy OS Live ISO Generator (archiso)
 ═══════════════════════════════════════════════════════════════════════
EOF
echo -e "${NC}"

# Root privileges check
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${YELLOW}⚡ Root privileges are required to build an Archiso image.${NC}"
    echo -e "   Re-executing with sudo..."
    exec sudo "$0" "$@"
fi

# Tooling check
if ! command -v mkarchiso >/dev/null 2>&1; then
    echo -e "${YELLOW}📦 mkarchiso is not installed. Installing archiso...${NC}"
    pacman -S --needed --noconfirm archiso
fi

# Storage check (at least 8 GB required for squashfs construction)
AVAILABLE_KB=$(df -k "$(dirname "$WORK_DIR")" | awk 'NR==2 {print $4}')
REQUIRED_KB=$((8 * 1024 * 1024))
if [ "$AVAILABLE_KB" -lt "$REQUIRED_KB" ]; then
    echo -e "${YELLOW}⚠️ Warning: Less than 8 GB free disk space available in $(dirname "$WORK_DIR").${NC}"
    echo -e "   Available: $((AVAILABLE_KB / 1024 / 1024)) GB. ISO build may run out of space."
fi

# Clean work directory if requested
if [ "$CLEAN_FIRST" = "true" ] && [ -d "$WORK_DIR" ]; then
    echo -e "${CYAN}🧹 Cleaning previous build work directory (${WORK_DIR})...${NC}"
    rm -rf "$WORK_DIR"
fi

mkdir -p "$OUT_DIR" "$WORK_DIR"

echo -e "  • Profile Directory : ${BOLD}${PROFILE_DIR}${NC}"
echo -e "  • Output Directory  : ${BOLD}${OUT_DIR}${NC}"
echo -e "  • Work Directory    : ${BOLD}${WORK_DIR}${NC}"
echo ""

echo -e "${GREEN}🚀 Invoking mkarchiso to build Tinarchy OS Live image...${NC}"
mkarchiso -v -w "$WORK_DIR" -o "$OUT_DIR" "$PROFILE_DIR"

# Generate SHA256 checksums for built ISOs
echo ""
echo -e "${CYAN}🔒 Calculating SHA256 checksums...${NC}"
for iso_file in "$OUT_DIR"/tinarchy-os-*.iso; do
    if [ -f "$iso_file" ]; then
        sha256sum "$iso_file" > "${iso_file}.sha256"
        echo -e "  ${GREEN}✔ Checksum:${NC} $(cat "${iso_file}.sha256")"
    fi
done

echo ""
echo -e "${GREEN}${BOLD}🎉 Tinarchy OS Live ISO built successfully!${NC}"
echo -e "  Output ISOs and checksums located in: ${BOLD}${OUT_DIR}${NC}"
echo ""
echo -e "  ${BOLD}To flash to USB:${NC}"
echo -e "    # dd bs=4M if=${OUT_DIR}/tinarchy-os-*.iso of=/dev/sdX conv=fsync oflag=direct status=progress"
echo ""
echo -e "  ${BOLD}To test in QEMU:${NC}"
echo -e "    $ run_archiso -i ${OUT_DIR}/tinarchy-os-*.iso"
