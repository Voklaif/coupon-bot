#!/usr/bin/env python3
import argparse
import urllib.request


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8080/health")
    p.add_argument("--timeout", type=float, default=3.0)
    args = p.parse_args()

    try:
        with urllib.request.urlopen(args.url, timeout=args.timeout) as r:
            return 0 if r.status == 200 else 1
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
