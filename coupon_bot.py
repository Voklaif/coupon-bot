#!/usr/bin/env python3
"""
Coupon Manager Telegram Bot (self-hosted) + OpenAI extraction + SQLite + reminders.
"""

import argparse
import base64
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


log = logging.getLogger("coupon-bot")


# ----------------------------- Config ----------------------------------------

def validate_config(data: Dict[str, Any]) -> Dict[str, Any]:
    for k in ["telegram_bot_token", "openai_api_key"]:
        if not (data.get(k) and str(data.get(k)).strip()):
            raise SystemExit(f"Config missing required key: {k}")

    if data.get("scan_every_minutes") is not None and int(data["scan_every_minutes"]) <= 0:
        raise SystemExit("scan_every_minutes must be > 0")

    if data.get("openai_timeout_seconds") is not None and int(data["openai_timeout_seconds"]) <= 0:
        raise SystemExit("openai_timeout_seconds must be > 0")

    if data.get("openai_max_retries") is not None and int(data["openai_max_retries"]) < 0:
        raise SystemExit("openai_max_retries must be >= 0")

    reminder_days = data.get("reminder_days")
    if reminder_days is not None:
        if not isinstance(reminder_days, list) or not reminder_days:
            raise SystemExit("reminder_days must be a non-empty list")
        if any(int(v) < 0 for v in reminder_days):
            raise SystemExit("reminder_days values must be >= 0")

    return data


def load_config(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"Config file not found: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"Failed parsing config JSON: {e}")

    return validate_config(data)


# ----------------------------- DB --------------------------------------------

def db_connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def db_init(db_path: str) -> None:
    with db_connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS coupons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_name TEXT,
                vendor TEXT,
                value_ils INTEGER,
                code TEXT,
                cvv TEXT,
                barcode TEXT,
                expiry_utc TEXT NOT NULL,
                raw TEXT,
                created_utc TEXT NOT NULL,
                notified_expired INTEGER NOT NULL DEFAULT 0
            );
        """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders_sent (
                coupon_id INTEGER NOT NULL,
                days_before INTEGER NOT NULL,
                sent_utc TEXT NOT NULL,
                PRIMARY KEY (coupon_id, days_before),
                FOREIGN KEY (coupon_id) REFERENCES coupons(id) ON DELETE CASCADE
            );
        """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_coupons_user_id ON coupons(user_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_coupons_expiry ON coupons(expiry_utc);")


def db_check(db_path: str) -> None:
    with db_connect(db_path) as conn:
        conn.execute("SELECT 1").fetchone()


def db_add_coupon(db_path: str, user_id: int, user_name: str, fields: Dict[str, Any]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with db_connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO coupons (
                user_id, user_name, vendor, value_ils, code, cvv, barcode, expiry_utc, raw, created_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                user_id,
                user_name,
                fields.get("vendor"),
                fields.get("value_ils"),
                fields.get("code"),
                fields.get("cvv"),
                fields.get("barcode"),
                fields["expiry_utc"],
                fields.get("raw"),
                now,
            ),
        )
        return int(cur.lastrowid)


def db_list_coupons(db_path: str, user_id: int) -> List[sqlite3.Row]:
    with db_connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT id, vendor, value_ils, code, cvv, barcode, expiry_utc, created_utc
            FROM coupons
            WHERE user_id = ?
            ORDER BY datetime(expiry_utc) ASC
        """,
            (user_id,),
        )
        return list(cur.fetchall())


def db_delete_coupon(db_path: str, user_id: int, coupon_id: int) -> bool:
    with db_connect(db_path) as conn:
        cur = conn.execute("DELETE FROM coupons WHERE user_id = ? AND id = ?", (user_id, coupon_id))
        return cur.rowcount > 0


def db_mark_reminder_sent(db_path: str, coupon_id: int, days_before: int) -> None:
    with db_connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO reminders_sent (coupon_id, days_before, sent_utc)
            VALUES (?, ?, ?)
        """,
            (coupon_id, days_before, datetime.now(timezone.utc).isoformat()),
        )


