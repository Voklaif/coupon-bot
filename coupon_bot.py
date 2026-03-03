#!/usr/bin/env python3
"""
Coupon Manager Telegram Bot (self-hosted) + OpenAI extraction + SQLite + reminders.

- Reads settings/secrets from config.json
- Handles text + images (screenshots) using OpenAI vision
- Stores coupons per Telegram user in SQLite
- /list, /del <id>, /help
- Sends reminders N days before expiry (configurable)
- Designed to run as a long-running service (systemd)

Install:
  pip install "python-telegram-bot>=21,<22" requests pillow

Run:
  python3 coupon_bot.py --config /etc/couponbot/config.json
"""

import argparse
import base64
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from PIL import Image
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


# ----------------------------- Config ----------------------------------------

def load_config(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"Config file not found: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"Failed parsing config JSON: {e}")

    # Basic validation
    for k in ["telegram_bot_token", "openai_api_key"]:
        if not (data.get(k) and str(data.get(k)).strip()):
            raise SystemExit(f"Config missing required key: {k}")

    return data


# ----------------------------- Logging ---------------------------------------

log = logging.getLogger("coupon-bot")


# ----------------------------- DB --------------------------------------------

def db_connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def db_init(db_path: str) -> None:
    with db_connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS coupons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_name TEXT,
                vendor TEXT,
                value_ils INTEGER,
                code TEXT,
                cvv TEXT,
                barcode TEXT,
                expiry_utc TEXT NOT NULL,     -- ISO timestamp at UTC midnight
                raw TEXT,                     -- original message/caption
                created_utc TEXT NOT NULL,
                notified_expired INTEGER NOT NULL DEFAULT 0
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders_sent (
                coupon_id INTEGER NOT NULL,
                days_before INTEGER NOT NULL,
                sent_utc TEXT NOT NULL,
                PRIMARY KEY (coupon_id, days_before),
                FOREIGN KEY (coupon_id) REFERENCES coupons(id) ON DELETE CASCADE
            );
        """)


def db_add_coupon(db_path: str, user_id: int, user_name: str, fields: Dict[str, Any]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with db_connect(db_path) as conn:
        cur = conn.execute("""
            INSERT INTO coupons (
                user_id, user_name, vendor, value_ils, code, cvv, barcode, expiry_utc, raw, created_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            user_name,
            fields.get("vendor"),
            fields.get("value_ils"),
            fields.get("code"),
            fields.get("cvv"),
            fields.get("barcode"),
            fields["expiry_utc"],
            fields.get("raw"),
            now
        ))
        return int(cur.lastrowid)


def db_list_coupons(db_path: str, user_id: int) -> List[sqlite3.Row]:
    with db_connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("""
            SELECT id, vendor, value_ils, code, cvv, barcode, expiry_utc, created_utc
            FROM coupons
            WHERE user_id = ?
            ORDER BY datetime(expiry_utc) ASC
        """, (user_id,))
        return list(cur.fetchall())


def db_delete_coupon(db_path: str, user_id: int, coupon_id: int) -> bool:
    with db_connect(db_path) as conn:
        cur = conn.execute("DELETE FROM coupons WHERE user_id = ? AND id = ?", (user_id, coupon_id))
        return cur.rowcount > 0


def db_mark_reminder_sent(db_path: str, coupon_id: int, days_before: int) -> None:
    with db_connect(db_path) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO reminders_sent (coupon_id, days_before, sent_utc)
            VALUES (?, ?, ?)
        """, (coupon_id, days_before, datetime.now(timezone.utc).isoformat()))


def db_mark_expired_notified(db_path: str, coupon_id: int) -> None:
    with db_connect(db_path) as conn:
        conn.execute("UPDATE coupons SET notified_expired = 1 WHERE id = ?", (coupon_id,))


# ----------------------------- Helpers ---------------------------------------

def fmt_row(r: sqlite3.Row) -> str:
    exp = datetime.fromisoformat(r["expiry_utc"]).date().isoformat()
    vendor = r["vendor"] or "—"
    value = f"{r['value_ils']}₪" if r["value_ils"] is not None else "—"
    code = r["code"] or "—"
    extras = []
    if r["cvv"]:
        extras.append(f"cvv:{r['cvv']}")
    if r["barcode"]:
        extras.append(f"barcode:{r['barcode']}")
    extra_s = (" • " + " ".join(extras)) if extras else ""
    return f"#{r['id']}  *{vendor}*  •  {value}  •  `{code}`  •  expires: *{exp}*{extra_s}"


def last_day_of_month(year: int, month: int) -> int:
    if month == 12:
        nxt = datetime(year + 1, 1, 1)
    else:
        nxt = datetime(year, month + 1, 1)
    return (nxt - timedelta(days=1)).day


def normalize_expiry_to_utc_midnight(expiry_str: str) -> Optional[str]:
    """
    Accepted formats from the model:
      - YYYY-MM-DD
      - DD/MM/YYYY or DD-MM-YYYY
      - MM/YY (interpreted as last day of month)
    Returns ISO timestamp at UTC midnight.
    """
    s = (expiry_str or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).isoformat()

    m = re.fullmatch(r"(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return datetime(y, mo, d, tzinfo=timezone.utc).isoformat()
        except ValueError:
            return None

    m2 = re.fullmatch(r"(\d{1,2})\/(\d{2})", s)
    if m2:
        mo, yy = int(m2.group(1)), int(m2.group(2))
        y = 2000 + yy
        try:
            d = last_day_of_month(y, mo)
            return datetime(y, mo, d, tzinfo=timezone.utc).isoformat()
        except ValueError:
            return None

    return None


def image_to_b64_jpeg(path: str, max_side: int = 1400) -> str:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)))
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ----------------------------- OpenAI ---------------------------------------

SYSTEM_EXTRACT = """You extract structured data from Israeli coupon messages (Hebrew/English) and screenshots.

