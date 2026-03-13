# Coupon Bot

Telegram coupon saver bot with:
- OpenAI extraction from text + images.
- SQLite storage and reminder notifications.
- Web dashboard with filters, detail view, and delete action.
- Dev/Prod Docker Compose split for PC + homelab workflows.

## What changed

- Added Compose split:
  - `compose.yml` (shared base)
  - `compose.dev.yml` (local dev)
  - `compose.prod.yml` (homelab prod)
- Added UI auth and `/health` endpoint.
- Added bot `/status`, OpenAI retry/backoff, startup validation, DB indexes, bot health file.
- Added backup/restore/deploy scripts in `scripts/`.
- Added pytest tests and GitHub Actions CI.
- Added roadmap/learning tracking docs.

## Project layout

- `coupon_bot.py` — Telegram bot service.
- `coupon_ui.py` — dashboard service.
- `compose.yml` + overrides — environment-specific orchestration.
- `Dockerfile` — shared runtime image (non-root).
- `scripts/` — healthchecks, backup/restore, tagged deploy helper.
- `tests/` — pytest suite.
- `ROADMAP.md`, `TASKS.md`, `AI_LEARNING_LOG.md`, `PLAYBOOK_AI_WORKFLOW.md`.

## Quick start (dev on PC)

1. Install deps:
   ```bash
   pip install -r requirements-dev.txt
   ```
2. Create local env + config:
   ```bash
   cp .env.dev.example .env.dev
   mkdir -p config
   cp config.example.dev.json config/config.json
   ```
3. Fill secrets in `config/config.json` and `.env.dev`.
4. Start stack:
   ```bash
   make dev-up
   ```
5. Open dashboard at `http://localhost:8080` (basic auth from `.env.dev`).

## Prod simulation on PC

```bash
cp .env.prod.example .env.prod
cp config.example.prod.json config/config.json
make prod-plan
make prod-up
```

## Homelab deploy flow

- Use git pull on server + compose up.
- Follow [DEPLOY_CHECKLIST.md](DEPLOY_CHECKLIST.md) and [HOMELAB_RUNBOOK.md](HOMELAB_RUNBOOK.md).
- For tagged rollout practice:
  ```bash
  ./scripts/deploy_tag.sh v0.1.0
  ```

## Homelab first deploy (quick path)

1. On server, clone repo and enter it.
2. Create runtime folders:
   ```bash
   mkdir -p data/incoming runtime config backups
   ```
3. Create prod env and config:
   ```bash
   cp .env.prod.example .env.prod
   cp config.example.prod.json config/config.json
   ```
4. Edit `.env.prod`:
   - set strong `UI_PASSWORD`
   - set `PUID`/`PGID` to your server user (`id -u`, `id -g`)
5. Edit `config/config.json` with real:
   - `telegram_bot_token`
   - `openai_api_key`
6. Start:
   ```bash
   make prod-up
   ```
7. Verify:
   ```bash
   docker compose --env-file .env.prod -f compose.yml -f compose.prod.yml ps
   curl -f http://127.0.0.1:8080/health
   ```

## Test and lint

```bash
make lint
make test
```

## Backup and restore

```bash
./scripts/backup_db.sh data/coupons.db backups
./scripts/restore_db.sh backups/<file>.db data/coupons.db
```

More details: [BACKUP_RESTORE.md](BACKUP_RESTORE.md)
