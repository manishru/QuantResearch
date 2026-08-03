#!/usr/bin/env python3
"""Report the next-session constituent rotation decision from cached ETF prices.

This is a read-only operational report for the experimental golden maturity
rotation.  It never downloads prices, never changes the golden strategy, and
uses only completed data on ``--as-of``.  A selected ETF is the highest-relative-
volume member of the three strongest price leaders; its volume must clear the
strict configured floor.  Its top three latest-public N-PORT holdings are the
candidate stock sleeve for the next available session.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import fmean

from backtest_etf_confirmed_momentum_overlay import rows
from backtest_etf_risk_off_constituent_short import latest_public_constituents, load_weighted_constituent_snapshots


def write(path: Path, values: list[dict]) -> None:
    fields = list(dict.fromkeys(key for value in values for key in value)) or ["etf"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(values)


def cached_history(cache_dir: Path, symbol: str) -> list[dict]:
    """Merge immutable cache fragments without calling EODHD or writing a cache."""
    merged: dict[str, dict] = {}
    prefix = symbol.replace(".", "_") + "_"
    for path in cache_dir.glob(prefix + "*.json"):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, list):
            merged.update({str(row["date"]): row for row in payload if isinstance(row, dict) and row.get("date")})
    return [merged[observed] for observed in sorted(merged)]


def screen_leaders(*, universe: list[str], history: dict[str, list[dict]], signal_date: date, as_of: date, top_n: int, minimum_relative_volume: float, selected_minimum_relative_volume: float) -> dict:
    """Screen completed ETF prices using the frozen top-price-then-volume rule."""
    spy = {row["date"]: float(row["adjusted_close"]) for row in history.get("SPY.US", []) if row.get("adjusted_close") is not None}
    unavailable: list[dict] = []
    qualified: list[dict] = []
    for symbol in universe:
        data = history.get(symbol, [])
        indexed = {row.get("date"): index for index, row in enumerate(data)}
        start_index, end_index = indexed.get(signal_date.isoformat()), indexed.get(as_of.isoformat())
        if start_index is None or end_index is None or end_index < 50:
            unavailable.append({"etf": symbol, "reason": "cache_does_not_cover_signal_or_as_of_date"})
            continue
        if signal_date.isoformat() not in spy or as_of.isoformat() not in spy:
            raise ValueError("SPY cache does not cover signal and as-of dates")
        try:
            close = float(data[end_index]["adjusted_close"])
            sma21 = fmean(float(row["adjusted_close"]) for row in data[end_index - 20:end_index + 1])
            sma50 = fmean(float(row["adjusted_close"]) for row in data[end_index - 49:end_index + 1])
            prior_volumes = [float(row.get("volume") or 0) for row in data[end_index - 21:end_index] if float(row.get("volume") or 0) > 0]
            relative_volume = float(data[end_index].get("volume") or 0) / fmean(prior_volumes) if prior_volumes else 0.0
            relative_return = (close / float(data[start_index]["adjusted_close"]) - 1) - (spy[as_of.isoformat()] / spy[signal_date.isoformat()] - 1)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            unavailable.append({"etf": symbol, "reason": "invalid_cached_price_or_volume"})
            continue
        if close > sma21 > sma50 and relative_volume >= minimum_relative_volume and relative_return > 0:
            qualified.append({"etf": symbol, "relative_return_vs_spy": relative_return, "relative_volume": relative_volume, "close": close, "sma_21": sma21, "sma_50": sma50})
    price_leaders = sorted(qualified, key=lambda row: (row["relative_return_vs_spy"], row["etf"]), reverse=True)[:top_n]
    if not price_leaders:
        return {"price_leaders": [], "selected": [], "unavailable": unavailable, "reason": "no_price_leaders"}
    winner = max(price_leaders, key=lambda row: (row["relative_volume"], row["relative_return_vs_spy"], row["etf"]))
    if winner["relative_volume"] < selected_minimum_relative_volume:
        return {"price_leaders": price_leaders, "selected": [], "unavailable": unavailable, "reason": "highest_volume_price_leader_below_strict_floor"}
    return {"price_leaders": price_leaders, "selected": [winner], "unavailable": unavailable, "reason": "selected"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rotation-universe", type=Path, required=True)
    parser.add_argument("--holdings", type=Path, action="append", required=True)
    parser.add_argument("--signal-date", type=date.fromisoformat, required=True, help="First completed date from which ETF relative return is measured.")
    parser.add_argument("--as-of", type=date.fromisoformat, required=True, help="Completed session used to make the next-session decision.")
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--minimum-relative-volume", type=float, default=1.0)
    parser.add_argument("--selected-minimum-relative-volume", type=float, default=3.0)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.signal_date >= args.as_of or args.top_n < 1 or args.minimum_relative_volume < 0 or args.selected_minimum_relative_volume < 0:
        parser.error("dates must be ordered, top-n must be positive, and volume floors cannot be negative")
    args.output.mkdir(parents=True, exist_ok=True)
    universe = sorted({row["etf"].upper() for row in rows(args.rotation_universe) if row.get("status", "").lower() == "approved"})
    history = {symbol: cached_history(args.cache_dir, symbol) for symbol in ["SPY.US", *universe]}
    result = screen_leaders(universe=universe, history=history, signal_date=args.signal_date, as_of=args.as_of, top_n=args.top_n, minimum_relative_volume=args.minimum_relative_volume, selected_minimum_relative_volume=args.selected_minimum_relative_volume)
    snapshots = load_weighted_constituent_snapshots(args.holdings)
    constituents: list[dict] = []
    for selected in result["selected"]:
        for holding in latest_public_constituents(snapshots.get(selected["etf"], []), args.as_of, 3):
            constituents.append({"etf": selected["etf"], "signal_date": args.signal_date.isoformat(), "as_of": args.as_of.isoformat(), "entry_session": "next_available_session", "relative_return_vs_spy": selected["relative_return_vs_spy"], "relative_volume": selected["relative_volume"], "constituent": holding["ticker"], "constituent_weight_pct": holding["weight_pct"], "holdings_as_of": holding["as_of_date"], "holdings_publication_date": holding["publication_date"]})
    report = {"strategy": "golden_etf_to_top3_constituent_rotation", "signal_date": args.signal_date.isoformat(), "as_of": args.as_of.isoformat(), "entry_session": "next_available_session", "top_n_price_leaders": args.top_n, "minimum_relative_volume": args.minimum_relative_volume, "selected_minimum_relative_volume": args.selected_minimum_relative_volume, "decision": "enter_constituent_sleeve" if constituents else "no_entry", "reason": result["reason"], "selected_etfs": result["selected"], "candidate_constituents": constituents, "unavailable_etf_count": len(result["unavailable"]), "data_rule": "Cache-only; no API request and no use of information after --as-of."}
    write(args.output / "price_leaders.csv", result["price_leaders"])
    write(args.output / "constituent_candidates.csv", constituents)
    write(args.output / "unavailable_etfs.csv", result["unavailable"])
    write(args.output / "decision.csv", [{key: value for key, value in report.items() if key not in {"selected_etfs", "candidate_constituents"}}])
    (args.output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