Return ONLY valid JSON with this schema:
{
  "vendor": string|null,
  "value_ils": integer|null,
  "code": string|null,
  "cvv": string|null,
  "barcode": string|null,
  "expiry": string  // required; formats allowed: YYYY-MM-DD or DD/MM/YYYY or DD-MM-YYYY or MM/YY
}

Rules:
- expiry is required.
- If multiple possible "codes" exist, prefer the main redemption code (often after 'הינו:' or 'קוד הקופון' or near barcode).
- If CVV appears (e.g., 'קוד אימות' or 'CVV'), capture it.
- value_ils: the amount in ₪ if present.
- vendor: best-effort store name (e.g., after 'ברשת').
- barcode: numeric string under a barcode if present.
"""

def openai_chat(api_key: str, model: str, messages: List[Dict[str, Any]], timeout_s: int = 60) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def extract_coupon_from_text(api_key: str, model: str, text: str) -> Dict[str, Any]:
    content = openai_chat(
        api_key=api_key,
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_EXTRACT},
            {"role": "user", "content": text},
        ],
    )
    data = json.loads(content)
    expiry_utc = normalize_expiry_to_utc_midnight(data.get("expiry", ""))
    if not expiry_utc:
        raise ValueError(f"Bad expiry returned: {data.get('expiry')}")
    return {
        "vendor": data.get("vendor"),
        "value_ils": data.get("value_ils"),
        "code": data.get("code"),
        "cvv": data.get("cvv"),
        "barcode": data.get("barcode"),
        "expiry_utc": expiry_utc,
        "raw": text,
    }


def extract_coupon_from_image(api_key: str, model: str, image_path: str, caption: str = "") -> Dict[str, Any]:
    b64 = image_to_b64_jpeg(image_path)

    user_parts: List[Dict[str, Any]] = []
    if caption.strip():
        user_parts.append({"type": "text", "text": f"Caption/context:\n{caption.strip()}\n"})
    user_parts.append({"type": "text", "text": "Extract coupon data from this screenshot/image."})
    user_parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    content = openai_chat(
        api_key=api_key,
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_EXTRACT},
            {"role": "user", "content": user_parts},
        ],
        timeout_s=90,
    )

    data = json.loads(content)
    expiry_utc = normalize_expiry_to_utc_midnight(data.get("expiry", ""))
    if not expiry_utc:
        raise ValueError(f"Bad expiry returned: {data.get('expiry')}")

    return {
        "vendor": data.get("vendor"),
        "value_ils": data.get("value_ils"),
        "code": data.get("code"),
        "cvv": data.get("cvv"),
        "barcode": data.get("barcode"),
        "expiry_utc": expiry_utc,
        "raw": f"[image] {caption}".strip(),
    }


# ----------------------------- Telegram bot ---------------------------------

HELP_TEXT = """\
Send me a coupon as text or image (screenshot).

