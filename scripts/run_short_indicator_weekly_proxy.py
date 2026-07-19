#!/usr/bin/env python3
"""Research-only, fixed-contribution short-sale proxy across four signal families.

All eligible stocks are *assumed* borrowable.  The model charges a configurable
annual borrow fee but does not model dividend liabilities, hard-to-borrow/locate
fees, margin, recalls, availability, slippage, or taxes.  It is not a trading
recommendation or order-submission tool.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import duckdb

from quantresearch.research.monthly_momentum_lots import scheduled_calendar_date
from quantresearch.research.short_proxy import (
    ShortBar, apply_asymmetric_pnl_haircut, select_short_exit,
    select_short_target_exit, short_net_return,
)


SIGNALS = (
    "rsi_bollinger_mean_reversion",
    "breakdown_relative_volume",
    "moving_average_trend_failure",
    "spike_volume_reversal_exhaustion",
)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def xirr(flows: list[tuple[date, float]]) -> float | None:
    if not flows or not any(v < 0 for _, v in flows) or not any(v > 0 for _, v in flows):
        return None
    origin = min(day for day, _ in flows)
    def npv(rate: float) -> float:
        return sum(value / (1 + rate) ** ((day - origin).days / 365.2425) for day, value in flows)
    low, high = -0.9999, 1000.0
    low_value, high_value = npv(low), npv(high)
    if low_value * high_value > 0:
        return None
    for _ in range(200):
        middle = (low + high) / 2
        value = npv(middle)
        if abs(value) < 1e-8:
            return middle
        if low_value * value <= 0:
            high = middle
        else:
            low, low_value = middle, value
    return (low + high) / 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--holding-weeks", type=int, action="append", choices=(1, 2), default=[])
    parser.add_argument("--daily-entry", action="store_true", help="Enter from every completed daily signal; requires --reward-multiple")
    parser.add_argument("--reward-multiple", type=float, action="append", choices=(1.0, 2.0, 3.0), default=[])
    parser.add_argument("--pnl-gain-keep", type=float, default=.90)
    parser.add_argument("--pnl-loss-multiplier", type=float, default=1.10)
    parser.add_argument("--signal", action="append", choices=SIGNALS, default=[])
    parser.add_argument("--stop", type=float, action="append", default=[])
    parser.add_argument("--top-n", type=int, action="append", choices=range(1, 6), default=[])
    parser.add_argument("--weekday", type=int, action="append", choices=range(5), default=[])
    parser.add_argument("--weekday-budget", type=float, default=1_000.0)
    parser.add_argument("--borrow-rate", type=float, default=.03)
    parser.add_argument("--cost", type=float, default=.001)
    parser.add_argument("--max-volatility", type=float, default=-1.0)
    parser.add_argument("--exclude-ticker", action="append", default=["CVC"])
    args = parser.parse_args()
    if args.end <= args.start:
        parser.error("--end must be after --start")
    if args.weekday_budget <= 0 or not 0 <= args.borrow_rate < 1 or not 0 <= args.cost < 1:
        parser.error("budget must be positive; borrow rate and cost must be in [0, 1)")
    if args.daily_entry and args.holding_weeks:
        parser.error("--daily-entry cannot be combined with --holding-weeks")
    if args.daily_entry and not args.reward_multiple:
        parser.error("--daily-entry requires one or more --reward-multiple values")
    if not 0 <= args.pnl_gain_keep <= 1 or args.pnl_loss_multiplier < 1:
        parser.error("invalid P&L haircut values")
    holds, signals = sorted(set(args.holding_weeks or [1, 2])), args.signal or list(SIGNALS)
    rewards = sorted(set(args.reward_multiple))
    stops, tops, weekdays = sorted(set(args.stop or [.05, .08, .10, .12, .15])), sorted(set(args.top_n or [1, 2, 3])), sorted(set(args.weekday or range(5)))
    if any(not 0 < stop < 1 for stop in stops):
        parser.error("each --stop must be between zero and one")
    root, output = args.project_root.expanduser().resolve(), args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    parquet = root / "data/validated/sp500/eod_adjusted_current.parquet"
    intervals = root / "data/validated/sp500/eligible_membership_intervals.csv"
    if not parquet.is_file() or not intervals.is_file():
        raise FileNotFoundError("validated prices and eligible membership intervals are required")

    scheduled = []
    cursor = args.start
    while cursor <= args.end:
        if cursor.weekday() in weekdays:
            scheduled.append((cursor.weekday(), cursor))
        cursor += timedelta(days=1)
    con = duckdb.connect(":memory:", config={"threads": "1"})
    try:
        con.execute("CREATE TABLE schedules(weekday INTEGER, target DATE)")
        con.executemany("INSERT INTO schedules VALUES (?, ?)", scheduled)
        con.execute("CREATE TABLE excluded(ticker VARCHAR)")
        con.executemany("INSERT INTO excluded VALUES (?)", [(item.upper(),) for item in args.exclude_ticker])
        con.execute("""CREATE TABLE prices AS
          SELECT UPPER(Ticker) ticker, CAST(Date AS DATE) observed, Open open_price,
                 Close close_price, Volume volume
          FROM read_parquet(?)
          WHERE CAST(Date AS DATE) BETWEEN ? AND ? AND Open > 0 AND Close > 0 AND Volume >= 0""",
                    [str(parquet), args.start - timedelta(days=180), args.end])
        con.execute("""CREATE TABLE calendar AS SELECT observed,
          LAG(observed) OVER (ORDER BY observed) signal_date
          FROM (SELECT observed FROM prices GROUP BY observed HAVING COUNT(*) >= 100)""")
        con.execute("""CREATE TABLE quarantined_tickers AS
          WITH changes AS (
            SELECT ticker, close_price,
              LAG(close_price) OVER (PARTITION BY ticker ORDER BY observed) prior_close
            FROM prices
          )
          SELECT DISTINCT ticker FROM changes
          WHERE prior_close > 0
            AND GREATEST(close_price/prior_close, prior_close/close_price) > 5""")
        con.execute("""CREATE TABLE features AS
          WITH daily AS (
            SELECT *, close_price / LAG(close_price) OVER (PARTITION BY ticker ORDER BY observed) - 1 daily_return,
              GREATEST(close_price - LAG(close_price) OVER (PARTITION BY ticker ORDER BY observed), 0) gain,
              GREATEST(LAG(close_price) OVER (PARTITION BY ticker ORDER BY observed) - close_price, 0) loss
            FROM prices
          ) SELECT *,
            AVG(close_price) OVER w20 ma20, AVG(close_price) OVER w50 ma50,
            STDDEV_SAMP(close_price) OVER w20 sd20,
            MIN(close_price) OVER (PARTITION BY ticker ORDER BY observed ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) prior_low20,
            AVG(volume) OVER (PARTITION BY ticker ORDER BY observed ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) prior_volume20,
            STDDEV_SAMP(daily_return) OVER w21 volatility_1m,
            AVG(gain) OVER w2 / NULLIF(AVG(loss) OVER w2, 0) rsi2_ratio,
            AVG(gain) OVER w5 / NULLIF(AVG(loss) OVER w5, 0) rsi5_ratio
          FROM daily
          WINDOW w2 AS (PARTITION BY ticker ORDER BY observed ROWS BETWEEN 1 PRECEDING AND CURRENT ROW),
                 w5 AS (PARTITION BY ticker ORDER BY observed ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
                 w20 AS (PARTITION BY ticker ORDER BY observed ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
                 w21 AS (PARTITION BY ticker ORDER BY observed ROWS BETWEEN 20 PRECEDING AND CURRENT ROW),
                 w50 AS (PARTITION BY ticker ORDER BY observed ROWS BETWEEN 49 PRECEDING AND CURRENT ROW)""")
        con.execute("""CREATE TABLE candidates AS
          WITH base AS (
            SELECT e.weekday, e.target, e.execution_date, c.signal_date, f.*, p.open_price execution_open_price,
              CASE
                WHEN 100 - 100/(1 + f.rsi2_ratio) >= 90 AND f.close_price > f.ma20 + 2*f.sd20 THEN 'rsi_bollinger_mean_reversion'
                WHEN f.close_price < f.prior_low20 AND f.volume >= 1.5*f.prior_volume20 THEN 'breakdown_relative_volume'
                WHEN f.close_price < f.ma20 AND f.ma20 < f.ma50 THEN 'moving_average_trend_failure'
                WHEN f.daily_return >= .08 AND f.volume >= 2*f.prior_volume20 AND f.close_price < f.open_price THEN 'spike_volume_reversal_exhaustion'
              END signal
            FROM (SELECT s.*, MIN(c.observed) execution_date FROM schedules s JOIN calendar c ON c.observed >= s.target GROUP BY ALL) e
            JOIN calendar c ON c.observed=e.execution_date
            JOIN features f ON f.observed=c.signal_date
            -- Signals are formed from the completed prior close.  The entry
            -- must be the later execution session's open, never the signal
            -- session's open (which would be look-ahead execution).
            JOIN prices p ON p.ticker=f.ticker AND p.observed=e.execution_date
            JOIN read_csv_auto(?, header=true) i ON UPPER(i.constituent_symbol)=f.ticker
              AND c.signal_date >= CAST(i.effective_from AS DATE)
              AND (i.effective_to IS NULL OR CAST(i.effective_to AS VARCHAR)='' OR c.signal_date <= CAST(i.effective_to AS DATE))
            WHERE c.signal_date >= CAST(i.effective_from AS DATE) + INTERVAL 60 DAY
              AND NOT EXISTS (SELECT 1 FROM excluded x WHERE x.ticker=f.ticker)
              AND NOT EXISTS (SELECT 1 FROM quarantined_tickers x WHERE x.ticker=f.ticker)
              AND (? < 0 OR f.volatility_1m <= ?)
          ), ranked AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY weekday, execution_date, signal ORDER BY
              CASE WHEN signal='rsi_bollinger_mean_reversion' THEN rsi2_ratio
                   WHEN signal='breakdown_relative_volume' THEN volume/NULLIF(prior_volume20,0)
                   WHEN signal='moving_average_trend_failure' THEN ma50/NULLIF(close_price,0)
                   ELSE daily_return*volume/NULLIF(prior_volume20,0) END DESC, ticker) signal_rank,
              COUNT(*) OVER (PARTITION BY weekday, execution_date, signal) candidate_count
            FROM base WHERE signal IS NOT NULL
          ) SELECT * FROM ranked WHERE signal_rank <= 5""", [str(intervals), args.max_volatility, args.max_volatility])
        columns = [item[0] for item in con.execute("SELECT * FROM candidates LIMIT 0").description]
        candidates = [dict(zip(columns, row)) for row in con.execute("SELECT * FROM candidates WHERE signal IN (" + ", ".join("?" for _ in signals) + ") ORDER BY execution_date, signal, signal_rank, ticker", signals).fetchall()]
        price_rows = con.execute("SELECT ticker, observed, open_price, close_price FROM prices ORDER BY ticker, observed").fetchall()
    finally:
        con.close()
    series: dict[str, list[ShortBar]] = defaultdict(list)
    for ticker, observed, open_price, close_price in price_rows:
        series[ticker].append(ShortBar(observed, float(open_price), float(close_price)))
    by_configuration: dict[tuple, list[dict[str, object]]] = defaultdict(list)
    candidates = list({(c["execution_date"], c["ticker"], c["signal"]): c for c in candidates}.values()) if args.daily_entry else candidates
    for hold in ([None] if args.daily_entry else holds):
        for stop in stops:
            for top_n in tops:
                for reward in (rewards if args.daily_entry else [None]):
                  for candidate in candidates:
                    if int(candidate["signal_rank"]) > top_n:
                        continue
                    allocation = args.weekday_budget / min(top_n, int(candidate["candidate_count"]))
                    entry = float(candidate["execution_open_price"])
                    bars = [bar for bar in series[candidate["ticker"]] if bar.observed >= candidate["execution_date"]]
                    exit_ = (select_short_target_exit(entry, bars, stop, reward)
                             if args.daily_entry else select_short_exit(entry, bars, candidate["execution_date"] + timedelta(days=hold * 7), stop))
                    if exit_ is None or exit_.observed > args.end:
                        continue
                    days = (exit_.observed - candidate["execution_date"]).days
                    gross_return = entry / exit_.price - 1
                    raw_pnl = allocation * (gross_return - 2 * args.cost)
                    adjusted_pnl = (apply_asymmetric_pnl_haircut(raw_pnl, args.pnl_gain_keep, args.pnl_loss_multiplier)
                                    if args.daily_entry else allocation * short_net_return(entry, exit_.price, days, args.borrow_rate, args.cost))
                    net_return = adjusted_pnl / allocation
                    row = {"signal": candidate["signal"], "weekday": ("Any" if args.daily_entry else WEEKDAYS[int(candidate["weekday"])]), "holding_weeks": hold, "reward_multiple": reward, "stop": stop, "top_n": top_n,
                           "signal_date": candidate["signal_date"], "execution_date": candidate["execution_date"], "ticker": candidate["ticker"], "entry_price": entry,
                           "cover_date": exit_.observed, "cover_price": exit_.price, "exit_reason": exit_.reason, "holding_days": days, "allocation": allocation,
                           "gross_short_return": gross_return, "borrow_fee": (0 if args.daily_entry else args.borrow_rate * days / 365.2425), "transaction_cost": 2 * args.cost,
                           "net_return": net_return, "net_proceeds": allocation + adjusted_pnl}
                    by_configuration[(candidate["signal"], (None if args.daily_entry else int(candidate["weekday"])), hold, reward, stop, top_n)].append(row)
    all_trades, summaries = [], []
    for key, rows in by_configuration.items():
        signal, weekday, hold, reward, stop, top_n = key
        invested, proceeds = sum(float(row["allocation"]) for row in rows), sum(float(row["net_proceeds"]) for row in rows)
        flows = [(row["execution_date"], -float(row["allocation"])) for row in rows] + [(row["cover_date"], float(row["net_proceeds"])) for row in rows]
        summary = {"signal": signal, "weekday": ("Any" if weekday is None else WEEKDAYS[weekday]), "holding_weeks": hold, "reward_multiple": reward, "stop": stop, "top_n": top_n, "trade_count": len(rows),
                   "invested_capital": invested, "net_proceeds": proceeds, "net_profit": proceeds-invested, "roi": (proceeds/invested-1) if invested else None,
                   "xirr": xirr(flows), "win_rate": sum(float(row["net_return"]) > 0 for row in rows)/len(rows),
                   "stop_rate": sum(row["exit_reason"] == "stop_close_next_open" for row in rows)/len(rows),
                   "borrow_rate": (0 if args.daily_entry else args.borrow_rate), "transaction_cost_per_side": args.cost,
                   "model_limitations": "assumed_borrowable; dividends, locate/hard-to-borrow fees, margin, recalls and availability excluded"}
        summaries.append(summary)
        all_trades.extend(rows)
    summaries.sort(key=lambda row: (-(row["xirr"] if row["xirr"] is not None else -999), -row["roi"]))
    for rank, row in enumerate(summaries, 1): row["rank"] = rank
    write_csv(output / "configuration_summary.csv", summaries)
    write_csv(output / "all_short_trades.csv", all_trades)
    run = {"output": str(output), "signals": signals, "daily_entry": args.daily_entry, "holding_weeks": ([] if args.daily_entry else holds), "reward_multiples": rewards, "weekday_budget": args.weekday_budget,
           "borrow_rate": (0 if args.daily_entry else args.borrow_rate), "cost": args.cost, "pnl_gain_keep": args.pnl_gain_keep, "pnl_loss_multiplier": args.pnl_loss_multiplier, "research_only": True,
           "limitations": "Assumes borrow availability. Dividend liabilities, borrow availability/recalls, hard-to-borrow and locate fees, margin and taxes are excluded.",
           "best": summaries[0] if summaries else None}
    (output / "run.json").write_text(json.dumps(run, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(run, indent=2, default=str))


if __name__ == "__main__":
    main()
