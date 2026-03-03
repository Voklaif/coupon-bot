#!/usr/bin/env python3
"""Simple web UI for viewing coupons stored by coupon_bot.py (no extra dependencies)."""

import argparse
import html
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def fetch_coupons(db_path: str):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, user_id, user_name, vendor, value_ils, code, expiry_utc
            FROM coupons
            ORDER BY datetime(expiry_utc) ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def render_dashboard(db_path: str) -> str:
    today = datetime.now(timezone.utc).date()
    coupons = fetch_coupons(db_path)

    expiring_soon = 0
    expired = 0
    body_rows = []

    for c in coupons:
        exp_date = datetime.fromisoformat(c["expiry_utc"]).date()
        delta = (exp_date - today).days

        if delta < 0:
            status = "Expired"
            status_class = "expired"
            expired += 1
        elif delta <= 7:
            status = f"{delta} day(s) left"
            status_class = "soon"
            expiring_soon += 1
        else:
            status = f"{delta} day(s) left"
            status_class = ""

        value = f"{c['value_ils']}₪" if c["value_ils"] is not None else "—"
        body_rows.append(
            "<tr>"
            f"<td>#{c['id']}</td>"
            f"<td>{html.escape(c['user_name'] or str(c['user_id']))}</td>"
            f"<td>{html.escape(c['vendor'] or '—')}</td>"
            f"<td>{value}</td>"
            f"<td><code>{html.escape(c['code'] or '—')}</code></td>"
            f"<td>{html.escape(c['expiry_utc'][:10])}</td>"
            f"<td class='{status_class}'>{html.escape(status)}</td>"
            "</tr>"
        )

    rows_html = "\n".join(body_rows) if body_rows else "<tr><td colspan='7'>No coupons yet.</td></tr>"

    return f"""<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Coupon Bot Dashboard</title>
<style>
body {{ font-family: system-ui,sans-serif; margin: 2rem; color: #222; }}
.meta {{ color: #666; margin-bottom: 1.2rem; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ text-align: left; padding: 0.55rem; border-bottom: 1px solid #e5e5e5; }}
th {{ background: #fafafa; }}
.expired {{ color: #b00020; font-weight: 600; }}
.soon {{ color: #8a4b00; font-weight: 600; }}
code {{ background: #f4f4f4; padding: 0.1rem 0.3rem; border-radius: 4px; }}
</style></head>
<body>
<h1>Coupon Bot Dashboard</h1>
<div class='meta'>
Total coupons: <strong>{len(coupons)}</strong> ·
Expiring in 7 days: <strong>{expiring_soon}</strong> ·
Already expired: <strong>{expired}</strong>
</div>
<table>
<thead><tr><th>ID</th><th>User</th><th>Vendor</th><th>Value</th><th>Code</th><th>Expiry</th><th>Status</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
</body></html>"""


def build_handler(db_path: str):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/":
                self.send_error(404)
                return
            payload = render_dashboard(db_path).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt: str, *args):
            return

    return DashboardHandler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="coupons.db")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    if not Path(args.db_path).exists():
        raise SystemExit(f"DB file not found: {args.db_path}")

    server = ThreadingHTTPServer((args.host, args.port), build_handler(args.db_path))
    print(f"Dashboard on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