Commands:
- /list
- /del <id>
- /help
"""

class CouponBot:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.db_path = str(cfg.get("db_path") or "coupons.db")
        self.bot_token = str(cfg["telegram_bot_token"]).strip()
        self.api_key = str(cfg["openai_api_key"]).strip()

        self.text_model = str(cfg.get("openai_text_model") or "gpt-4.1-mini")
        self.vision_model = str(cfg.get("openai_vision_model") or "gpt-4.1-mini")

        self.reminder_days = list(cfg.get("reminder_days") or [30, 7, 1])
        self.scan_every_minutes = int(cfg.get("scan_every_minutes") or 30)

        self.incoming_dir = str(cfg.get("incoming_dir") or "incoming")
        Path(self.incoming_dir).mkdir(parents=True, exist_ok=True)

        db_init(self.db_path)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(HELP_TEXT)

    async def cmd_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        rows = db_list_coupons(self.db_path, update.effective_user.id)
        if not rows:
            await update.message.reply_text("No coupons saved yet.")
            return
        lines = ["Your coupons:"]
        lines += [fmt_row(r) for r in rows]
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    async def cmd_del(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Usage: /del <id>")
            return
        try:
            cid = int(context.args[0])
        except ValueError:
            await update.message.reply_text("ID must be a number. Example: /del 3")
            return

        ok = db_delete_coupon(self.db_path, update.effective_user.id, cid)
        await update.message.reply_text("Deleted." if ok else "Not found (or not yours).")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = (update.message.text or "").strip()
        if not text:
            return

        try:
            fields = extract_coupon_from_text(self.api_key, self.text_model, text)
        except Exception as e:
            log.warning("extract text failed: %s", e)
            await update.message.reply_text("I couldn't extract the coupon reliably. Try pasting the full message.")
            return

        cid = db_add_coupon(self.db_path, update.effective_user.id, update.effective_user.full_name or "", fields)
        exp = datetime.fromisoformat(fields["expiry_utc"]).date().isoformat()
        await update.message.reply_text(
            f"Saved coupon #{cid}\n"
            f"- vendor: {fields.get('vendor') or '—'}\n"
            + (f"- value: {fields.get('value_ils')}₪\n" if fields.get("value_ils") is not None else "")
            + f"- code: {fields.get('code') or '—'}\n"
            + (f"- cvv: {fields.get('cvv')}\n" if fields.get("cvv") else "")
            + (f"- barcode: {fields.get('barcode')}\n" if fields.get("barcode") else "")
            + f"- expiry: {exp}\n"
        )

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        photo = update.message.photo[-1]  # best resolution
        f = await context.bot.get_file(photo.file_id)
        path = os.path.join(self.incoming_dir, f"{photo.file_id}.jpg")
        await f.download_to_drive(path)

        caption = (update.message.caption or "").strip()

        try:
            fields = extract_coupon_from_image(self.api_key, self.vision_model, path, caption=caption)
        except Exception as e:
            log.warning("extract image failed: %s", e)
            await update.message.reply_text("I couldn't extract from the image. Try a clearer screenshot.")
            return

        cid = db_add_coupon(self.db_path, update.effective_user.id, update.effective_user.full_name or "", fields)
        exp = datetime.fromisoformat(fields["expiry_utc"]).date().isoformat()
        await update.message.reply_text(
            f"Saved coupon #{cid} (from image)\n"
            f"- vendor: {fields.get('vendor') or '—'}\n"
            + (f"- value: {fields.get('value_ils')}₪\n" if fields.get("value_ils") is not None else "")
            + f"- code: {fields.get('code') or '—'}\n"
            + (f"- cvv: {fields.get('cvv')}\n" if fields.get("cvv") else "")
            + (f"- barcode: {fields.get('barcode')}\n" if fields.get("barcode") else "")
            + f"- expiry: {exp}\n"
        )

    async def reminder_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        now = datetime.now(timezone.utc)

        with db_connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Pre-expiry reminders (N days before)
            for days in self.reminder_days:
                band_start = (now + timedelta(days=days)).date()
                band_end = (now + timedelta(days=days + 1)).date()

                cur = conn.execute("""
                    SELECT c.*
                    FROM coupons c
                    LEFT JOIN reminders_sent r
                      ON r.coupon_id = c.id AND r.days_before = ?
                    WHERE r.coupon_id IS NULL
                      AND date(c.expiry_utc) >= date(?)
                      AND date(c.expiry_utc) <  date(?)
                """, (days, band_start.isoformat(), band_end.isoformat()))

                for r in cur.fetchall():
                    exp = datetime.fromisoformat(r["expiry_utc"]).date().isoformat()
                    vendor = r["vendor"] or "—"
                    code = r["code"] or "—"
                    msg = f"⏰ Coupon reminder: {days} day(s) left\n{vendor} • `{code}` • expires {exp}"
                    try:
                        await context.bot.send_message(chat_id=r["user_id"], text=msg, parse_mode=ParseMode.MARKDOWN)
                        db_mark_reminder_sent(self.db_path, r["id"], days)
                    except Exception as e:
                        log.warning("send reminder failed: %s", e)

            # Expired notice (once)
            cur2 = conn.execute("""
                SELECT *
                FROM coupons
                WHERE notified_expired = 0
                  AND date(expiry_utc) < date(?)
            """, (now.date().isoformat(),))

            for r in cur2.fetchall():
                exp = datetime.fromisoformat(r["expiry_utc"]).date().isoformat()
                vendor = r["vendor"] or "—"
                code = r["code"] or "—"
                msg = f"⚠️ Coupon expired\n{vendor} • `{code}` • expired {exp}"
                try:
                    await context.bot.send_message(chat_id=r["user_id"], text=msg, parse_mode=ParseMode.MARKDOWN)
                    db_mark_expired_notified(self.db_path, r["id"])
                except Exception as e:
                    log.warning("send expired notice failed: %s", e)

    def run(self) -> None:
        app = Application.builder().token(self.bot_token).build()

        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("list", self.cmd_list))
        app.add_handler(CommandHandler("del", self.cmd_del))

        app.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

        # schedule reminder scan
        app.job_queue.run_repeating(self.reminder_job, interval=self.scan_every_minutes * 60, first=10)

        log.info("Bot started. DB=%s text_model=%s vision_model=%s", self.db_path, self.text_model, self.vision_model)
        app.run_polling(close_loop=False)


# ----------------------------- main ------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR")
    args = parser.parse_args()

    logging.getLogger().setLevel(args.log_level.upper())

    cfg = load_config(args.config)
    bot = CouponBot(cfg)
    bot.run()


if __name__ == "__main__":
    main()
