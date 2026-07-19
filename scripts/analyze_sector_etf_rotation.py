#!/usr/bin/env python3
"""Fetch sector ETF history and rank recent sector rotation versus SPY.

Research-only price/volume rotation proxy; it does not identify institutional
buyers or sellers. The EODHD token is read only from an environment variable.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from statistics import fmean
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ETFS = {
    "SPY.US": "S&P 500",
    "RSP.US": "Equal-weight S&P 500",
    "XLK.US": "Technology",
    "XLC.US": "Communication Services",
    "XLY.US": "Consumer Discretionary",
    "XLF.US": "Financials",
    "XLI.US": "Industrials",
    "XLV.US": "Health Care",
    "XLE.US": "Energy",
    "XLB.US": "Materials",
    "XLU.US": "Utilities",
    "XLRE.US": "Real Estate",
    "XLP.US": "Consumer Staples",
    "SOXX.US": "Semiconductors",
    "SMH.US": "Semiconductors",
    "XSD.US": "Equal-weight Semiconductors",
    "DRAM.US": "Memory",
}

def fetch(symbol: str, start: date, end: date, token: str) -> list[dict]:
    query = urlencode(
        {"from": start.isoformat(), "to": end.isoformat(), "api_token": token, "fmt": "json"}
    )
    with urlopen(f"https://eodhd.com/api/eod/{symbol}?{query}", timeout=60) as response:  # noqa: S310
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, list): raise ValueError(f"unexpected response for {symbol}")
    return result


def build_observations(symbol: str, sector: str, data: list[dict]) -> list[dict]:
    """Calculate only from information available on each completed session."""
    observations: list[dict] = []
    for index in range(21, len(data)):
        current = data[index]
        prior = data[index - 21]
        prior_volumes = [float(item["volume"]) for item in data[index - 21 : index]]
        average_volume = fmean(prior_volumes)
        observations.append(
            {
                "date": current["date"],
                "symbol": symbol,
                "sector": sector,
                "return_21d": float(current["adjusted_close"]) / float(prior["adjusted_close"]) - 1,
                "relative_volume": float(current["volume"]) / average_volume if average_volume else None,
                "close": current["adjusted_close"],
            }
        )
    return observations


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--token-env", default="EODHD_API_TOKEN")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--history",
        action="store_true",
        help="also write daily sector leadership and semiconductor-versus-SPY history",
    )
    args = parser.parse_args()
    token = os.environ.get(args.token_env)
    if not token:
        parser.error(f"set {args.token_env}; token is never accepted on the command line")

    out = args.output.expanduser().resolve()
    raw = out / "raw_eodhd"
    raw.mkdir(parents=True, exist_ok=True)
    latest_rows: list[dict] = []
    all_observations: list[dict] = []
    unavailable: dict[str, str] = {}
    for symbol, sector in ETFS.items():
        cache = raw / f"{symbol.replace('.', '_')}_{args.start}_{args.to}.json"
        try:
            data = (
                fetch(symbol, args.start, args.to, token)
                if args.refresh or not cache.exists()
                else json.loads(cache.read_text())
            )
            if args.refresh or not cache.exists():
                cache.write_text(json.dumps(data, indent=2) + "\n")
        except Exception as error:  # An unavailable ETF must not discard all other sectors.
            unavailable[symbol] = str(error)
            continue
        if len(data) < 22:
            unavailable[symbol] = "fewer than 22 daily rows returned"
            continue
        observations = build_observations(symbol, sector, data)
        all_observations.extend(observations)
        latest_rows.append(observations[-1])

    spy = next((row for row in latest_rows if row["symbol"] == "SPY.US"), None)
    if spy is None:
        parser.error("SPY.US was unavailable; cannot calculate sector return versus S&P 500")
    for row in latest_rows:
        row["return_vs_spy_21d"] = row["return_21d"] - spy["return_21d"]
    latest_rows.sort(key=lambda row: row["return_vs_spy_21d"], reverse=True)
    report = out / "sector_rotation.csv"
    write_csv(report, latest_rows)

    history_reports: dict[str, str] = {}
    if args.history:
        spy_by_date = {
            row["date"]: row["return_21d"]
            for row in all_observations
            if row["symbol"] == "SPY.US"
        }
        history = []
        for row in all_observations:
            if row["date"] not in spy_by_date:
                continue
            row = row.copy()
            row["return_vs_spy_21d"] = row["return_21d"] - spy_by_date[row["date"]]
            row["activity_price_proxy"] = (
                "strength_with_activity"
                if row["return_vs_spy_21d"] > 0 and row["relative_volume"] > 1
                else "weakness_with_activity"
                if row["return_vs_spy_21d"] < 0 and row["relative_volume"] > 1
                else "neutral"
            )
            history.append(row)
        history.sort(key=lambda row: (row["date"], row["return_vs_spy_21d"]), reverse=True)
        history_report = out / "daily_sector_rotation.csv"
        write_csv(history_report, history)
        history_reports["daily_sector_rotation"] = str(history_report)

        by_date: dict[str, list[dict]] = {}
        for row in history:
            by_date.setdefault(row["date"], []).append(row)
        summary = []
        for observation_date, daily_rows in sorted(by_date.items(), reverse=True):
            leaders = sorted(daily_rows, key=lambda row: row["return_vs_spy_21d"], reverse=True)
            semis = [row for row in daily_rows if row["symbol"] in {"SMH.US", "SOXX.US", "XSD.US"}]
            if not semis:
                continue
            leader = leaders[0]
            summary.append(
                {
                    "date": observation_date,
                    "leading_symbol": leader["symbol"],
                    "leading_sector": leader["sector"],
                    "leading_return_vs_spy_21d": leader["return_vs_spy_21d"],
                    "leading_relative_volume": leader["relative_volume"],
                    "semiconductor_avg_return_vs_spy_21d": fmean(
                        row["return_vs_spy_21d"] for row in semis
                    ),
                    "semiconductor_avg_relative_volume": fmean(
                        row["relative_volume"] for row in semis if row["relative_volume"] is not None
                    ),
                    "semiconductor_state": (
                        "weakness_with_activity"
                        if fmean(row["return_vs_spy_21d"] for row in semis) < 0
                        and fmean(row["relative_volume"] for row in semis if row["relative_volume"] is not None) > 1
                        else "strength_with_activity"
                        if fmean(row["return_vs_spy_21d"] for row in semis) > 0
                        and fmean(row["relative_volume"] for row in semis if row["relative_volume"] is not None) > 1
                        else "neutral"
                    ),
                }
            )
        summary_report = out / "daily_rotation_summary.csv"
        write_csv(summary_report, summary)
        history_reports["daily_rotation_summary"] = str(summary_report)
    print(
        json.dumps(
            {
                "output": str(out),
                "report": str(report),
                "available_etfs": [row["symbol"] for row in latest_rows],
                "unavailable_etfs": unavailable,
                "history_reports": history_reports,
                "warning": "Price/volume leadership is a rotation proxy, not confirmed institutional flow.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
