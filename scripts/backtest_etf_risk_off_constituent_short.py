#!/usr/bin/env python3
"""Research-only short event study after an ETF's completed-close risk-off signal.

For every approved ETF, a new risk-off state is detected when its trailing
return trails SPY, relative volume is elevated, and drawdown from its running
peak exceeds the configured threshold.  The script then selects the highest
weighted constituent from the latest *public* N-PORT snapshot available on the
signal date and shorts it at the next stock-session open.

This is not investment advice.  It does not create orders and never substitutes
current holdings for a missing historical snapshot.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import fmean

import duckdb

from backtest_etf_confirmed_momentum_overlay import fetch, rows
from backtest_sector_cooldown_momentum import add_months, load_price_alias_resolver


def write(path: Path, values: list[dict]) -> None:
    fields = list(dict.fromkeys(key for row in values for key in row)) if values else ["etf"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(values)


def approved_etfs(path: Path) -> list[str]:
    return sorted(row["etf"].upper() for row in rows(path) if row.get("status", "approved").lower() == "approved")


def load_largest_constituents(paths: list[Path]) -> dict[str, list[dict]]:
    """Return one largest constituent for every ETF/publication-date snapshot."""
    snapshots: dict[tuple[str, str], dict] = {}
    for path in paths:
        for row in rows(path):
            try:
                weight = float(row.get("weight_pct") or 0)
            except ValueError:
                continue
            etf, ticker, published = row.get("etf", "").upper(), row.get("ticker", "").upper(), row.get("publication_date", "")
            if not etf or not ticker or not published:
                continue
            key = (etf, published)
            candidate = {**row, "etf": etf, "ticker": ticker, "weight_pct": weight}
            if key not in snapshots or weight > snapshots[key]["weight_pct"]:
                snapshots[key] = candidate
    by_etf: dict[str, list[dict]] = defaultdict(list)
    for candidate in snapshots.values():
        by_etf[candidate["etf"]].append(candidate)
    for candidates in by_etf.values():
        candidates.sort(key=lambda item: item["publication_date"])
    return by_etf


def load_weighted_constituent_snapshots(paths: list[Path]) -> dict[str, list[dict]]:
    """Load every dated ETF snapshot, retaining constituents by descending weight."""
    snapshots: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for path in paths:
        for row in rows(path):
            try:
                weight = float(row.get("weight_pct") or 0)
            except ValueError:
                continue
            etf, ticker, published = row.get("etf", "").upper(), row.get("ticker", "").upper(), row.get("publication_date", "")
            if etf and ticker and published:
                snapshots[(etf, published)].append({**row, "etf": etf, "ticker": ticker, "weight_pct": weight})
    by_etf: dict[str, list[dict]] = defaultdict(list)
    for (etf, published), constituents in snapshots.items():
        by_etf[etf].append({"publication_date": published, "constituents": sorted(constituents, key=lambda row: (-row["weight_pct"], row["ticker"]))})
    for records in by_etf.values():
        records.sort(key=lambda row: row["publication_date"])
    return by_etf


def latest_public_constituents(snapshots: list[dict], observed: date, count: int) -> list[dict]:
    eligible = [row for row in snapshots if date.fromisoformat(row["publication_date"]) <= observed]
    return eligible[-1]["constituents"][:count] if eligible else []


def update_consecutive_risk_off_months(months: list[tuple[int, int]], observed: date) -> list[tuple[int, int]]:
    """Record a calendar month containing risk-off, resetting after a gap."""
    current = (observed.year, observed.month)
    if not months or months[-1] == current:
        return months if months else [current]
    year, month = months[-1]
    expected = (year + 1, 1) if month == 12 else (year, month + 1)
    return [*months, current] if current == expected else [current]


def latest_public_constituent(candidates: list[dict], observed: date) -> dict | None:
    eligible = [row for row in candidates if date.fromisoformat(row["publication_date"]) <= observed]
    return eligible[-1] if eligible else None


def risk_state(data: list[dict], spy: dict[str, float], index: int, lookback: int) -> dict | None:
    if index < lookback:
        return None
    row, prior = data[index], data[index - lookback]
    observed = row["date"]
    if observed not in spy or prior["date"] not in spy or not row.get("adjusted_close") or not prior.get("adjusted_close"):
        return None
    volumes = [float(item.get("volume") or 0) for item in data[index - lookback:index] if float(item.get("volume") or 0) > 0]
    if not volumes:
        return None
    close = float(row["adjusted_close"])
    peak = max(float(item["adjusted_close"]) for item in data[: index + 1] if item.get("adjusted_close") is not None)
    return {
        "return": close / float(prior["adjusted_close"]) - 1,
        "vs_spy": close / float(prior["adjusted_close"]) - spy[observed] / spy[prior["date"]] + 1,
        "relative_volume": float(row.get("volume") or 0) / fmean(volumes),
        "drawdown": close / peak - 1,
    }


def simulate_short(bars: list[dict], entry_at: date, stop_pct: float, target_pct: float, hold_months: int, conflict: str) -> dict | None:
    """Use split-adjusted OHLC; a stop-first conflict is deliberately conservative."""
    start = next((index for index, bar in enumerate(bars) if bar["date"] > entry_at), None)
    if start is None:
        return None
    entry_bar = bars[start]
    entry = entry_bar["open"]
    if entry <= 0:
        return None
    stop, target = entry * (1 + stop_pct), entry * (1 - target_pct)
    due = add_months(entry_bar["date"], hold_months)
    for bar in bars[start:]:
        if bar["date"] >= due:
            return {"entry_date": entry_bar["date"], "entry_price": entry, "exit_date": bar["date"], "exit_price": bar["open"], "exit_reason": "one_month_open", "ambiguous_bar": False}
        hit_stop, hit_target = bar["high"] >= stop, bar["low"] <= target
        if hit_stop and hit_target:
            price, reason = (stop, "short_stop_same_day_conflict") if conflict == "stop_first" else (target, "short_target_same_day_conflict")
            return {"entry_date": entry_bar["date"], "entry_price": entry, "exit_date": bar["date"], "exit_price": price, "exit_reason": reason, "ambiguous_bar": True}
        if hit_stop:
            price = bar["open"] if bar["open"] >= stop else stop
            return {"entry_date": entry_bar["date"], "entry_price": entry, "exit_date": bar["date"], "exit_price": price, "exit_reason": "short_stop", "ambiguous_bar": False}
        if hit_target:
            price = bar["open"] if bar["open"] <= target else target
            return {"entry_date": entry_bar["date"], "entry_price": entry, "exit_date": bar["date"], "exit_price": price, "exit_reason": "short_target", "ambiguous_bar": False}
    return None


def entry_open_below_prior_sma(bars: list[dict], signal_date: date, sessions: int = 21) -> tuple[bool, float | None, date | None]:
    """Evaluate next-session entry open against prior completed-session closes.

    The entry-day close is excluded, avoiding a look-ahead bias.
    """
    entry_index = next((index for index, bar in enumerate(bars) if bar["date"] > signal_date), None)
    if entry_index is None or entry_index < sessions:
        return False, None, None if entry_index is None else bars[entry_index]["date"]
    prior_closes = [float(bar["close"]) for bar in bars[entry_index - sessions:entry_index] if bar.get("close") is not None]
    if len(prior_closes) != sessions:
        return False, None, bars[entry_index]["date"]
    sma = fmean(prior_closes)
    return bars[entry_index]["open"] < sma, sma, bars[entry_index]["date"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eligible-etfs", type=Path, required=True)
    parser.add_argument("--etf", action="append", help="Optional ETF symbol filter; repeat for a focused smoke test.")
    parser.add_argument("--holdings", type=Path, action="append", required=True, help="Repeat for normalized N-PORT holding CSVs.")
    parser.add_argument("--top-constituents", type=int, default=1, choices=range(1, 11), help="Test this many highest-weight constituents from the dated ETF snapshot.")
    parser.add_argument("--confirmation-months-before-entry", type=int, default=0, choices=range(0, 13), help="Require this many consecutive calendar months containing ETF risk-off before a later new risk-off event can enter a short; 0 disables confirmation.")
    parser.add_argument("--confirmation-mode", choices=("consecutive_months", "rolling_signals"), default="consecutive_months", help="How to interpret the confirmation window when --confirmation-months-before-entry is nonzero.")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2019, 10, 1))
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--parquet", type=Path, default=Path("data/validated/sp500/eod_adjusted_current.parquet"))
    parser.add_argument("--price-aliases", type=Path)
    parser.add_argument("--lookback", type=int, default=21)
    parser.add_argument("--min-relative-volume", type=float, default=1.25)
    parser.add_argument("--drawdown", type=float, default=0.10)
    parser.add_argument("--short-stop", type=float, default=0.10)
    parser.add_argument("--profit-target", type=float, default=0.20)
    parser.add_argument("--hold-months", type=int, default=1)
    parser.add_argument("--require-entry-below-sma-21", action="store_true", help="Enter only if next-session open is below the preceding 21 completed-session adjusted-close SMA.")
    parser.add_argument("--cost", type=float, default=0.001, help="One-way fractional transaction cost.")
    parser.add_argument("--notional-per-trade", type=float, default=1000.0, help="Fixed dollar notional used only for the reported per-trade profit/loss summary.")
    parser.add_argument("--same-day-conflict", choices=("stop_first", "target_first"), default="stop_first")
    parser.add_argument("--token-env", default="EODHD_API_TOKEN")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.start >= args.end or args.lookback < 2 or min(args.drawdown, args.short_stop, args.profit_target, args.notional_per_trade) <= 0 or args.hold_months < 1:
        parser.error("invalid date range or thresholds")
    token = os.environ.get(args.token_env)
    if not token:
        parser.error(f"set {args.token_env}; tokens are not accepted on the command line")

    args.output.mkdir(parents=True, exist_ok=True)
    weighted_snapshots = load_weighted_constituent_snapshots(args.holdings)
    price_symbol, aliases = load_price_alias_resolver(args.price_aliases)
    symbols = approved_etfs(args.eligible_etfs)
    if args.etf:
        requested = {symbol.upper() for symbol in args.etf}
        unknown = requested - set(symbols)
        if unknown:
            parser.error(f"ETF(s) are not approved in --eligible-etfs: {', '.join(sorted(unknown))}")
        symbols = [symbol for symbol in symbols if symbol in requested]
    history_start = add_months(args.start, -2)
    etf_data = {symbol: fetch(price_symbol(symbol, args.start), history_start, args.end, token, args.cache_dir) for symbol in symbols}
    spy_rows = fetch("SPY.US", history_start, args.end, token, args.cache_dir)
    spy = {row["date"]: float(row["adjusted_close"]) for row in spy_rows if row.get("adjusted_close") is not None}

    signals: list[dict] = []
    skipped: list[dict] = []
    for symbol in symbols:
        active = False
        risk_off_months: list[tuple[int, int]] = []
        risk_off_signal_dates: list[date] = []
        confirmed = args.confirmation_months_before_entry == 0
        for index, item in enumerate(etf_data[symbol]):
            observed = date.fromisoformat(item["date"])
            if not args.start <= observed <= args.end:
                continue
            risk = risk_state(etf_data[symbol], spy, index, args.lookback)
            is_risk_off = bool(risk and risk["vs_spy"] < 1 and risk["relative_volume"] >= args.min_relative_volume and risk["drawdown"] <= -args.drawdown)
            confirmation_before_today = confirmed
            if is_risk_off and args.confirmation_months_before_entry and args.confirmation_mode == "consecutive_months":
                risk_off_months = update_consecutive_risk_off_months(risk_off_months, observed)
                confirmed = len(risk_off_months) >= args.confirmation_months_before_entry
            if is_risk_off and not active:
                if args.confirmation_months_before_entry and args.confirmation_mode == "rolling_signals":
                    window_start = add_months(observed, -args.confirmation_months_before_entry)
                    risk_off_signal_dates = [item for item in risk_off_signal_dates if item >= window_start]
                    risk_off_signal_dates.append(observed)
                    confirmed = len(risk_off_signal_dates) >= args.confirmation_months_before_entry
                constituents = latest_public_constituents(weighted_snapshots.get(symbol, []), observed, args.top_constituents)
                if not confirmation_before_today:
                    observed_count = len(risk_off_months) if args.confirmation_mode == "consecutive_months" else len(risk_off_signal_dates)
                    skipped.append({"etf": symbol, "signal_date": observed.isoformat(), "reason": "awaiting_risk_off_confirmation", "confirmation_mode": args.confirmation_mode, "risk_off_confirmations_observed": observed_count, "risk_off_confirmations_required": args.confirmation_months_before_entry, **risk})
                elif constituents:
                    for constituent in constituents:
                        signals.append({"etf": symbol, "etf_price_symbol": price_symbol(symbol, observed), "signal_date": observed, "constituent": constituent["ticker"], "constituent_weight_pct": constituent["weight_pct"], "holdings_as_of": constituent["as_of_date"], "holdings_publication_date": constituent["publication_date"], "holdings_source": constituent["source"], "holdings_source_url": constituent["source_url"], **risk})
                    if args.confirmation_months_before_entry:
                        # A fresh four-month confirmation is required for every
                        # later short cycle after this qualifying re-breakdown.
                        risk_off_months = []
                        risk_off_signal_dates = []
                        confirmed = False
                else:
                    skipped.append({"etf": symbol, "signal_date": observed.isoformat(), "reason": "no_public_point_in_time_constituent_snapshot", **risk})
            active = is_risk_off

    tickers = sorted({signal["constituent"] for signal in signals})
    stock_bars: dict[str, list[dict]] = defaultdict(list)
    if tickers:
        connection = duckdb.connect(":memory:")
        try:
            marks = ",".join("?" for _ in tickers)
            query = f"""SELECT UPPER(Ticker), CAST(Date AS DATE), Open, High, Low, AdjustedClose
                         FROM read_parquet(?) WHERE UPPER(Ticker) IN ({marks})
                         AND CAST(Date AS DATE)>=? AND CAST(Date AS DATE)<=? ORDER BY 1, 2"""
            raw = connection.execute(query, [str(args.parquet), *tickers, args.start, add_months(args.end, args.hold_months + 1)]).fetchall()
        finally:
            connection.close()
        for ticker, observed, opened, high, low, adjusted_close in raw:
            if None in (opened, high, low, adjusted_close):
                continue
            stock_bars[ticker].append({"date": observed, "open": float(opened), "high": float(high), "low": float(low), "close": float(adjusted_close)})

    trades: list[dict] = []
    for signal in signals:
        bars = stock_bars.get(signal["constituent"], [])
        passes_sma, sma21, intended_entry_date = entry_open_below_prior_sma(bars, signal["signal_date"])
        if args.require_entry_below_sma_21 and not passes_sma:
            skipped.append({"etf": signal["etf"], "signal_date": signal["signal_date"].isoformat(), "constituent": signal["constituent"], "intended_entry_date": intended_entry_date.isoformat() if intended_entry_date else "", "prior_sma_21": sma21 if sma21 is not None else "", "reason": "entry_open_not_below_prior_21_session_sma"})
            continue
        result = simulate_short(bars, signal["signal_date"], args.short_stop, args.profit_target, args.hold_months, args.same_day_conflict)
        if not result:
            skipped.append({"etf": signal["etf"], "signal_date": signal["signal_date"].isoformat(), "constituent": signal["constituent"], "reason": "missing_constituent_stock_ohlc"})
            continue
        gross = result["entry_price"] / result["exit_price"] - 1
        net = (1 - args.cost) * result["entry_price"] / (result["exit_price"] * (1 + args.cost)) - 1
        trades.append({**signal, **{key: value.isoformat() if isinstance(value, date) else value for key, value in result.items()}, "entry_open_below_prior_sma_21": passes_sma, "prior_sma_21": sma21 if sma21 is not None else "", "gross_return_pct": gross, "net_return_pct": net, "notional_dollars": args.notional_per_trade, "net_profit_loss_dollars": args.notional_per_trade * net})
    trades.sort(key=lambda row: (row["signal_date"], row["etf"]))

    grouped: dict[str, list[dict]] = defaultdict(list)
    for trade in trades:
        grouped[trade["etf"]].append(trade)
    summary = []
    for symbol in symbols:
        values = grouped.get(symbol, [])
        returns = [float(row["net_return_pct"]) for row in values]
        summary.append({"etf": symbol, "trade_count": len(values), "net_total_return_pct": sum(returns), "mean_net_return_pct": fmean(returns) if returns else "", "net_profit_loss_dollars": sum(float(row["net_profit_loss_dollars"]) for row in values), "win_rate": sum(value > 0 for value in returns) / len(returns) if returns else "", "short_stop_count": sum("short_stop" in row["exit_reason"] for row in values), "short_target_count": sum("short_target" in row["exit_reason"] for row in values), "one_month_count": sum(row["exit_reason"] == "one_month_open" for row in values)})
    write(args.output / "trades.csv", trades)
    write(args.output / "etf_summary.csv", summary)
    write(args.output / "skipped_signals.csv", skipped)
    all_returns = [float(row["net_return_pct"]) for row in trades]
    profitable = sum(value > 0 for value in all_returns)
    ranked = sorted((row for row in summary if row["trade_count"]), key=lambda row: float(row["net_profit_loss_dollars"]), reverse=True)
    runtime_summary = {
        "notional_per_trade_dollars": args.notional_per_trade,
        "sum_of_individual_trade_profit_loss_dollars": sum(float(row["net_profit_loss_dollars"]) for row in trades),
        "mean_net_return_pct": fmean(all_returns) if all_returns else 0.0,
        "win_rate": profitable / len(all_returns) if all_returns else 0.0,
        "profitable_trade_count": profitable,
        "losing_trade_count": len(all_returns) - profitable,
        "short_stop_count": sum("short_stop" in row["exit_reason"] for row in trades),
        "short_target_count": sum("short_target" in row["exit_reason"] for row in trades),
        "one_month_count": sum(row["exit_reason"] == "one_month_open" for row in trades),
        "best_etfs_by_profit_loss": ranked[:5],
        "worst_etfs_by_profit_loss": list(reversed(ranked[-5:])),
    }
    payload = {"start": args.start.isoformat(), "end": args.end.isoformat(), "approved_etf_count": len(symbols), "etfs_with_holdings": len(weighted_snapshots), "signal_count": len(signals), "trade_count": len(trades), "skipped_count": len(skipped), "performance_summary": runtime_summary, "rules": {"lookback_sessions": args.lookback, "minimum_relative_volume": args.min_relative_volume, "etf_drawdown": args.drawdown, "top_constituents": args.top_constituents, "confirmation_months_before_entry": args.confirmation_months_before_entry, "confirmation_mode": args.confirmation_mode, "short_stop": args.short_stop, "profit_target": args.profit_target, "hold_months": args.hold_months, "require_entry_open_below_prior_sma_21": args.require_entry_below_sma_21, "same_day_conflict": args.same_day_conflict}, "outputs": {"trades": str(args.output / "trades.csv"), "etf_summary": str(args.output / "etf_summary.csv"), "skipped_signals": str(args.output / "skipped_signals.csv")}, "limitation": "Profit/loss is a fixed-notional sum of individual trades, not a portfolio equity curve: overlapping shorts and margin are not modelled. Constituents are the top weighted names in the latest public point-in-time N-PORT snapshot, which can be reported after the underlying holdings date. This is a research event study, not investment advice."}
    (args.output / "summary.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
