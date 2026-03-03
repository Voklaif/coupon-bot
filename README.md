# Coupon Bot

A Telegram coupon saver bot with:
- OpenAI extraction from text + images.
- SQLite storage and reminder notifications.
- Optional web dashboard UI for browsing saved coupons.

## Project layout

- `coupon_bot.py` — Telegram bot service.
- `coupon_ui.py` — lightweight dashboard service (read-only).
- `docker-compose.yml` — runs bot + UI with shared `./data` volume.
- `Dockerfile` — single image used by both services.

## Local run

1. Create a venv and install deps:
   ```bash
   pip install -r requirements.txt
   ```
2. Create `config.json` (or use `/data/config.json` in Docker) with:
   ```json
   {
     "telegram_bot_token": "...",
     "openai_api_key": "...",
     "db_path": "coupons.db",
     "incoming_dir": "incoming",
     "openai_text_model": "gpt-4.1-mini",
     "openai_vision_model": "gpt-4.1-mini",
     "reminder_days": [30, 7, 1],
     "scan_every_minutes": 30
   }
   ```
3. Start bot:
   ```bash
   python coupon_bot.py --config config.json
   ```
4. Start dashboard (optional):
   ```bash
   python coupon_ui.py --db-path coupons.db --port 8080
   ```

## Docker run

1. Create `data/config.json` with the same schema above but ensure DB path is `/data/coupons.db` and incoming dir is `/data/incoming`.
2. Start stack:
   ```bash
   docker compose up --build -d
   ```
3. Open dashboard at `http://localhost:8080`.

This setup makes it easier to manage by splitting bot and UI into separate services while reusing the same image and shared SQLite file.
