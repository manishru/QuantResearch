#!/usr/bin/env python3
"""Replace selected ETF sleeves with equal-weight top-three N-PORT stocks.

The source ETF sleeve ledger is immutable input.  Each eligible ETF sleeve is
replaced by its three highest-weight holdings from the latest public snapshot
available on the sleeve entry date.  A constituent exits at a 40% stop or at
the source ETF sleeve's recorded exit date; early stop proceeds remain cash.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import fmean

import duckdb

from backtest_etf_confirmed_momentum_overlay import rows
from backtest_etf_risk_off_constituent_short import latest_public_constituents, load_weighted_constituent_snapshots


def write(path: Path, values: list[dict]) -> None:
    fields = list(dict.fromkeys(key for value in values for key in value)) or ["source_etf"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(values)


def simulate_long(bars: list[dict], entry_date: date, scheduled_exit: date, stop_pct: float) -> dict | None:
    start = next((index for index, bar in enumerate(bars) if bar["date"] == entry_date), None)
    if start is None:
        return None
    entry = bars[start]["open"]
    stop = entry * (1 - stop_pct)
    for bar in bars[start:]:
        if bar["date"] >= scheduled_exit:
            return {"entry_price": entry, "exit_date": bar["date"], "exit_price": bar["open"], "exit_reason": "source_etf_exit"}
        if bar["low"] <= stop:
            return {"entry_price": entry, "exit_date": bar["date"], "exit_price": min(bar["open"], stop), "exit_reason": "stock_stop"}
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--etf-overlay-trades", type=Path, required=True)
    parser.add_argument("--holdings", type=Path, action="append", required=True, help="Repeat for every normalized, ticker-resolved N-PORT holdings CSV.")
    parser.add_argument("--parquet", type=Path, default=Path("data/validated/sp500/eod_adjusted_current.parquet"))
    parser.add_argument("--stock-stop", type=float, default=.40)
    parser.add_argument("--cost", type=float, default=.001)
    parser.add_argument("--source-portfolio-value", type=float, required=True, help="Final value reported by the source ETF-sleeve run.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.stock_stop < 1 or args.cost < 0 or args.source_portfolio_value <= 0:
        parser.error("stock stop must be in (0, 1); cost must be non-negative; source portfolio value must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    snapshots = load_weighted_constituent_snapshots(args.holdings)
    sleeves = [row for row in rows(args.etf_overlay_trades) if row.get("entry_date") and row.get("exit_date") and row.get("allocation")]
    requested: dict[tuple[str, str, str], list[dict]] = {}
    tickers: set[str] = set()
    skipped: list[dict] = []
    for sleeve in sleeves:
        entry_date = date.fromisoformat(sleeve["entry_date"])
        selected = latest_public_constituents(snapshots.get(sleeve["etf"], []), entry_date, 3)
        if len(selected) != 3:
            skipped.append({"source_etf": sleeve["etf"], "entry_date": sleeve["entry_date"], "reason": "fewer_than_three_public_point_in_time_constituents"}); continue
        key = (sleeve["source_id"], sleeve["etf"], sleeve["entry_date"])
        requested[key] = selected; tickers.update(row["ticker"] for row in selected)
    bars: dict[str, list[dict]] = defaultdict(list)
    if tickers:
        marks = ",".join("?" for _ in tickers)
        connection = duckdb.connect(":memory:")
        try:
            raw = connection.execute(f"SELECT upper(Ticker), cast(Date as date), Open, Low FROM read_parquet(?) WHERE upper(Ticker) IN ({marks}) ORDER BY 1, 2", [str(args.parquet), *sorted(tickers)]).fetchall()
        finally:
            connection.close()
        for ticker, observed, opened, low in raw:
            if opened is not None and low is not None and opened > 0 and low > 0:
                bars[ticker].append({"date": observed, "open": float(opened), "low": float(low)})
    trades: list[dict] = []; replaced_etf_proceeds = 0.0; replacement_proceeds = 0.0; replaced_allocation = 0.0
    for sleeve in sleeves:
        key = (sleeve["source_id"], sleeve["etf"], sleeve["entry_date"])
        selected = requested.get(key)
        if not selected:
            continue
        allocation = float(sleeve["allocation"]) / 3
        outcomes = []
        for holding in selected:
            outcome = simulate_long(bars.get(holding["ticker"], []), date.fromisoformat(sleeve["entry_date"]), date.fromisoformat(sleeve["exit_date"]), args.stock_stop)
            if not outcome:
                skipped.append({"source_etf": sleeve["etf"], "entry_date": sleeve["entry_date"], "ticker": holding["ticker"], "reason": "missing_stock_ohlc"}); continue
            shares = allocation * (1 - args.cost) / outcome["entry_price"]
            proceeds = shares * outcome["exit_price"] * (1 - args.cost)
            outcomes.append({"source_etf": sleeve["etf"], "source_id": sleeve["source_id"], "source_ticker": sleeve.get("source_ticker", ""), "source_signal_date": sleeve.get("source_signal_date", ""), "maturity_date": sleeve.get("maturity_date", ""), "entry_date": sleeve["entry_date"], "constituent": holding["ticker"], "constituent_weight_pct": holding["weight_pct"], "holdings_as_of": holding["as_of_date"], "holdings_publication_date": holding["publication_date"], "stock_allocation": allocation, "shares": shares, **outcome, "net_proceeds": proceeds, "net_profit": proceeds - allocation})
        if len(outcomes) != 3:
            skipped.append({"source_etf": sleeve["etf"], "entry_date": sleeve["entry_date"], "reason": "incomplete_constituent_price_coverage"}); continue
        trades.extend(outcomes); replaced_etf_proceeds += float(sleeve["net_proceeds"]); replacement_proceeds += sum(row["net_proceeds"] for row in outcomes); replaced_allocation += float(sleeve["allocation"])
    adjusted_value = args.source_portfolio_value - replaced_etf_proceeds + replacement_proceeds
    summary = {"source_etf_sleeves": len(sleeves), "replaced_etf_sleeves": len({(row["source_id"], row["source_etf"], row["entry_date"]) for row in trades}), "constituent_trades": len(trades), "stock_stop": args.stock_stop, "source_portfolio_value": args.source_portfolio_value, "coverage_matched_sleeve_allocation": replaced_allocation, "coverage_matched_etf_proceeds": replaced_etf_proceeds, "coverage_matched_etf_return": replaced_etf_proceeds / replaced_allocation - 1 if replaced_allocation else 0.0, "coverage_matched_constituent_proceeds": replacement_proceeds, "coverage_matched_constituent_return": replacement_proceeds / replaced_allocation - 1 if replaced_allocation else 0.0, "coverage_matched_incremental_value": replacement_proceeds - replaced_etf_proceeds, "constituent_sleeve_portfolio_value": adjusted_value, "incremental_value_vs_etf": adjusted_value - args.source_portfolio_value, "mean_constituent_net_return_pct": fmean(row["net_profit"] / row["stock_allocation"] for row in trades) if trades else 0.0, "skipped": len(skipped), "limitation": "The coverage-matched result is the valid ETF-versus-stock comparison. Only sleeves with three public point-in-time N-PORT constituents and complete daily OHLC are replaced; pre-publication ETF sleeves are excluded from that comparison and remain unchanged only in the mixed portfolio value. This is research only; it models no taxes, borrow, liquidity, or intraday stop ordering."}
    write(args.output / "constituent_trades.csv", trades); write(args.output / "skipped_sleeves.csv", skipped); write(args.output / "comparison.csv", [summary]); (args.output / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__": main()
