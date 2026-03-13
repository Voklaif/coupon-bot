#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${1:-data/coupons.db}"
BACKUP_DIR="${2:-backups}"

if [[ ! -f "$DB_PATH" ]]; then
  echo "DB file not found: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_PATH="$BACKUP_DIR/coupons-$STAMP.db"

sqlite3 "$DB_PATH" ".backup '$BACKUP_PATH'"
sqlite3 "$BACKUP_PATH" "PRAGMA integrity_check;" | grep -q "ok"

echo "Backup created: $BACKUP_PATH"
