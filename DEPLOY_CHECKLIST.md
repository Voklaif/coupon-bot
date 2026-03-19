# Deploy Checklist (Manual)

1. On your PC, verify before pushing:
   - `make lint`
   - `make test`
   - `git status` is clean
2. Push to your repo.
3. SSH into homelab server and open project directory.
4. Pull updates:
   - `git fetch --all --prune`
   - `git pull`
5. Verify env/config:
   - `.env` exists and has strong `UI_PASSWORD`
   - `config/config.json` exists with valid tokens
6. Preview final Compose config:
   - `make config`
7. Take DB backup before deploy:
   - `./scripts/backup_db.sh data/coupons.db backups`
8. Deploy:
   - `make up`
9. Validate:
   - `make ps`
   - UI health from server: `curl -f http://127.0.0.1:8080/health` (or through SWAG route)
   - Telegram `/status` command returns expected settings
10. If rollback is needed:
   - checkout previous git tag/commit
   - `make up`
   - if DB corruption suspected: restore from latest backup then restart
