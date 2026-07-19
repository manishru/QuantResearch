#!/usr/bin/env python3
"""Point-in-time weekly breakout / Supertrend exit research backtest.

The signal is a completed-week close above the *prior* N completed weekly
highs.  A qualifying position is entered at the first available session open
of the following week.  Supertrend is evaluated only from the completed
weekly bar; a red Supertrend schedules an exit at the following week's first
available session open.  This avoids same-bar / look-ahead execution.

This is research only, not investment advice.  Results use adjusted prices,
fixed dollars per trade and no taxes, borrow, spread or market-impact model.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb

from quantresearch.features.supertrend import SupertrendConfig, compute_supertrend_features
from quantresearch.ingestion.parquet_bars import approved_provider_to_constituent
from quantresearch.ingestion.review_decisions import load_mapping_decisions
from quantresearch.simulation.models import Bar


@dataclass(frozen=True)
class DailyBar:
    observed: date
    open_price: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class WeeklyBar:
    week_end: date
    bar: Bar


def write_csv(path: Path, rows: list[dict[str, object]], headers: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def xirr(flows: list[tuple[date, float]]) -> float | None:
    if not flows or not any(amount < 0 for _, amount in flows) or not any(amount > 0 for _, amount in flows):
        return None
    origin = min(day for day, _ in flows)

    def npv(rate: float) -> float:
        return sum(amount / (1 + rate) ** ((day - origin).days / 365.2425) for day, amount in flows)

    low, high = -0.9999, 1000.0
    low_value, high_value = npv(low), npv(high)
    if low_value * high_value > 0:
        return None
    for _ in range(200):
        middle = (low + high) / 2
        value = npv(middle)
        if abs(value) < 1e-9:
            return middle
        if low_value * value <= 0:
            high = middle
        else:
            low, low_value = middle, value
    return (low + high) / 2


def in_universe(intervals: dict[str, list[tuple[date, date | None]]], ticker: str, observed: date) -> bool:
    return any(start <= observed and (end is None or observed <= end) for start, end in intervals.get(ticker, []))


def aggregate_weeks(ticker: str, bars: list[DailyBar]) -> list[WeeklyBar]:
    grouped: dict[date, list[DailyBar]] = defaultdict(list)
    for item in bars:
        grouped[item.observed - timedelta(days=item.observed.weekday())].append(item)
    output: list[WeeklyBar] = []
    for _, values in sorted(grouped.items()):
        values.sort(key=lambda item: item.observed)
        output.append(
            WeeklyBar(
                week_end=values[-1].observed,
                bar=Bar(
                    ticker=ticker,
                    date=values[-1].observed,
                    open=values[0].open_price,
                    high=max(item.high for item in values),
                    low=min(item.low for item in values),
                    close=values[-1].close,
                    volume=sum(item.volume for item in values),
                ),
            )
        )
    return output


def next_week_open(bars: list[DailyBar], completed_week_end: date) -> DailyBar | None:
    for item in bars:
        if item.observed > completed_week_end:
            return item
    return None


def simulate(
    *,
    prices: dict[str, list[DailyBar]],
    intervals: dict[str, list[tuple[date, date | None]]],
    start: date,
    end: date,
    breakout_weeks: int,
    supertrend_period: int,
    supertrend_multiplier: float,
    allocation: float,
    cost: float,
    max_open_lots_per_ticker: int,
    top_n: int,
) -> list[dict[str, object]]:
    trades: list[dict[str, object]] = []
    config = SupertrendConfig(
        periods=(supertrend_period,), multipliers=(supertrend_multiplier,), reference_pairs=()
    )
    label = format(supertrend_multiplier, "g").replace(".", "p")
    green_key = f"supertrend_green_{supertrend_period}_{label}"
    entry_candidates: dict[date, list[dict[str, object]]] = defaultdict(list)
    exit_events: dict[date, dict[str, str]] = defaultdict(dict)
    for ticker, daily in sorted(prices.items()):
        weekly = aggregate_weeks(ticker, daily)
        features = compute_supertrend_features([item.bar for item in weekly], config)
        green = {row.date: bool(row.values[green_key]) for row in features}
        for index, item in enumerate(weekly):
            if item.week_end < start or item.week_end > end:
                continue
            execution = next_week_open(daily, item.week_end)
            if execution is None or execution.observed > end:
                continue
            # A red condition is known at this completed weekly close and is
            # executable only at the following week's first market open.
            if not green.get(item.week_end, False):
                exit_events[execution.observed][ticker] = item.week_end.isoformat()
                continue
            if index < breakout_weeks:
                continue
            prior_high = max(previous.bar.high for previous in weekly[index - breakout_weeks:index])
            if item.bar.close <= prior_high:
                continue
            # Enforce point-in-time membership at both decision and execution.
            if not in_universe(intervals, ticker, item.week_end) or not in_universe(intervals, ticker, execution.observed):
                continue
            entry_candidates[execution.observed].append({
                "ticker": ticker,
                "breakout_weeks": breakout_weeks,
                "supertrend_period": supertrend_period,
                "supertrend_multiplier": supertrend_multiplier,
                "allocation": allocation,
                "signal_date": item.week_end.isoformat(),
                "breakout_level": prior_high,
                "weekly_close": item.bar.close,
                "entry_date": execution.observed.isoformat(),
                "entry_strength": item.bar.close / prior_high - 1,
            })

    # Select the strongest N breakouts across the entire index on each entry
    # date, rather than taking every stock that qualified that week.
    selected_entries = {
        observed: sorted(candidates, key=lambda candidate: (-float(candidate["entry_strength"]), str(candidate["ticker"])))[:top_n]
        for observed, candidates in entry_candidates.items()
    }
    positions: dict[str, list[dict[str, object]]] = defaultdict(list)
    event_dates = sorted(set(selected_entries) | set(exit_events))
    for observed in event_dates:
        # Exit first. Both exit and entry use this session's open, but a ticker
        # cannot be green and red on the same completed weekly bar.
        for ticker, signal_date in sorted(exit_events[observed].items()):
            opening = next((bar for bar in prices[ticker] if bar.observed == observed), None)
            if opening is None:
                continue
            for position in positions.pop(ticker, []):
                exit_price = opening.open_price * (1 - cost)
                proceeds = float(position["shares"]) * exit_price
                trades.append({
                    **position, "exit_signal_date": signal_date, "exit_date": observed.isoformat(),
                    "exit_price": exit_price, "exit_reason": "weekly_supertrend_red", "proceeds": proceeds,
                    "return_pct": proceeds / allocation - 1,
                    "holding_days": (observed - date.fromisoformat(str(position["entry_date"]))).days,
                    "status": "closed",
                })
        for candidate in selected_entries.get(observed, []):
            ticker = str(candidate["ticker"])
            if len(positions[ticker]) >= max_open_lots_per_ticker:
                continue
            opening = next((bar for bar in prices[ticker] if bar.observed == observed), None)
            if opening is None:
                continue
            entry_price = opening.open_price * (1 + cost)
            positions[ticker].append({**candidate, "entry_price": entry_price, "shares": allocation / entry_price})
    for ticker, ticker_positions in positions.items():
        last = next((item for item in reversed(prices[ticker]) if item.observed <= end), None)
        if last is None:
            continue
        for position in ticker_positions:
            proceeds = float(position["shares"]) * last.close * (1 - cost)
            trades.append({
                **position, "exit_signal_date": "", "exit_date": last.observed.isoformat(),
                "exit_price": last.close * (1 - cost), "exit_reason": "open_mark_to_market_at_end",
                "proceeds": proceeds, "return_pct": proceeds / allocation - 1,
                "holding_days": (last.observed - date.fromisoformat(str(position["entry_date"]))).days,
                "status": "open_marked",
            })
    return trades


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--breakout-weeks", type=int, action="append", default=None, help="Repeat to compare lookbacks; default: 13")
    parser.add_argument("--supertrend-period", type=int, action="append", default=None, help="Repeat to compare ATR periods; default: 10")
    parser.add_argument("--supertrend-multiplier", type=float, action="append", default=None, help="Repeat to compare multipliers; default: 3")
    parser.add_argument("--allocation", type=float, default=1_000.0, help="Fixed dollars per trade; default: 1000")
    parser.add_argument("--max-open-lots-per-ticker", type=int, default=52,
                        help="Maximum concurrently open weekly lots in one ticker; default: 52")
    parser.add_argument("--top-n", type=int, action="append", default=None,
                        help="Strongest breakouts selected across the S&P 500 each week; default: 3")
    parser.add_argument("--cost", type=float, default=0.0, help="One-way proportional execution cost; default: 0")
    parser.add_argument("--exclude-ticker", action="append", default=["CVC"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.end <= args.start:
        parser.error("--end must be after --start")
    if (args.allocation <= 0 or args.max_open_lots_per_ticker < 1
            or any(value < 1 for value in (args.top_n or [3])) or not 0 <= args.cost < 1):
        parser.error("--allocation must be positive and --cost must be in [0, 1)")
    breakouts = sorted(set(args.breakout_weeks or [13]))
    periods = sorted(set(args.supertrend_period or [10]))
    multipliers = sorted(set(args.supertrend_multiplier or [3.0]))
    top_values = sorted(set(args.top_n or [3]))
    if any(value < 2 for value in breakouts) or any(value < 1 for value in periods) or any(value <= 0 for value in multipliers):
        parser.error("breakout weeks must be >=2; Supertrend period and multiplier must be positive")

    root = args.project_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    trades_dir = output / "trades"
    trades_dir.mkdir(exist_ok=True)
    parquet = root / "data/validated/sp500/eod_adjusted_current.parquet"
    membership = root / "data/validated/sp500/eligible_membership_intervals.csv"
    mappings = root / "data/validated/sp500/mapping_decisions_operator.csv"
    if not parquet.is_file() or not membership.is_file() or not mappings.is_file():
        raise FileNotFoundError("validated prices, point-in-time membership intervals, and mappings are required")

    aliases = approved_provider_to_constituent(load_mapping_decisions(mappings).registry, "EODHD")
    history_start = args.start - timedelta(days=730)
    con = duckdb.connect(":memory:", config={"threads": "1"})
    try:
        con.execute("CREATE TABLE aliases(provider VARCHAR, constituent VARCHAR)")
        if aliases:
            con.executemany("INSERT INTO aliases VALUES (?, ?)", sorted(aliases.items()))
        exclusions = sorted({item.upper().strip() for item in args.exclude_ticker if item.strip()})
        con.execute("CREATE TABLE excluded(ticker VARCHAR)")
        if exclusions:
            con.executemany("INSERT INTO excluded VALUES (?)", [(item,) for item in exclusions])
        rows = con.execute("""
            SELECT COALESCE(a.constituent, UPPER(p.Ticker)) ticker,
                   CAST(p.Date AS DATE) observed,
                   COALESCE(p.RawOpen * p.AdjustmentFactor, p.Open) adjusted_open,
                   COALESCE(p.RawHigh * p.AdjustmentFactor, p.High) adjusted_high,
                   COALESCE(p.RawLow * p.AdjustmentFactor, p.Low) adjusted_low,
                   COALESCE(p.AdjustedClose, p.Close) adjusted_close, p.Volume
            FROM read_parquet(?) p
            LEFT JOIN aliases a ON UPPER(p.Ticker)=a.provider
            LEFT JOIN excluded e ON COALESCE(a.constituent, UPPER(p.Ticker))=e.ticker
            WHERE CAST(p.Date AS DATE) BETWEEN ? AND ? AND e.ticker IS NULL
              AND COALESCE(p.RawOpen * p.AdjustmentFactor, p.Open)>0
              AND COALESCE(p.RawHigh * p.AdjustmentFactor, p.High)>0
              AND COALESCE(p.RawLow * p.AdjustmentFactor, p.Low)>0
              AND COALESCE(p.AdjustedClose, p.Close)>0
            ORDER BY ticker, observed
        """, [str(parquet), history_start, args.end]).fetchall()
    finally:
        con.close()
    prices: dict[str, list[DailyBar]] = defaultdict(list)
    for ticker, observed, opening, high, low, close, volume in rows:
        prices[ticker].append(DailyBar(observed, opening, high, low, close, float(volume or 0)))
    intervals: dict[str, list[tuple[date, date | None]]] = defaultdict(list)
    with membership.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            end_value = row["effective_to"].strip()
            intervals[row["constituent_symbol"].upper()].append(
                (date.fromisoformat(row["effective_from"]), date.fromisoformat(end_value) if end_value else None)
            )

    summary: list[dict[str, object]] = []
    trade_headers = [
        "ticker", "breakout_weeks", "supertrend_period", "supertrend_multiplier", "allocation",
        "signal_date", "breakout_level", "weekly_close", "entry_strength", "entry_date", "entry_price", "shares",
        "exit_signal_date", "exit_date", "exit_price", "exit_reason", "proceeds", "return_pct",
        "holding_days", "status",
    ]
    for breakout in breakouts:
        for period in periods:
            for multiplier in multipliers:
                for top_n in top_values:
                    trades = simulate(prices=prices, intervals=intervals, start=args.start, end=args.end,
                                      breakout_weeks=breakout, supertrend_period=period,
                                      supertrend_multiplier=multiplier, allocation=args.allocation, cost=args.cost,
                                      max_open_lots_per_ticker=args.max_open_lots_per_ticker, top_n=top_n)
                    closed = [trade for trade in trades if trade["status"] == "closed"]
                    total_invested = args.allocation * len(trades)
                    proceeds = sum(float(trade["proceeds"]) for trade in trades)
                    flows = [(date.fromisoformat(str(trade["entry_date"])), -args.allocation) for trade in trades]
                    flows.extend((date.fromisoformat(str(trade["exit_date"])), float(trade["proceeds"])) for trade in trades)
                    returns = [float(trade["return_pct"]) for trade in trades]
                    rule_name = f"breakout_{breakout}w_supertrend_{period}_{format(multiplier, 'g')}_top{top_n}"
                    write_csv(trades_dir / f"{rule_name}_trades.csv", trades, trade_headers)
                    summary.append({
                    "strategy_rule": rule_name, "breakout_weeks": breakout,
                    "supertrend_period": period, "supertrend_multiplier": multiplier,
                    "top_n": top_n,
                    "trade_count": len(trades), "closed_trade_count": len(closed),
                    "open_marked_count": len(trades) - len(closed), "invested_capital": total_invested,
                    "net_proceeds": proceeds, "net_profit": proceeds - total_invested,
                    "roi": proceeds / total_invested - 1 if total_invested else None,
                    "xirr": xirr(flows), "average_trade_return": sum(returns) / len(returns) if returns else None,
                    "median_trade_return": sorted(returns)[len(returns)//2] if returns else None,
                    "win_rate": sum(value > 0 for value in returns) / len(returns) if returns else None,
                    "cost_per_side": args.cost,
                    "trades_file": str((trades_dir / f"{rule_name}_trades.csv").relative_to(output)),
                    })
    summary.sort(key=lambda item: (item["xirr"] is not None, item["xirr"] or -9999), reverse=True)
    write_csv(output / "comparison.csv", summary, list(summary[0]) if summary else ["strategy_rule"])
    print(json.dumps({
        "output": str(output), "comparison": str(output / "comparison.csv"),
        "definition": "close above prior N completed weekly highs; next-week-open entry; weekly Supertrend red -> next-week-open exit",
        "universe": "point-in-time S&P 500 membership", "price_basis": "split/dividend-adjusted OHLC",
        "best": summary[0] if summary else None,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
