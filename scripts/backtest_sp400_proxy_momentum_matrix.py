#!/usr/bin/env python3
"""Backtest a fixed-monthly S&P 400 proxy momentum matrix from merged EODHD data.

This is deliberately separate from the S&P 500 Golden implementation.  It uses
the approximate Wikipedia membership intervals, adjusted EODHD prices for all
return/stop arithmetic, and no future data for a signal.  Results are research
outputs only; the membership history is a selected-change Wikipedia proxy.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import duckdb


# Kept aligned with the established monthly-momentum rule catalog.  Expressions
# are evaluated only against returns known at the completed signal close.
RULES = {
    "1M>0": "ret21 > 0",
    "12M>9M>6M>3M>0": "ret252 > ret189 and ret189 > ret126 and ret126 > ret63 and ret63 > 0",
    "12M>6M>3M>0": "ret252 > ret126 and ret126 > ret63 and ret63 > 0",
    "12M>9M>6M>3M>0 & 2M>0": "ret252 > ret189 and ret189 > ret126 and ret126 > ret63 and ret63 > 0 and ret42 > 0",
    "9M>6M>3M>0 & 2M>0": "ret189 > ret126 and ret126 > ret63 and ret63 > 0 and ret42 > 0",
    "6M>3M>0 & 2M>0": "ret126 > ret63 and ret63 > 0 and ret42 > 0",
    "5M>2M>0": "ret105 > ret42 and ret42 > 0", "5M>3M>0": "ret105 > ret63 and ret63 > 0",
    "6M>3M>0": "ret126 > ret63 and ret63 > 0", "9M>6M>3M>0": "ret189 > ret126 and ret126 > ret63 and ret63 > 0",
    "9M>5M>0": "ret189 > ret105 and ret105 > 0", "10M>6M>3M>0": "ret210 > ret126 and ret126 > ret63 and ret63 > 0",
    "11M>6M>3M>0": "ret231 > ret126 and ret126 > ret63 and ret63 > 0", "6M>4M>0": "ret126 > ret84 and ret84 > 0",
    "4M>2M>0": "ret84 > ret42 and ret42 > 0", "3M>2M>0": "ret63 > ret42 and ret42 > 0",
    "7M>4M>0": "ret147 > ret84 and ret84 > 0", "8M>5M>0": "ret168 > ret105 and ret105 > 0",
    "9M>6M>0": "ret189 > ret126 and ret126 > 0",
}


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def xirr(cashflows: list[tuple[date, float]]) -> float | None:
    if not cashflows or not any(v < 0 for _, v in cashflows) or not any(v > 0 for _, v in cashflows):
        return None
    origin = min(day for day, _ in cashflows)
    def npv(rate: float) -> float:
        return sum(value / (1 + rate) ** ((day - origin).days / 365.2425) for day, value in cashflows)
    low, high = -0.9999, 1_000.0
    f_low, f_high = npv(low), npv(high)
    if f_low * f_high > 0: return None
    for _ in range(160):
        mid = (low + high) / 2; f_mid = npv(mid)
        if abs(f_mid) < 1e-8: return mid
        if f_low * f_mid <= 0: high = mid
        else: low, f_low = mid, f_mid
    return (low + high) / 2


def scheduled_sessions(sessions: list[date], start: date, end: date, day: int) -> list[tuple[date, date]]:
    result: list[tuple[date, date]] = []
    month = date(start.year, start.month, 1)
    while month <= end:
        next_month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        # Calendar day 31 means the final calendar day for short months.
        target = date(month.year, month.month, min(day, (next_month - timedelta(days=1)).day))
        # Execute on the first available session *on or after* the nominated
        # calendar day. The signal uses the immediately preceding completed
        # session. This never enters before the user-selected calendar day.
        index = bisect.bisect_left(sessions, target)
        if index > 0 and index < len(sessions) and sessions[index] <= end:
            result.append((sessions[index - 1], sessions[index]))
        month = next_month
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/validated/sp400/eodhd_sp400_proxy_eod.duckdb"))
    parser.add_argument("--membership", type=Path, default=Path("reports/sp400_wikipedia_reverse_membership_2016_2026/membership_intervals.csv"))
    parser.add_argument("--start", type=date.fromisoformat, default=date(2016, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--days", default="1-31", help="Calendar entry days, e.g. 26 or 1-31 or 5,17,26")
    parser.add_argument("--holding-weeks", default="4,6,8,12,16,20,24,28,32,36,40,44,48,52")
    parser.add_argument("--stops", default="0.20,0.25,0.30")
    parser.add_argument("--top-n-values", default="1,2,3,4,5")
    parser.add_argument("--rule", action="append", choices=sorted(RULES), help="Repeat to restrict rules; default is every catalog rule")
    parser.add_argument("--ranking-metric", choices=("rule_lead", "1m", "12m"), default="rule_lead", help="Rank qualifying candidates; rule_lead uses each rule's longest/left-most horizon.")
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--monthly-budget", type=float, default=1000.0)
    parser.add_argument("--cost", type=float, default=.001)
    parser.add_argument("--corporate-action-exits", type=Path, default=Path("config/experiments/sp400_proxy_corporate_action_exits.csv"))
    parser.add_argument("--write-trades", action="store_true", help="Write all configuration trades (large); matrix summary is always written.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.database.is_file() or not args.membership.is_file():
        raise FileNotFoundError("database or membership file is missing")
    if args.monthly_budget <= 0 or not 0 <= args.cost < 1: parser.error("invalid budget or cost")
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count: parser.error("invalid shard index")
    def parse_days(value: str) -> list[int]:
        out: set[int] = set()
        for part in value.split(","):
            if "-" in part:
                left, right = map(int, part.split("-", 1)); out.update(range(left, right + 1))
            else: out.add(int(part))
        if not out or min(out) < 1 or max(out) > 31: raise ValueError("days must be within 1..31")
        return sorted(out)
    days = parse_days(args.days)
    holds = [int(x) for x in args.holding_weeks.split(",")]
    stops = [float(x) for x in args.stops.split(",")]
    top_n_values = [int(x) for x in args.top_n_values.split(",")]
    active_rules = [name for i, name in enumerate(args.rule or sorted(RULES)) if i % args.shard_count == args.shard_index]
    if any(h < 1 for h in holds) or any(not 0 < s < 1 for s in stops) or any(n < 1 for n in top_n_values): parser.error("invalid holding weeks, stops, or top-n values")
    output = args.output.expanduser().resolve(); output.mkdir(parents=True, exist_ok=True)
    history_start = args.start - timedelta(days=430)
    con = duckdb.connect(str(args.database), read_only=True)
    try:
        price_rows = con.execute("""SELECT ticker, observed, open, close, adjusted_close
            FROM sp400_proxy_prices WHERE observed BETWEEN ? AND ?
            AND open>0 AND close>0 AND adjusted_close>0 ORDER BY ticker, observed""", [history_start, args.end]).fetchall()
    finally: con.close()
    intervals: dict[str, list[tuple[date, date]]] = defaultdict(list)
    with args.membership.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            intervals[row["ticker"].upper()].append((date.fromisoformat(row["effective_from"]), date.fromisoformat(row["effective_to"])))
    action_exits: dict[str, tuple[date, float]] = {}
    if args.corporate_action_exits.is_file():
        with args.corporate_action_exits.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                action_exits[row["ticker"].upper()] = (date.fromisoformat(row["effective_date"]), float(row["cash_exit_price"]))
    by_ticker: dict[str, tuple[list[date], list[float], list[float]]] = {}
    all_sessions: set[date] = set()
    raw: dict[str, list[tuple[date, float, float]]] = defaultdict(list)
    for ticker, observed, open_price, close_price, adjusted_close in price_rows:
        factor = float(adjusted_close) / float(close_price)
        raw[ticker].append((observed, float(open_price) * factor, float(adjusted_close)))
        if observed >= args.start: all_sessions.add(observed)
    for ticker, values in raw.items():
        by_ticker[ticker] = ([x[0] for x in values], [x[1] for x in values], [x[2] for x in values])
    sessions = sorted(all_sessions)
    def active(ticker: str, signal: date, entry: date) -> bool:
        return any(left <= signal <= right and left <= entry <= right for left, right in intervals.get(ticker, []))
    schedules = {day: scheduled_sessions(sessions, args.start, args.end, day) for day in days}
    # Candidate selection is invariant across stop/holding variants, so calculate once.
    candidates: dict[tuple[str, int, date], list[tuple[str, float, int]]] = {}
    max_top_n = max(top_n_values)
    for rule_name in active_rules:
      for day, schedule in schedules.items():
        for signal, entry in schedule:
            ranked: list[tuple[float, str, int]] = []
            for ticker, (ticker_days, ticker_opens, ticker_closes) in by_ticker.items():
                index = bisect.bisect_left(ticker_days, signal)
                entry_index = bisect.bisect_left(ticker_days, entry)
                if (index >= len(ticker_days) or ticker_days[index] != signal or index < 105
                        or entry_index >= len(ticker_days) or ticker_days[entry_index] != entry
                        or not active(ticker, signal, entry)):
                    continue
                returns = {f"ret{sessions_back}": ticker_closes[index] / ticker_closes[index - sessions_back] - 1 if index >= sessions_back else None for sessions_back in (21, 42, 63, 84, 105, 126, 147, 168, 189, 210, 231, 252)}
                needed = set(re.findall(r"ret\d+", RULES[rule_name]))
                rank_key = (f"ret{max(int(name[3:]) for name in needed)}" if args.ranking_metric == "rule_lead"
                            else "ret21" if args.ranking_metric == "1m" else "ret252")
                if all(returns[name] is not None for name in needed | {rank_key}) and eval(RULES[rule_name], {"__builtins__": {}}, returns):
                    ranked.append((returns[rank_key], ticker, entry_index))
            ranked.sort(key=lambda x: (-x[0], x[1]))
            candidates[(rule_name, day, entry)] = [(ticker, ret12, index) for ret12, ticker, index in ranked[:max_top_n]]
    def outcome(ticker: str, entry_index: int, weeks: int, stop: float) -> tuple[date, float, str]:
        ticker_days, ticker_opens, ticker_closes = by_ticker[ticker]
        entry_price = ticker_opens[entry_index] * (1 + args.cost)
        target = ticker_days[entry_index] + timedelta(days=weeks * 7)
        maturity_signal = bisect.bisect_left(ticker_days, target)
        last = bisect.bisect_right(ticker_days, args.end) - 1
        end_signal = min(maturity_signal, last)
        for i in range(entry_index, end_signal + 1):
            if ticker_closes[i] <= entry_price * (1 - stop):
                exit_i = min(i + 1, last)
                return ticker_days[exit_i], ticker_opens[exit_i] * (1 - args.cost), "stop_close_next_open"
        if maturity_signal <= last:
            exit_i = min(maturity_signal + 1, last)
            return ticker_days[exit_i], ticker_opens[exit_i] * (1 - args.cost), "scheduled_maturity"
        action = action_exits.get(ticker)
        # A corporate-action settlement supersedes a missing price history.
        # Providers sometimes retain one or more stale post-close rows, so do
        # not require the action date to be after the final observed row.
        if action and ticker_days[entry_index] <= action[0] <= args.end:
            return action[0], action[1] * (1 - args.cost), "corporate_action_cash_exit"
        return ticker_days[last], ticker_closes[last] * (1 - args.cost), "open_mtm"
    metrics: list[dict[str, object]] = []
    trade_handle = (output / "all_trades.csv").open("w", newline="", encoding="utf-8") if args.write_trades else None
    trade_writer: csv.DictWriter | None = None
    outcomes_cache: dict[tuple[str, int, int, float], tuple[date, float, str]] = {}
    for rule_name in active_rules:
     for day in days:
        planned = len(schedules[day])
        for weeks in holds:
            for stop in stops:
             for top_n in top_n_values:
                trades: list[dict[str, object]] = []
                for signal, entry in schedules[day]:
                    selected = candidates[(rule_name, day, entry)][:top_n]
                    allocation = args.monthly_budget / len(selected) if selected else 0
                    for rank, (ticker, ret12, entry_index) in enumerate(selected, 1):
                        key = (ticker, entry_index, weeks, stop)
                        exit_day, exit_price, reason = outcomes_cache.setdefault(key, outcome(ticker, entry_index, weeks, stop))
                        entry_price = by_ticker[ticker][1][entry_index] * (1 + args.cost)
                        proceeds = allocation * exit_price / entry_price
                        trades.append({"nominal_day": day, "holding_weeks": weeks, "stop": stop, "signal_date": signal, "entry_date": entry, "ticker": ticker, "rank": rank, "ranking_return_12m": ret12, "allocation": allocation, "entry_price_adjusted": entry_price, "exit_date": exit_day, "exit_price_adjusted": exit_price, "exit_reason": reason, "proceeds": proceeds, "net_return": proceeds / allocation - 1})
                contributions = sum(float(t["allocation"]) for t in trades); final = sum(float(t["proceeds"]) for t in trades)
                returns = [float(t["net_return"]) for t in trades]
                # This discovery sweep has 108,810 configurations.  Exact
                # cashflow IRR is intentionally deferred to the selected five
                # finalists; it does not affect equal-weight ROI ranking.
                leading_horizon = max(int(name[3:]) for name in set(re.findall(r"ret\d+", RULES[rule_name])))
                metrics.append({"rule": rule_name, "ranking_metric": f"{leading_horizon // 21}M_rule_lead" if args.ranking_metric == "rule_lead" else args.ranking_metric.upper(), "nominal_day": day, "holding_weeks": weeks, "stop": stop, "top_n": top_n, "scheduled_months": planned, "deployed_months": len({t["entry_date"] for t in trades}), "trade_count": len(trades), "total_contributions": contributions, "final_value": final, "net_profit": final - contributions, "roi": final / contributions - 1 if contributions else None, "xirr": None, "mean_trade_return": sum(returns) / len(returns) if returns else None, "win_rate": sum(x > 0 for x in returns) / len(trades) if trades else None, "stop_rate": sum(t["exit_reason"] == "stop_close_next_open" for t in trades) / len(trades) if trades else None, "open_mtm_count": sum(t["exit_reason"] == "open_mtm" for t in trades)})
                if trade_handle:
                    if trade_writer is None:
                        trade_writer = csv.DictWriter(trade_handle, fieldnames=list(trades[0]) if trades else ["nominal_day"], extrasaction="ignore")
                        trade_writer.writeheader()
                    trade_writer.writerows(trades)
    if trade_handle: trade_handle.close()
    metrics.sort(key=lambda row: -(row["roi"] or -999))
    fields = list(metrics[0]) if metrics else []
    write_csv(output / "matrix_summary.csv", metrics, fields)
    summary = {"configurations": len(metrics), "rules": active_rules, "days": days, "holding_weeks": holds, "stops": stops, "top_n_values": top_n_values, "shard": f"{args.shard_index}/{args.shard_count}", "price_symbols": len(by_ticker), "complete_membership_proxy": "Wikipedia selected-change reverse proxy", "matrix": str(output / "matrix_summary.csv"), "trades": str(output / "all_trades.csv") if args.write_trades else None, "limitation": "Research only. This uses approximate historical membership and adjusted daily EOD prices; it models close-confirmed stops exited at the next session open, not intraday stop fills."}
    (output / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__": main()
