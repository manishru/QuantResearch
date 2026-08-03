#!/usr/bin/env python3
"""Fetch reviewed momentum-sector ETF histories from EODHD into a shared cache.

The cache naming intentionally matches ``backtest_sector_cooldown_momentum.py``.
Only approved mappings are downloaded; exclusions never produce API requests.
The EODHD token is read from an environment variable and is never printed.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def mapping_symbols(static: Path, intervals: Path) -> set[str]:
    symbols = {"SPY.US"}
    for path in (static, intervals):
        if not path.is_file():
            continue
        for row in read_rows(path):
            if row.get("status", "approved").lower() != "approved":
                continue
            for field in ("primary_etf", "direct_long_etf", "direct_inverse_etf"):
                if row.get(field):
                    symbols.add(row[field].upper())
    return symbols


def fetch(symbol: str, start: date, end: date, token: str) -> list[dict]:
    query = urlencode({"api_token": token, "fmt": "json", "from": start.isoformat(), "to": end.isoformat()})
    request = Request(f"https://eodhd.com/api/eod/{symbol}?{query}", headers={"User-Agent": "QuantResearch ETF history fetcher"})
    with urlopen(request, timeout=60) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, list):
        raise RuntimeError(f"unexpected EODHD response: {payload}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True, help="First cache date; use six months before the backtest start.")
    parser.add_argument("--end", type=date.fromisoformat, required=True, help="Last completed-close date.")
    parser.add_argument("--mapping", type=Path, default=Path("config/etf_confirmed_momentum_mapping.csv"))
    parser.add_argument("--mapping-intervals", type=Path, default=Path("config/etf_confirmed_momentum_mapping_intervals.csv"))
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true", help="Re-download cache entries that already exist.")
    parser.add_argument("--request-delay-seconds", type=float, default=0.15)
    parser.add_argument("--token-env", default="EODHD_API_TOKEN")
    args = parser.parse_args()
    if args.end < args.start:
        parser.error("--end must be on or after --start")
    token = os.environ.get(args.token_env)
    if not token:
        parser.error(f"set {args.token_env}; tokens are not accepted on the command line")
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    for ordinal, symbol in enumerate(sorted(mapping_symbols(args.mapping, args.mapping_intervals)), start=1):
        path = args.cache_dir / f"{symbol.replace('.', '_')}_{args.start}_{args.end}.json"
        if path.is_file() and not args.refresh:
            payload = json.loads(path.read_text(encoding="utf-8"))
            manifest.append({"symbol": symbol, "status": "cached", "rows": len(payload), "file": str(path), "error": ""})
            continue
        try:
            payload = fetch(symbol, args.start, args.end, token)
            path.write_text(json.dumps(payload), encoding="utf-8")
            manifest.append({"symbol": symbol, "status": "fetched", "rows": len(payload), "file": str(path), "error": ""})
        except Exception as error:  # Keep successful files and report failures for review.
            manifest.append({"symbol": symbol, "status": "error", "rows": 0, "file": str(path), "error": str(error)})
        print(f"[{ordinal}] {symbol}: {manifest[-1]['status']}", flush=True)
        if args.request_delay_seconds > 0:
            time.sleep(args.request_delay_seconds)
    manifest_path = args.cache_dir / f"momentum_mapping_etf_fetch_{args.start}_{args.end}.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        out = csv.DictWriter(handle, fieldnames=["symbol", "status", "rows", "file", "error"])
        out.writeheader(); out.writerows(manifest)
    errors = [row for row in manifest if row["status"] == "error"]
    print(json.dumps({"symbols": len(manifest), "fetched": sum(row["status"] == "fetched" for row in manifest), "cached": sum(row["status"] == "cached" for row in manifest), "errors": len(errors), "manifest": str(manifest_path)}, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
