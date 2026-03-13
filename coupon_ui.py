#!/usr/bin/env python3
"""Simple web UI for viewing and managing coupons from coupon_bot.py."""

import argparse
import base64
import html
import secrets
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def parse_basic_auth(header_value: str):
    if not header_value or not header_value.startswith("Basic "):
        return None, None
    try:
        raw = base64.b64decode(header_value[6:]).decode("utf-8")
    except Exception:
        return None, None
    if ":" not in raw:
        return None, None
    username, password = raw.split(":", 1)
    return username, password


def require_auth(handler: BaseHTTPRequestHandler, username: str, password: str) -> bool:
    got_user, got_pass = parse_basic_auth(handler.headers.get("Authorization", ""))
    if got_user == username and got_pass == password:
        return True

    handler.send_response(401)
    handler.send_header("WWW-Authenticate", 'Basic realm="Coupon Dashboard"')
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    payload = b"Unauthorized"
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)
    return False


def fetch_coupons(db_path: str, status: str = "all", vendor: str = "", user_id: str = ""):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        query = (
            """
            SELECT id, user_id, user_name, vendor, value_ils, code, cvv, barcode, expiry_utc, created_utc
            FROM coupons
            WHERE 1=1
            """
        )
        params = []

        if vendor:
            query += " AND lower(coalesce(vendor, '')) LIKE ?"
            params.append(f"%{vendor.lower()}%")

        if user_id:
            query += " AND cast(user_id as text) = ?"
            params.append(user_id)

        if status == "expired":
            query += " AND date(expiry_utc) < date('now')"
        elif status == "expiring":
            query += " AND date(expiry_utc) >= date('now') AND date(expiry_utc) <= date('now', '+7 days')"
        elif status == "active":
            query += " AND date(expiry_utc) > date('now', '+7 days')"

        query += " ORDER BY datetime(expiry_utc) ASC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def delete_coupon(db_path: str, coupon_id: int) -> bool:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("DELETE FROM coupons WHERE id = ?", (coupon_id,))
        return cur.rowcount > 0


def fetch_coupon_by_id(db_path: str, coupon_id: int):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, user_id, user_name, vendor, value_ils, code, cvv, barcode, expiry_utc, created_utc, raw
            FROM coupons
            WHERE id = ?
            """,
            (coupon_id,),
        ).fetchone()
        return dict(row) if row else None


def coupon_status(expiry_utc: str):
    today = datetime.now(timezone.utc).date()
    exp_date = datetime.fromisoformat(expiry_utc).date()
    delta = (exp_date - today).days
    if delta < 0:
        return "Expired", "expired"
    if delta <= 7:
        return f"{delta} day(s) left", "soon"
    return f"{delta} day(s) left", ""


def render_dashboard(db_path: str, status: str, vendor: str, user_id: str, message: str = "") -> str:
    coupons = fetch_coupons(db_path, status=status, vendor=vendor, user_id=user_id)
    expiring_soon = 0
    expired = 0

    body_rows = []
    for c in coupons:
        status_text, status_class = coupon_status(c["expiry_utc"])
        if status_class == "expired":
            expired += 1
        elif status_class == "soon":
            expiring_soon += 1

        value = f"{c['value_ils']}₪" if c["value_ils"] is not None else "—"
        safe_vendor = html.escape(c["vendor"] or "—")
        safe_user = html.escape(c["user_name"] or str(c["user_id"]))
        safe_code = html.escape(c["code"] or "—")
        expiry_date = html.escape(c["expiry_utc"][:10])

        body_rows.append(
            "<tr>"
            f"<td><a href='/coupon/{c['id']}'>#{c['id']}</a></td>"
            f"<td>{safe_user}</td>"
            f"<td>{safe_vendor}</td>"
            f"<td>{value}</td>"
            f"<td><code>{safe_code}</code></td>"
            f"<td>{expiry_date}</td>"
            f"<td class='{status_class}'>{html.escape(status_text)}</td>"
            f"<td><form method='post' action='/actions/delete/{c['id']}' onsubmit='return confirm(&quot;Delete coupon #{c['id']}?&quot;)'><button type='submit'>Delete</button></form></td>"
            "</tr>"
        )

    rows_html = "\n".join(body_rows) if body_rows else "<tr><td colspan='8'>No coupons found.</td></tr>"

    notice = f"<div class='notice'>{html.escape(message)}</div>" if message else ""
    status_opts = ["all", "expiring", "active", "expired"]
    status_options = "".join(
        f"<option value='{s}' {'selected' if s == status else ''}>{s.title()}</option>" for s in status_opts
    )

    return f"""<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Coupon Bot Dashboard</title>
