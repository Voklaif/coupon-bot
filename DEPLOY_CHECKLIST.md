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
   - `.env.prod` exists and has strong `UI_PASSWORD`
   - `config/config.json` exists with valid tokens
6. Preview final Compose config:
   - `make prod-plan`
7. Take DB backup before deploy:
   - `./scripts/backup_db.sh data/coupons.db backups`
8. Deploy:
   - `make prod-up`
9. Validate:
   - `docker compose --env-file .env.prod -f compose.yml -f compose.prod.yml ps`
   - UI health from server: `curl -f http://127.0.0.1:8080/health` (or through SWAG route)
   - Telegram `/status` command returns expected settings
10. If rollback is needed:
   - checkout previous git tag/commit
   - `make prod-up`
   - if DB corruption suspected: restore from latest backup then restart
