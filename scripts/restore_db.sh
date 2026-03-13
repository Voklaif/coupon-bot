#!/usr/bin/env bash
set -euo pipefail

BACKUP_PATH="${1:-}"
TARGET_DB="${2:-data/coupons.db}"

if [[ -z "$BACKUP_PATH" ]]; then
  echo "Usage: $0 <backup_path> [target_db]" >&2
  exit 1
fi

if [[ ! -f "$BACKUP_PATH" ]]; then
  echo "Backup file not found: $BACKUP_PATH" >&2
  exit 1
fi

mkdir -p "$(dirname "$TARGET_DB")"
cp "$BACKUP_PATH" "$TARGET_DB"
sqlite3 "$TARGET_DB" "PRAGMA integrity_check;" | grep -q "ok"

echo "Restore completed: $TARGET_DB"