<style>
body {{ font-family: system-ui,sans-serif; margin: 2rem; color: #222; }}
.meta {{ color: #666; margin-bottom: 1.2rem; }}
.notice {{ background: #edf7ed; color: #1e4620; padding: 0.6rem; border-radius: 8px; margin-bottom: 1rem; }}
.filters {{ display: flex; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 1rem; }}
input, select, button {{ padding: 0.4rem 0.55rem; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ text-align: left; padding: 0.55rem; border-bottom: 1px solid #e5e5e5; vertical-align: top; }}
th {{ background: #fafafa; }}
.expired {{ color: #b00020; font-weight: 600; }}
.soon {{ color: #8a4b00; font-weight: 600; }}
code {{ background: #f4f4f4; padding: 0.1rem 0.3rem; border-radius: 4px; }}
@media (max-width: 900px) {{ body {{ margin: 1rem; }} table {{ font-size: 0.92rem; }} }}
</style></head>
<body>
<h1>Coupon Bot Dashboard</h1>
{notice}
<div class='meta'>
Visible coupons: <strong>{len(coupons)}</strong> ·
Expiring in 7 days: <strong>{expiring_soon}</strong> ·
Already expired: <strong>{expired}</strong>
</div>
<form class='filters' method='get' action='/'>
<label>Status <select name='status'>{status_options}</select></label>
<label>Vendor <input type='text' name='vendor' value='{html.escape(vendor)}' placeholder='e.g. Rami Levy'></label>
<label>User ID <input type='text' name='user_id' value='{html.escape(user_id)}' placeholder='telegram user id'></label>
<button type='submit'>Apply</button>
<a href='/'><button type='button'>Reset</button></a>
</form>
<table>
<thead><tr><th>ID</th><th>User</th><th>Vendor</th><th>Value</th><th>Code</th><th>Expiry</th><th>Status</th><th>Actions</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
</body></html>"""


def render_coupon_detail(coupon: dict) -> str:
    status_text, status_class = coupon_status(coupon["expiry_utc"])
    value = f"{coupon['value_ils']}₪" if coupon["value_ils"] is not None else "—"
    raw = html.escape(coupon.get("raw") or "")
    return f"""<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Coupon #{coupon['id']}</title>
<style>
body {{ font-family: system-ui,sans-serif; margin: 2rem; color: #222; max-width: 860px; }}
.card {{ border: 1px solid #e5e5e5; border-radius: 12px; padding: 1rem; }}
label {{ color: #666; font-size: 0.9rem; display: block; margin-top: 0.6rem; }}
code, pre {{ background: #f4f4f4; padding: 0.25rem 0.4rem; border-radius: 4px; }}
.expired {{ color: #b00020; font-weight: 600; }}
.soon {{ color: #8a4b00; font-weight: 600; }}
</style></head>
<body>
<p><a href='/'>← Back to dashboard</a></p>
<h1>Coupon #{coupon['id']}</h1>
<div class='card'>
<label>User</label><div>{html.escape(coupon.get('user_name') or str(coupon.get('user_id')))}</div>
<label>Vendor</label><div>{html.escape(coupon.get('vendor') or '—')}</div>
<label>Value</label><div>{value}</div>
<label>Code</label><div><code>{html.escape(coupon.get('code') or '—')}</code></div>
<label>CVV</label><div><code>{html.escape(coupon.get('cvv') or '—')}</code></div>
<label>Barcode</label><div><code>{html.escape(coupon.get('barcode') or '—')}</code></div>
<label>Expiry</label><div>{html.escape(coupon['expiry_utc'][:10])} <span class='{status_class}'>{html.escape(status_text)}</span></div>
<label>Created</label><div>{html.escape(coupon['created_utc'])}</div>
<label>Raw Source</label><pre>{raw or '—'}</pre>
</div>
</body></html>"""


def build_handler(db_path: str, username: str, password: str):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)

            if parsed.path == "/health":
                payload = b"ok"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            if not require_auth(self, username, password):
                return

            if parsed.path == "/":
                q = parse_qs(parsed.query)
                status = (q.get("status", ["all"])[0] or "all").strip().lower()
                if status not in {"all", "expiring", "active", "expired"}:
                    status = "all"
                vendor = (q.get("vendor", [""])[0] or "").strip()
                user_id = (q.get("user_id", [""])[0] or "").strip()
                message = (q.get("message", [""])[0] or "").strip()
                payload = render_dashboard(db_path, status=status, vendor=vendor, user_id=user_id, message=message).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            if parsed.path.startswith("/coupon/"):
                try:
                    coupon_id = int(parsed.path.split("/coupon/", 1)[1])
                except ValueError:
                    self.send_error(400, "Bad coupon id")
                    return

                coupon = fetch_coupon_by_id(db_path, coupon_id)
                if not coupon:
                    self.send_error(404, "Coupon not found")
                    return

                payload = render_coupon_detail(coupon).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            self.send_error(404)

        def do_POST(self):
            if not require_auth(self, username, password):
                return

            if self.path.startswith("/actions/delete/"):
                try:
                    coupon_id = int(self.path.split("/actions/delete/", 1)[1])
                except ValueError:
                    self.send_error(400, "Bad coupon id")
                    return

                deleted = delete_coupon(db_path, coupon_id)
                msg = "Coupon deleted" if deleted else "Coupon not found"
                location = f"/?message={msg.replace(' ', '+')}"
                self.send_response(303)
                self.send_header("Location", location)
                self.end_headers()
                return

            self.send_error(404)

        def log_message(self, fmt: str, *args):
            return

    return DashboardHandler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="coupons.db")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="")
    args = parser.parse_args()

    if not Path(args.db_path).exists():
        raise SystemExit(f"DB file not found: {args.db_path}")

    if not args.password:
        raise SystemExit("UI password must be provided via --password")

    server = ThreadingHTTPServer((args.host, args.port), build_handler(args.db_path, args.username, args.password))
    print(f"Dashboard on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
