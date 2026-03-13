# Homelab Runbook

## Topology

- `coupon-bot` and `coupon-ui` run from `compose.yml`.
- UI is exposed internally on port `8080` and should be routed via SWAG.
- Data and runtime volumes:
  - `/data` for SQLite and incoming images
  - `/app/runtime` for bot health file

## SWAG reverse proxy note

Use SWAG to route a subdomain or path to `coupon-ui:8080` on the same Docker network.

Expected forwarded headers:
- `Host`
- `X-Forwarded-For`
- `X-Forwarded-Proto`

Keep UI basic auth enabled at app level (`UI_USERNAME`, `UI_PASSWORD`) even behind SWAG.

## Operational checks

- Container health:
  - `docker compose ps`
- Bot logs:
  - `docker compose logs -f coupon-bot`
- UI logs:
  - `docker compose logs -f coupon-ui`

## Failure modes

- `coupon-bot` unhealthy:
  - check `/app/runtime/bot_health.txt` exists and updates
  - inspect OpenAI errors/timeouts in logs
  - verify DB path and permissions in mounted volume
- UI returns 401 unexpectedly:
  - verify SWAG forwards `Authorization` header
  - verify `.env` credentials
- Reminder anomalies:
  - check `scan_every_minutes` and `reminder_days` in config
  - verify server clock and timezone behavior
