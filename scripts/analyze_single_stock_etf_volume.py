#!/usr/bin/env python3
"""Compare recent price and trading-volume trends for selected ETFs.

Designed for research monitoring of single-stock long/inverse ETFs.  Price
returns use adjusted close; both share-volume and dollar-volume are reported
because ETF share splits can distort a raw share-volume comparison.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date
from pathlib import Path
from statistics import fmean
from urllib.parse import urlencode
from urllib.request import urlopen


DEFAULT_SYMBOLS = ("SNXX", "SNDQ", "MUD", "MUZ")


def fetch(symbol: str, token: str, as_of: date | None) -> list[dict]:
    parameters = {"api_token": token, "fmt": "json"}
    if as_of:
        parameters["to"] = as_of.isoformat()
    request = urlencode(parameters)
    with urlopen(f"https://eodhd.com/api/eod/{symbol}.US?{request}", timeout=60) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, list):
        raise RuntimeError(str(payload))
    return sorted(payload, key=lambda row: row["date"])


def average(rows: list[dict], field: str) -> float:
    return fmean(float(row.get(field) or 0) for row in rows)


def summarize(symbol: str, rows: list[dict], window: int) -> dict[str, object]:
    if len(rows) < 2 * window + 1:
        raise ValueError(f"{symbol}: needs at least {2 * window + 1} sessions; received {len(rows)}")
    recent, prior = rows[-window:], rows[-2 * window:-window]
    recent_share = average(recent, "volume")
    prior_share = average(prior, "volume")
    recent_dollar = fmean(float(row.get("close") or 0) * float(row.get("volume") or 0) for row in recent)
    prior_dollar = fmean(float(row.get("close") or 0) * float(row.get("volume") or 0) for row in prior)
    first, latest = recent[0], recent[-1]
    return {
        "ticker": symbol,
        "latest_date": latest["date"],
        "window_sessions": window,
        "price_return": float(latest["adjusted_close"]) / float(first["adjusted_close"]) - 1,
        "recent_avg_share_volume": recent_share,
        "prior_avg_share_volume": prior_share,
        "share_volume_change": recent_share / prior_share - 1 if prior_share else None,
        "recent_avg_dollar_volume": recent_dollar,
        "prior_avg_dollar_volume": prior_dollar,
        "dollar_volume_change": recent_dollar / prior_dollar - 1 if prior_dollar else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", action="append", default=[], help="Ticker without .US; repeatable.")
    parser.add_argument("--as-of", type=date.fromisoformat, help="Optional last date to include.")
    parser.add_argument("--window", action="append", type=int, default=[], help="Sessions, e.g. 21 and 30.")
    parser.add_argument("--token-env", default="EODHD_API_TOKEN")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get(args.token_env)
    if not token:
        parser.error(f"set {args.token_env}; tokens are intentionally not accepted on the command line")
    symbols = args.symbol or list(DEFAULT_SYMBOLS)
    windows = args.window or [21, 30]
    if any(window < 2 for window in windows):
        parser.error("--window must be at least 2")
    args.output.mkdir(parents=True, exist_ok=True)
    report: list[dict[str, object]] = []
    errors: dict[str, str] = {}
    for symbol in symbols:
        symbol = symbol.upper().removesuffix(".US")
        try:
            rows = fetch(symbol, token, args.as_of)
            for window in windows:
                report.append(summarize(symbol, rows, window))
        except Exception as error:
            errors[symbol] = str(error)
    fields = ["ticker", "latest_date", "window_sessions", "price_return", "recent_avg_share_volume", "prior_avg_share_volume", "share_volume_change", "recent_avg_dollar_volume", "prior_avg_dollar_volume", "dollar_volume_change"]
    with (args.output / "volume_trend.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report)
    summary = {"output": str(args.output.resolve()), "symbols": symbols, "windows": windows, "errors": errors, "report": str((args.output / "volume_trend.csv").resolve())}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
