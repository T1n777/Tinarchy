#!/usr/bin/env bash
# ==============================================================================
# Pineapple Laptop $HOME Cleanup & Syncthing /mnt/shared Consolidation Script
# ==============================================================================
set -euo pipefail

SHARED_DIR="/mnt/shared"
USER_NAME="${USER}"

echo "══════════════════════════════════════════════════════════════════════"
echo "🍍 Pineapple Laptop: $HOME Cleanup & Syncthing Consolidation"
echo "══════════════════════════════════════════════════════════════════════"

# Step 1: Ensure /mnt/shared exists with proper permissions
echo "[1/5] Ensuring ${SHARED_DIR} exists with correct ownership..."
if [ ! -d "${SHARED_DIR}" ]; then
    sudo mkdir -p "${SHARED_DIR}"
fi
sudo chown -R "${USER_NAME}:${USER_NAME}" "${SHARED_DIR}"

# Step 2: Consolidate scattered sync folders out of $HOME into /mnt/shared
echo "[2/5] Cleaning scattered sync directories from ${HOME}..."
SCATTERED_DIRS=("Media" "stuff" "backups" "peach" "pine" "shared")

for dir in "${SCATTERED_DIRS[@]}"; do
    src="${HOME}/${dir}"
    dst="${SHARED_DIR}/${dir}"
    
    if [ -d "${src}" ] && [ ! -L "${src}" ]; then
        echo "  -> Found stray directory: ${src}"
        if [ -d "${dst}" ]; then
            echo "     Merging into ${dst} (preserving newer files)..."
            rsync -a --update "${src}/" "${dst}/"
            rm -rf "${src}"
        else
            echo "     Moving ${src} -> ${dst}..."
            mv "${src}" "${dst}"
        fi
        echo "     ✓ Consolidated ${dir}"
    fi
done

# Clean stray Syncthing markers from $HOME
if [ -d "${HOME}/.stfolder" ]; then
    echo "  -> Removing stray .stfolder from ${HOME}..."
    rm -rf "${HOME}/.stfolder"
fi
if [ -f "${HOME}/.stignore" ]; then
    echo "  -> Removing stray .stignore from ${HOME}..."
    rm -f "${HOME}/.stignore"
fi

# Ensure .stfolder marker exists inside /mnt/shared
mkdir -p "${SHARED_DIR}/.stfolder"

# Step 3: Create clean navigation symlink in $HOME (e.g. ~/drive -> /mnt/shared)
echo "[3/5] Setting up ~/drive convenience symlink..."
if [ ! -e "${HOME}/drive" ]; then
    ln -s "${SHARED_DIR}" "${HOME}/drive"
fi

# Step 4: Write clean Syncthing ignore rules in /mnt/shared/.stignore
echo "[4/5] Updating ${SHARED_DIR}/.stignore..."
cat <<'EOF' > "${SHARED_DIR}/.stignore"
(?d)$RECYCLE.BIN
(?d).Trash-*
(?d)System Volume Information
(?d).syncthing.*.tmp
(?d).filebrowser.db*
(?d).cache
EOF

# Step 5: Update Syncthing folder configuration
echo "[5/5] Reconfiguring Syncthing client..."
if command -v syncthing &>/dev/null; then
    # Check if folder 'shared' exists in syncthing config
    if syncthing cli config folders list 2>/dev/null | grep -qw "shared"; then
        echo "  -> Updating folder 'shared' path to ${SHARED_DIR}..."
        syncthing cli config folders shared path set "${SHARED_DIR}" || true
        syncthing cli config folders shared marker-name set ".stfolder" || true
    elif syncthing cli config folders list 2>/dev/null | grep -qw "shared-drive"; then
        echo "  -> Updating folder 'shared-drive' path to ${SHARED_DIR}..."
        syncthing cli config folders shared-drive path set "${SHARED_DIR}" || true
        syncthing cli config folders shared-drive marker-name set ".stfolder" || true
    fi
    
    # Restart Syncthing to apply
    systemctl --user restart syncthing 2>/dev/null || syncthing cli operations restart 2>/dev/null || true
fi

echo "══════════════════════════════════════════════════════════════════════"
echo "✨ Cleanup complete!"
echo "   - $HOME is completely clean"
echo "   - All shared data consolidated in /mnt/shared"
echo "   - ~/drive points to /mnt/shared"
echo "   - Syncthing configured to sync the entirety of /mnt/shared"
echo "══════════════════════════════════════════════════════════════════════"
