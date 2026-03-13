import json
from datetime import datetime, timezone

import pytest

from coupon_bot import (
    infer_expiry_from_duration_text,
    normalize_expiry_to_utc_midnight,
    parse_extraction_payload,
    reminder_band_bounds,
)


def test_normalize_expiry_iso():
    assert normalize_expiry_to_utc_midnight("2026-12-01") == "2026-12-01T00:00:00+00:00"


def test_normalize_expiry_dmy():
    assert normalize_expiry_to_utc_midnight("01/12/2026") == "2026-12-01T00:00:00+00:00"


def test_normalize_expiry_mmyy_month_end():
    assert normalize_expiry_to_utc_midnight("02/26") == "2026-02-28T00:00:00+00:00"


def test_normalize_expiry_invalid():
    assert normalize_expiry_to_utc_midnight("31/02/2026") is None


def test_parse_extraction_payload_success():
    payload = json.dumps(
        {
            "vendor": "Store",
            "value_ils": 50,
            "code": "ABC123",
            "cvv": "111",
            "barcode": "123456",
            "expiry_type": "date",
            "expiry_date": "2026-10-05",
            "expiry_duration": None,
            "confidence": 0.9,
        }
    )
    parsed = parse_extraction_payload(payload, raw="src")
    assert parsed["vendor"] == "Store"
    assert parsed["expiry_utc"] == "2026-10-05T00:00:00+00:00"


def test_parse_extraction_payload_unknown_expiry_returns_none():
    parsed = parse_extraction_payload(
        '{"vendor":"X","expiry_type":"unknown","expiry_date":null,"expiry_duration":null,"confidence":0.2}',
        raw="src",
    )
    assert parsed["expiry_utc"] is None
    assert parsed["expiry_type"] == "unknown"


def test_reminder_band_bounds():
    now = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
    start, end = reminder_band_bounds(now, 7)
    assert start.isoformat() == "2026-03-13"
    assert end.isoformat() == "2026-03-14"


def test_infer_expiry_from_duration_hebrew_years():
    now = datetime(2026, 3, 7, 15, 20, tzinfo=timezone.utc)
    raw = "תוקף השובר: 5 שנים"
    assert infer_expiry_from_duration_text(raw, now=now) == "2031-03-07T00:00:00+00:00"


def test_parse_extraction_payload_duration_object():
    payload = json.dumps(
        {
            "vendor": "Store",
            "expiry_type": "duration",
            "expiry_date": None,
            "expiry_duration": {"value": 5, "unit": "years"},
            "confidence": 0.7,
        }
    )
    parsed = parse_extraction_payload(payload, raw="src")
    assert parsed["expiry_utc"] is not None
