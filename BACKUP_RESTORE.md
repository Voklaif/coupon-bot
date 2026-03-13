# Backup and Restore

## Backup

```bash
./scripts/backup_db.sh data/coupons.db backups
```

What it does:
- creates timestamped SQLite backup in `backups/`
- runs `PRAGMA integrity_check` and fails if not `ok`

## Restore

```bash
./scripts/restore_db.sh backups/<backup-file>.db data/coupons.db
```

What it does:
- copies selected backup over target DB path
- validates DB integrity after restore

## Recommended routine

- Run backup before every production deploy.
- Keep at least last 7 backups.
- Test restore in dev monthly.
