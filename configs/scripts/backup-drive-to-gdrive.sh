#!/bin/bash
# Backup /home/pineapple/drive to Google Drive remote (excluding cache and logs)
REMOTE_NAME="gdrive"
DEST_FOLDER="Server_Drive_Backup"

if ! rclone listremotes 2>/dev/null | grep -q "^${REMOTE_NAME}:"; then
    echo "[INFO] Rclone remote '${REMOTE_NAME}' not configured yet. Skipping cloud sync until 'rclone config' is set up."
    exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting rclone sync to ${REMOTE_NAME}:${DEST_FOLDER}..."
rclone sync /home/pineapple/drive "${REMOTE_NAME}:${DEST_FOLDER}" \
    --exclude ".cache/**" \
    --exclude ".filebrowser.db-journal" \
    --exclude "Media/**" \
    --fast-list \
    --transfers 4 \
    --checkers 8 \
    --log-file /home/pineapple/drive/.rclone-backup.log \
    --log-level INFO

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sync completed successfully."
