#!/usr/bin/env python3
"""Inventory current direct long/inverse ETFs for a momentum trade file.

The ETF inventory is a current TradingView snapshot.  It is intentionally not
used to infer that a product existed at an earlier historical trade date.
"""
from __future__ import annotations

import argparse
import ast
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def description(row: dict[str, str]) -> str:
    raw = row.get("ticker-view") or ""
    try:
        return str(ast.literal_eval(raw).get("description") or raw)
    except (ValueError, SyntaxError):
        return raw


def direction(text: str) -> str | None:
    lower = f" {text.lower()} "
    if any(word in lower for word in (" short ", " bear ", " inverse ")):
        return "inverse"
    if any(word in lower for word in (" long ", " bull ", " ultra ")):
        return "long"
    return None


def company_aliases(snapshot: Path | None) -> dict[str, list[str]]:
    if not snapshot:
        return {}
    aliases: dict[str, list[str]] = {}
    suffixes = re.compile(r"\b(incorporated|corporation|corp|company|co|limited|ltd|plc|holdings|technologies|technology|class [a-z]+)\b", re.I)
    for row in read_csv(snapshot):
        ticker = row.get("ticker", "")
        text = description(row)
        cleaned = re.sub(r"[^A-Za-z ]", " ", text)
        cleaned = suffixes.sub(" ", cleaned)
        words = [word for word in cleaned.split() if len(word) >= 4]
        if words:
            # One distinctive company-name token is enough for a supplemental
            # match; the ETF must still explicitly state long/bull/short/bear.
            aliases[ticker] = [words[0].upper()]
    return aliases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trades", type=Path, required=True)
    parser.add_argument("--etf-snapshot", type=Path, required=True)
    parser.add_argument("--stock-snapshot", type=Path, help="Optional TradingView stock snapshot for company-name matching.")
    parser.add_argument("--nominal-day", type=int, help="Limit to this entry day.")
    parser.add_argument("--top-n", type=int, help="Limit to this portfolio rank setting.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    trades = read_csv(args.trades)
    if args.nominal_day is not None:
        trades = [row for row in trades if row.get("nominal_day") == str(args.nominal_day)]
    if args.top_n is not None:
        trades = [row for row in trades if row.get("top_n") == str(args.top_n)]
    if not trades:
        parser.error("no trades remain after filters")
    aliases = company_aliases(args.stock_snapshot)
    by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in trades:
        by_ticker[row["ticker"]].append(row)
    candidates: dict[str, list[dict[str, str]]] = defaultdict(list)
    for etf in read_csv(args.etf_snapshot):
        text = description(etf)
        direct = direction(text)
        if not direct:
            continue
        for ticker in by_ticker:
            terms = [ticker, *aliases.get(ticker, [])]
            if any(re.search(rf"(?<![A-Z0-9]){re.escape(term)}(?![A-Z0-9])", text.upper()) for term in terms):
                candidates[ticker].append({"ticker": etf["ticker"], "direction": direct, "description": text,
                                           "aum": etf.get("aum", ""), "value_traded": etf.get("Value.Traded", "")})
    args.output.mkdir(parents=True, exist_ok=True)
    report: list[dict[str, object]] = []
    direct_rows: list[dict[str, object]] = []
    for ticker in sorted(by_ticker):
        rows = by_ticker[ticker]
        matches = candidates[ticker]
        longs = [row["ticker"] for row in matches if row["direction"] == "long"]
        inverse = [row["ticker"] for row in matches if row["direction"] == "inverse"]
        report.append({"ticker": ticker, "selection_count": len(rows), "first_signal_date": min(row["signal_date"] for row in rows),
                       "last_signal_date": max(row["signal_date"] for row in rows), "current_long_etfs": ";".join(longs),
                       "current_inverse_etfs": ";".join(inverse), "direct_etf_status": "found" if matches else "none_found"})
        for match in matches:
            direct_rows.append({"underlying_ticker": ticker, **match})
    fields = ["ticker", "selection_count", "first_signal_date", "last_signal_date", "current_long_etfs", "current_inverse_etfs", "direct_etf_status"]
    with (args.output / "momentum_ticker_direct_etf_inventory.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(report)
    detail_fields = ["underlying_ticker", "ticker", "direction", "description", "aum", "value_traded"]
    with (args.output / "current_direct_etf_matches.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=detail_fields); writer.writeheader(); writer.writerows(direct_rows)
    print(f"wrote {len(report)} unique momentum tickers; {sum(row['direct_etf_status'] == 'found' for row in report)} have current direct ETF matches to {args.output}")


if __name__ == "__main__":
    main()