def db_mark_expired_notified(db_path: str, coupon_id: int) -> None:
    with db_connect(db_path) as conn:
        conn.execute("UPDATE coupons SET notified_expired = 1 WHERE id = ?", (coupon_id,))


# ----------------------------- Helpers ---------------------------------------

def touch_health(path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


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


def add_years_safe(base: datetime, years: int) -> datetime:
    target_year = base.year + years
    day = base.day
    month = base.month
    max_day = last_day_of_month(target_year, month)
    return datetime(target_year, month, min(day, max_day), tzinfo=timezone.utc)


def infer_expiry_from_duration_text(raw: str, now: Optional[datetime] = None) -> Optional[str]:
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None

    base = (now or datetime.now(timezone.utc)).replace(hour=0, minute=0, second=0, microsecond=0)

    # Hebrew examples: "תוקף השובר: 5 שנים", "בתוקף ל-3 שנים"
    years_match = re.search(r"(?:תוקף|בתוקף|valid)[^\n\r:]*[:\-]?\s*(\d{1,2})\s*(?:שנים|שנה|years?|yrs?)", text, re.IGNORECASE)
    if years_match:
        years = int(years_match.group(1))
        if years > 0:
            return add_years_safe(base, years).isoformat()

    months_match = re.search(r"(?:תוקף|בתוקף|valid)[^\n\r:]*[:\-]?\s*(\d{1,3})\s*(?:חודשים|חודש|months?)", text, re.IGNORECASE)
    if months_match:
        months = int(months_match.group(1))
        if months > 0:
            total_months = (base.year * 12 + (base.month - 1)) + months
            y = total_months // 12
            m = total_months % 12 + 1
            d = min(base.day, last_day_of_month(y, m))
            return datetime(y, m, d, tzinfo=timezone.utc).isoformat()

    return None


def normalize_duration_unit(unit: str) -> Optional[str]:
    u = (unit or "").strip().lower()
    if u in {"year", "years", "yr", "yrs", "שנה", "שנים"}:
        return "years"
    if u in {"month", "months", "חודש", "חודשים"}:
        return "months"
    if u in {"day", "days", "יום", "ימים"}:
        return "days"
    return None


def expiry_from_duration(value: Any, unit: str, now: Optional[datetime] = None) -> Optional[str]:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None

    base = (now or datetime.now(timezone.utc)).replace(hour=0, minute=0, second=0, microsecond=0)
    normalized = normalize_duration_unit(unit)
    if normalized == "years":
        return add_years_safe(base, n).isoformat()
    if normalized == "months":
        total_months = (base.year * 12 + (base.month - 1)) + n
        y = total_months // 12
        m = total_months % 12 + 1
        d = min(base.day, last_day_of_month(y, m))
        return datetime(y, m, d, tzinfo=timezone.utc).isoformat()
    if normalized == "days":
        return (base + timedelta(days=n)).isoformat()
    return None


def reminder_band_bounds(now: datetime, days: int) -> Tuple[datetime.date, datetime.date]:
    return (now + timedelta(days=days)).date(), (now + timedelta(days=days + 1)).date()


def parse_extraction_payload(content: str, raw: str) -> Dict[str, Any]:
    data = json.loads(content)
    expiry_utc = None

    expiry_type = str(data.get("expiry_type") or "").strip().lower()
    expiry_date = str(data.get("expiry_date") or "").strip()
    legacy_expiry = str(data.get("expiry", "")).strip()
    duration = data.get("expiry_duration") if isinstance(data.get("expiry_duration"), dict) else {}

    if expiry_date:
        expiry_utc = normalize_expiry_to_utc_midnight(expiry_date)
    if not expiry_utc and legacy_expiry:
        expiry_utc = normalize_expiry_to_utc_midnight(legacy_expiry)
    if not expiry_utc and expiry_type == "duration":
        expiry_utc = expiry_from_duration(duration.get("value"), str(duration.get("unit") or ""))
    if not expiry_utc:
        expiry_utc = infer_expiry_from_duration_text(raw)

    confidence_raw = data.get("confidence")
    try:
        confidence = float(confidence_raw) if confidence_raw is not None else 0.6
    except (TypeError, ValueError):
        confidence = 0.6

    return {
        "vendor": data.get("vendor"),
        "value_ils": data.get("value_ils"),
        "code": data.get("code"),
        "cvv": data.get("cvv"),
        "barcode": data.get("barcode"),
        "expiry_utc": expiry_utc,
        "confidence": confidence,
        "expiry_type": expiry_type or ("date" if expiry_utc else "unknown"),
        "raw": raw,
    }


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
  "expiry_type": "date"|"duration"|"unknown",
  "expiry_date": string|null,         // YYYY-MM-DD or DD/MM/YYYY or DD-MM-YYYY or MM/YY
  "expiry_duration": {"value": integer, "unit": string}|null, // unit: years|months|days
  "confidence": number                // 0..1
}

