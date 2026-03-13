#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--health-file", default="/app/runtime/bot_health.txt")
    p.add_argument("--max-age-seconds", type=int, default=600)
    args = p.parse_args()

    hp = Path(args.health_file)
    if not hp.exists():
        return 1

    try:
        ts = datetime.fromisoformat(hp.read_text(encoding="utf-8").strip())
    except Exception:
        return 1

    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return 0 if age <= args.max_age_seconds else 1


if __name__ == "__main__":
    raise SystemExit(main())
