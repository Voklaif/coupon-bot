# Coupon Bot

Telegram coupon saver bot with:
- OpenAI extraction from text + images.
- SQLite storage and reminder notifications.
- Web dashboard with filters, detail view, and delete action.
- One simple Docker Compose setup for both PC and homelab.

## Project layout

- `coupon_bot.py` — Telegram bot service.
- `coupon_ui.py` — dashboard service.
- `compose.yml` — Docker services for bot + UI.
- `Dockerfile` — shared runtime image (non-root).
- `scripts/` — healthchecks, backup/restore, tagged deploy helper.
- `tests/` — pytest suite.
- `ROADMAP.md`, `TASKS.md`, `AI_LEARNING_LOG.md`, `PLAYBOOK_AI_WORKFLOW.md`.

## Local run

1. Install deps:
   ```bash
   pip install -r requirements-dev.txt
   ```
2. Create env + config:
   ```bash
   cp .env.example .env
   mkdir -p config
   cp config.example.json config/config.json
   ```
3. Fill secrets in `config/config.json` and `.env`.
4. Start stack:
   ```bash
   make up
   ```
5. Open dashboard at `http://localhost:8080` using `UI_USERNAME` and `UI_PASSWORD` from `.env`.

## Homelab deploy

1. On server, clone repo and enter it.
2. Create runtime folders:
   ```bash
   mkdir -p data/incoming runtime config backups
   ```
3. Create env and config:
   ```bash
   cp .env.example .env
   cp config.example.json config/config.json
   ```
4. Edit `.env`:
   - set strong `UI_PASSWORD`
   - set `PUID`/`PGID` to your server user (`id -u`, `id -g`)
5. Edit `config/config.json` with real:
   - `telegram_bot_token`
   - `openai_api_key`
6. Start:
   ```bash
   make up
   ```
7. Verify:
   ```bash
   make ps
   curl -f http://127.0.0.1:8080/health
   ```
8. Point SWAG at `coupon-ui:8080` or at the host port you published.

## Deploy flow

- Push your changes.
- On the server: `git pull`
- Back up the DB: `./scripts/backup_db.sh data/coupons.db backups`
- Restart: `make up`
- For tagged releases: `./scripts/deploy_tag.sh v0.1.0`

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