Rules:
- If expiry is a duration (for example "תוקף: 5 שנים"), set expiry_type=duration and fill expiry_duration.
- If expiry is explicit date, set expiry_type=date and fill expiry_date.
- If expiry cannot be inferred, set expiry_type=unknown and confidence<0.5.
- If multiple possible "codes" exist, prefer the main redemption code (often after 'הינו:' or 'קוד הקופון' or near barcode).
- If CVV appears (e.g., 'קוד אימות' or 'CVV'), capture it.
- value_ils: the amount in ₪ if present.
- vendor: best-effort store name (e.g., after 'ברשת').
- barcode: numeric string under a barcode if present.
"""


def openai_chat(
    api_key: str,
    model: str,
    messages: List[Dict[str, Any]],
    timeout_s: int = 60,
    max_retries: int = 2,
    backoff_seconds: float = 1.5,
) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    attempt = 0
    while True:
        attempt += 1
        started = time.monotonic()
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
            r.raise_for_status()
            elapsed_ms = int((time.monotonic() - started) * 1000)
            log.info("openai call success model=%s attempt=%s duration_ms=%s", model, attempt, elapsed_ms)
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            log.warning(
                "openai call failed model=%s attempt=%s duration_ms=%s error=%s",
                model,
                attempt,
                elapsed_ms,
                e,
            )
            if attempt > max_retries:
                raise
            time.sleep(backoff_seconds * attempt)


def extract_coupon_from_text(
    api_key: str,
    model: str,
    text: str,
    timeout_s: int,
    max_retries: int,
    backoff_seconds: float,
) -> Dict[str, Any]:
    content = openai_chat(
        api_key=api_key,
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_EXTRACT},
            {"role": "user", "content": text},
        ],
        timeout_s=timeout_s,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
    )
    return parse_extraction_payload(content, raw=text)


def extract_coupon_from_image(
    api_key: str,
    model: str,
    image_path: str,
    caption: str,
    timeout_s: int,
    max_retries: int,
    backoff_seconds: float,
) -> Dict[str, Any]:
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
        timeout_s=timeout_s,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
    )

    return parse_extraction_payload(content, raw=f"[image] {caption}".strip())


# ----------------------------- Telegram bot ---------------------------------

HELP_TEXT = """\
Send me a coupon as text or image (screenshot).

