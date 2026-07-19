#!/usr/bin/env python3
"""Measure breadth across the current holdings of semiconductor ETFs.

This is research-only. Holdings are a current EODHD snapshot, so this script
must not be used as a point-in-time historical constituent backtest. ETF price
history remains the non-survivorship-biased aggregate history.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import fmean, median
from urllib.parse import urlencode
from urllib.request import urlopen


DEFAULT_ETFS = ("SMH.US", "SOXX.US", "XSD.US")
US_EXCHANGES = {"US", "NASDAQ", "NYSE", "NYSE ARCA", "BATS"}


def fetch_json(url: str) -> object:
    with urlopen(url, timeout=60) as response:  # noqa: S310 - fixed vendor URL
        return json.loads(response.read().decode("utf-8"))


def fetch_holdings(etf: str, token: str) -> dict[str, dict]:
    query = urlencode({"api_token": token, "fmt": "json", "filter": "ETF_Data::Holdings"})
    result = fetch_json(f"https://eodhd.com/api/v1.1/fundamentals/{etf}?{query}")
    if not isinstance(result, dict):
        raise ValueError(f"unexpected holdings response for {etf}")
    # Depending on endpoint version/plan, EODHD returns either the holdings map
    # directly or wraps it in ETF_Data/Holdings (or Holdings).
    candidate: object = result
    if isinstance(candidate.get("ETF_Data"), dict):
        candidate = candidate["ETF_Data"].get("Holdings", candidate["ETF_Data"])
    if isinstance(candidate, dict) and isinstance(candidate.get("Holdings"), dict):
        candidate = candidate["Holdings"]
    if not isinstance(candidate, dict):
        raise ValueError(f"no holdings map in response for {etf}")
    return {str(symbol): value for symbol, value in candidate.items() if isinstance(value, dict)}


def normalise_us_symbol(provider_symbol: str, details: dict) -> str | None:
    """Return EODHD's US symbol for direct or wrapped holding formats."""
    exchange = str(details.get("Exchange", "")).upper()
    code = str(details.get("Code", provider_symbol)).upper()
    if provider_symbol.upper().endswith(".US"):
        return provider_symbol.upper()
    if exchange in US_EXCHANGES:
        return f"{code}.US"
    return None


def fetch_prices(symbol: str, start: date, end: date, token: str) -> list[dict]:
    query = urlencode(
        {"from": start.isoformat(), "to": end.isoformat(), "api_token": token, "fmt": "json"}
    )
    result = fetch_json(f"https://eodhd.com/api/eod/{symbol}?{query}")
    if not isinstance(result, list):
        raise ValueError(f"unexpected EOD response for {symbol}")
    return result