Commands:
- /list
- /del <id>
- /status
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

        self.openai_timeout_s = int(cfg.get("openai_timeout_seconds") or 60)
        self.openai_max_retries = int(cfg.get("openai_max_retries") or 2)
        self.openai_backoff_seconds = float(cfg.get("openai_retry_backoff_seconds") or 1.5)

        self.reminder_days = sorted({int(v) for v in list(cfg.get("reminder_days") or [30, 7, 1])}, reverse=True)
        self.scan_every_minutes = int(cfg.get("scan_every_minutes") or 30)

        self.incoming_dir = str(cfg.get("incoming_dir") or "incoming")
        self.health_file = str(cfg.get("health_file") or "runtime/bot_health.txt")
        self.started_at = datetime.now(timezone.utc)
        self.pending_by_user: Dict[int, Dict[str, Any]] = {}

        Path(self.incoming_dir).mkdir(parents=True, exist_ok=True)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        db_init(self.db_path)
        db_check(self.db_path)
        touch_health(self.health_file)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(HELP_TEXT)

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        uptime_s = int((datetime.now(timezone.utc) - self.started_at).total_seconds())
        await update.message.reply_text(
            "Bot status:\n"
            f"- db_path: {self.db_path}\n"
            f"- uptime_seconds: {uptime_s}\n"
            f"- scan_every_minutes: {self.scan_every_minutes}\n"
            f"- reminder_days: {','.join(str(d) for d in self.reminder_days)}\n"
            f"- text_model: {self.text_model}\n"
            f"- vision_model: {self.vision_model}"
        )

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

    async def _save_coupon_and_reply(self, update: Update, fields: Dict[str, Any], source_label: str = "") -> None:
        cid = db_add_coupon(self.db_path, update.effective_user.id, update.effective_user.full_name or "", fields)
        exp = datetime.fromisoformat(fields["expiry_utc"]).date().isoformat()
        touch_health(self.health_file)
        await update.message.reply_text(
            f"Saved coupon #{cid}{source_label}\n"
            f"- vendor: {fields.get('vendor') or '—'}\n"
            + (f"- value: {fields.get('value_ils')}₪\n" if fields.get("value_ils") is not None else "")
            + f"- code: {fields.get('code') or '—'}\n"
            + (f"- cvv: {fields.get('cvv')}\n" if fields.get("cvv") else "")
            + (f"- barcode: {fields.get('barcode')}\n" if fields.get("barcode") else "")
            + f"- expiry: {exp}\n"
        )

    async def _request_expiry_clarification(self, update: Update, fields: Dict[str, Any]) -> None:
        user_id = update.effective_user.id
        self.pending_by_user[user_id] = fields
        await update.message.reply_text(
            "I extracted most fields but expiry is unclear.\n"
            "Please reply with expiry only (date or duration), for example:\n"
            "- 2029-03-01\n"
            "- 01/03/2029\n"
            "- 5 years\n"
            "- 5 שנים"
        )

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = (update.message.text or "").strip()
        if not text:
            return
        user_id = update.effective_user.id

        if user_id in self.pending_by_user and len(text) <= 40:
            pending = self.pending_by_user[user_id]
            expiry_utc = normalize_expiry_to_utc_midnight(text) or infer_expiry_from_duration_text(text) or expiry_from_duration(
                value=text.split()[0] if text.split() else "",
                unit=text.split()[1] if len(text.split()) > 1 else "",
            )
            if expiry_utc:
                pending["expiry_utc"] = expiry_utc
                self.pending_by_user.pop(user_id, None)
                await self._save_coupon_and_reply(update, pending, source_label=" (after clarification)")
            else:
                await update.message.reply_text("Couldn't parse expiry yet. Reply with date (YYYY-MM-DD) or duration (e.g., 5 years).")
            return

        try:
            fields = extract_coupon_from_text(
                self.api_key,
                self.text_model,
                text,
                timeout_s=self.openai_timeout_s,
                max_retries=self.openai_max_retries,
                backoff_seconds=self.openai_backoff_seconds,
            )
        except Exception as e:
            log.warning("extract text failed user_id=%s error=%s", update.effective_user.id, e)
            await update.message.reply_text("I couldn't extract the coupon reliably. Try pasting the full message.")
            return

        if not fields.get("expiry_utc") or float(fields.get("confidence", 0.6)) < 0.35:
            await self._request_expiry_clarification(update, fields)
            return
        await self._save_coupon_and_reply(update, fields)

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        photo = update.message.photo[-1]
        f = await context.bot.get_file(photo.file_id)
        path = os.path.join(self.incoming_dir, f"{photo.file_id}.jpg")
        await f.download_to_drive(path)

        caption = (update.message.caption or "").strip()

        try:
            fields = extract_coupon_from_image(
                self.api_key,
                self.vision_model,
                path,
                caption=caption,
                timeout_s=max(self.openai_timeout_s, 90),
                max_retries=self.openai_max_retries,
                backoff_seconds=self.openai_backoff_seconds,
            )
        except Exception as e:
            log.warning("extract image failed user_id=%s error=%s", update.effective_user.id, e)
            await update.message.reply_text("I couldn't extract from the image. Try a clearer screenshot.")
            return

        if not fields.get("expiry_utc") or float(fields.get("confidence", 0.6)) < 0.35:
            await self._request_expiry_clarification(update, fields)
            return
        await self._save_coupon_and_reply(update, fields, source_label=" (from image)")

    async def reminder_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        now = datetime.now(timezone.utc)
        reminder_sent_count = 0
        expired_sent_count = 0

        with db_connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            for days in self.reminder_days:
                band_start, band_end = reminder_band_bounds(now, days)

                cur = conn.execute(
                    """
                    SELECT c.*
                    FROM coupons c
                    LEFT JOIN reminders_sent r
                      ON r.coupon_id = c.id AND r.days_before = ?
                    WHERE r.coupon_id IS NULL
                      AND date(c.expiry_utc) >= date(?)
                      AND date(c.expiry_utc) <  date(?)
                """,
                    (days, band_start.isoformat(), band_end.isoformat()),
                )

                for r in cur.fetchall():
                    exp = datetime.fromisoformat(r["expiry_utc"]).date().isoformat()
                    vendor = r["vendor"] or "—"
                    code = r["code"] or "—"
                    msg = f"⏰ Coupon reminder: {days} day(s) left\n{vendor} • `{code}` • expires {exp}"
                    try:
                        await context.bot.send_message(chat_id=r["user_id"], text=msg, parse_mode=ParseMode.MARKDOWN)
                        db_mark_reminder_sent(self.db_path, r["id"], days)
                        reminder_sent_count += 1
                    except Exception as e:
                        log.warning("send reminder failed coupon_id=%s error=%s", r["id"], e)

            cur2 = conn.execute(
                """
                SELECT *
                FROM coupons
                WHERE notified_expired = 0
                  AND date(expiry_utc) < date(?)
            """,
                (now.date().isoformat(),),
            )

            for r in cur2.fetchall():
                exp = datetime.fromisoformat(r["expiry_utc"]).date().isoformat()
                vendor = r["vendor"] or "—"
                code = r["code"] or "—"
                msg = f"⚠️ Coupon expired\n{vendor} • `{code}` • expired {exp}"
                try:
                    await context.bot.send_message(chat_id=r["user_id"], text=msg, parse_mode=ParseMode.MARKDOWN)
                    db_mark_expired_notified(self.db_path, r["id"])
                    expired_sent_count += 1
                except Exception as e:
                    log.warning("send expired notice failed coupon_id=%s error=%s", r["id"], e)

        touch_health(self.health_file)
        log.info(
            "reminder job completed reminders_sent=%s expired_sent=%s",
            reminder_sent_count,
            expired_sent_count,
        )

    def run(self) -> None:
        app = Application.builder().token(self.bot_token).build()

        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("status", self.cmd_status))
        app.add_handler(CommandHandler("list", self.cmd_list))
        app.add_handler(CommandHandler("del", self.cmd_del))

        app.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

        app.job_queue.run_repeating(self.reminder_job, interval=self.scan_every_minutes * 60, first=10)

        log.info(
            "Bot started db=%s text_model=%s vision_model=%s scan_every_minutes=%s",
            self.db_path,
            self.text_model,
            self.vision_model,
            self.scan_every_minutes,
        )
        touch_health(self.health_file)
        app.run_polling(close_loop=False)


# ----------------------------- main ------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    cfg = load_config(args.config)
    bot = CouponBot(cfg)
    bot.run()


if __name__ == "__main__":
    main()