def observations(symbol: str, bars: list[dict]) -> list[dict]:
    result: list[dict] = []
    for index in range(21, len(bars)):
        current, prior = bars[index], bars[index - 21]
        volumes = [float(bar["volume"]) for bar in bars[index - 21 : index]]
        mean_volume = fmean(volumes)
        result.append(
            {
                "date": current["date"],
                "symbol": symbol,
                "return_21d": float(current["adjusted_close"]) / float(prior["adjusted_close"]) - 1,
                "relative_volume": float(current["volume"]) / mean_volume if mean_volume else None,
                "close": current["adjusted_close"],
            }
        )
    return result


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--etf", action="append", default=[])
    parser.add_argument("--token-env", default="EODHD_API_TOKEN")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    token = os.environ.get(args.token_env)
    if not token:
        parser.error(f"set {args.token_env}; token is never accepted on the command line")

    output = args.output.expanduser().resolve()
    raw = output / "raw_eodhd"
    raw.mkdir(parents=True, exist_ok=True)
    etfs = tuple(args.etf) if args.etf else DEFAULT_ETFS

    constituents: dict[str, dict] = {}
    holding_rows: list[dict] = []
    errors: dict[str, str] = {}
    for etf in etfs:
        cache = raw / f"holdings_{etf.replace('.', '_')}.json"
        try:
            holdings = (
                fetch_holdings(etf, token)
                if args.refresh or not cache.exists()
                else json.loads(cache.read_text(encoding="utf-8"))
            )
            if args.refresh or not cache.exists():
                cache.write_text(json.dumps(holdings, indent=2) + "\n", encoding="utf-8")
        except Exception as error:
            errors[etf] = str(error)
            continue
        for provider_symbol, details in holdings.items():
            # The analysis is limited to US-listed holdings that EODHD identifies
            # with a directly fetchable provider symbol such as NVDA.US.
            us_symbol = normalise_us_symbol(provider_symbol, details)
            if us_symbol is None:
                continue
            constituents.setdefault(us_symbol, details)
            holding_rows.append(
                {
                    "etf": etf,
                    "provider_symbol": us_symbol,
                    "ticker": details.get("Code", us_symbol.removesuffix(".US")),
                    "name": details.get("Name", ""),
                    "industry": details.get("Industry", ""),
                    "assets_pct": details.get("Assets_%", ""),
                }
            )
    if not constituents:
        parser.error(f"no US-listed ETF holdings were returned; endpoint details: {errors}")
    holding_rows.sort(key=lambda row: (row["etf"], -float(row["assets_pct"] or 0)))
    write_csv(output / "current_etf_holdings.csv", holding_rows)

    daily: list[dict] = []
    for symbol in sorted(constituents):
        cache = raw / f"prices_{symbol.replace('.', '_')}_{args.start}_{args.to}.json"
        try:
            bars = (
                fetch_prices(symbol, args.start, args.to, token)
                if args.refresh or not cache.exists()
                else json.loads(cache.read_text(encoding="utf-8"))
            )
            if args.refresh or not cache.exists():
                cache.write_text(json.dumps(bars, indent=2) + "\n", encoding="utf-8")
            if len(bars) >= 22:
                daily.extend(observations(symbol, bars))
            else:
                errors[symbol] = "fewer than 22 daily rows returned"
        except Exception as error:
            errors[symbol] = str(error)
    if not daily:
        parser.error("no constituent price histories were available")

    by_date: dict[str, list[dict]] = defaultdict(list)
    for row in daily:
        by_date[row["date"]].append(row)
    breadth: list[dict] = []
    for observation_date, rows in sorted(by_date.items(), reverse=True):
        usable_volume = [row["relative_volume"] for row in rows if row["relative_volume"] is not None]
        positive = [row for row in rows if row["return_21d"] > 0]
        active_positive = [row for row in positive if row["relative_volume"] is not None and row["relative_volume"] > 1]
        active_negative = [
            row
            for row in rows
            if row["return_21d"] < 0 and row["relative_volume"] is not None and row["relative_volume"] > 1
        ]
        breadth.append(
            {
                "date": observation_date,
                "constituent_count": len(rows),
                "positive_21d_count": len(positive),
                "positive_21d_pct": len(positive) / len(rows),
                "equal_weight_return_21d": fmean(row["return_21d"] for row in rows),
                "median_return_21d": median(row["return_21d"] for row in rows),
                "average_relative_volume": fmean(usable_volume) if usable_volume else None,
                "positive_with_activity_count": len(active_positive),
                "negative_with_activity_count": len(active_negative),
            }
        )
    daily.sort(key=lambda row: (row["date"], row["return_21d"]), reverse=True)
    write_csv(output / "daily_constituent_returns.csv", daily)
    write_csv(output / "daily_constituent_breadth.csv", breadth)
    latest_date = breadth[0]["date"]
    latest = [row for row in daily if row["date"] == latest_date]
    latest.sort(key=lambda row: row["return_21d"], reverse=True)
    write_csv(output / "latest_constituent_ranking.csv", latest)
    print(
        json.dumps(
            {
                "output": str(output),
                "etfs": list(etfs),
                "unique_current_us_constituents": len(constituents),
                "latest_date": latest_date,
                "holdings_report": str(output / "current_etf_holdings.csv"),
                "breadth_report": str(output / "daily_constituent_breadth.csv"),
                "latest_ranking": str(output / "latest_constituent_ranking.csv"),
                "unavailable": errors,
                "limitation": "Current ETF holdings are not historical holdings; use this for current breadth, not a point-in-time historical stock-selection backtest.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
