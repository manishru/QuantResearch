#!/usr/bin/env python3
"""Run the point-in-time monthly momentum-lot experiment matrix."""

from __future__ import annotations

import argparse
import calendar
import csv
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import duckdb

from quantresearch.ingestion.parquet_bars import approved_provider_to_constituent
from quantresearch.ingestion.review_decisions import load_mapping_decisions
from quantresearch.research.monthly_momentum_lots import scheduled_calendar_date

RULES = {
    "12M>9M>6M>3M>0": (
        "ret252 > ret189 AND ret189 > ret126 AND ret126 > ret63 AND ret63 > 0"
    ),
    "12M>6M>3M>0": "ret252 > ret126 AND ret126 > ret63 AND ret63 > 0",
    "12M>9M>6M>3M>0 & 2M>0": (
        "ret252 > ret189 AND ret189 > ret126 AND ret126 > ret63 "
        "AND ret63 > 0 AND ret42 > 0"
    ),
    "9M>6M>3M>0 & 2M>0": (
        "ret189 > ret126 AND ret126 > ret63 AND ret63 > 0 AND ret42 > 0"
    ),
    "6M>3M>0 & 2M>0": "ret126 > ret63 AND ret63 > 0 AND ret42 > 0",
    "5M>2M>0": "ret105 > ret42 AND ret42 > 0",
    "5M>3M>0": "ret105 > ret63 AND ret63 > 0",
    "6M>4M>0": "ret126 > ret84 AND ret84 > 0",
    "4M>2M>0": "ret84 > ret42 AND ret42 > 0",
    "3M>2M>0": "ret63 > ret42 AND ret42 > 0",
    "7M>4M>0": "ret147 > ret84 AND ret84 > 0",
    "8M>5M>0": "ret168 > ret105 AND ret105 > 0",
    "9M>6M>0": "ret189 > ret126 AND ret126 > 0",
}


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _xirr(cashflows: list[tuple[date, float]]) -> float | None:
    if (
        not cashflows
        or not any(v < 0 for _, v in cashflows)
        or not any(v > 0 for _, v in cashflows)
    ):
        return None
    origin = min(d for d, _ in cashflows)

    def npv(rate: float) -> float:
        return sum(v / (1 + rate) ** ((d - origin).days / 365.2425) for d, v in cashflows)

    low, high = -0.9999, 1000.0
    f_low, f_high = npv(low), npv(high)
    if f_low * f_high > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            return mid
        if f_low * f_mid <= 0:
            high = mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--parquet",
        type=Path,
        help="Validated adjusted Parquet; defaults to the current validated artifact when present",
    )
    parser.add_argument("--start", type=date.fromisoformat, default=date(2016, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 7, 10))
    parser.add_argument("--monthly-budget", type=float, default=10_000.0)
    parser.add_argument(
        "--nominal-day",
        type=int,
        action="append",
        choices=range(1, 32),
        help="Evaluate only this calendar day of each month; repeat to select multiple days",
    )
    parser.add_argument(
        "--entry-weekday",
        type=int,
        action="append",
        choices=range(5),
        help="Use weekly entries on weekday 0=Monday through 4=Friday; repeat to test several weekdays",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        action="append",
        choices=range(1, 6),
        help="Evaluate only this number of top-ranked stocks; repeat to select multiple values",
    )
    holding_period = parser.add_mutually_exclusive_group()
    holding_period.add_argument(
        "--holding-months",
        type=int,
        default=None,
        help="Scheduled holding period in monthly purchase cycles (default: 12)",
    )
    holding_period.add_argument(
        "--holding-weeks",
        type=int,
        default=None,
        help="Scheduled calendar-week holding period; exit at first session on/after target",
    )
    parser.add_argument("--stop", type=float, default=0.45)
    parser.add_argument("--cost", type=float, default=0.001)
    parser.add_argument(
        "--max-open-lots-per-ticker",
        type=int,
        help="Maximum overlapping open lots for one ticker; omit for no cap",
    )
    parser.add_argument(
        "--exclude-ticker",
        action="append",
        default=[],
        help="Reviewed data-quality ticker exclusion; repeat for multiple symbols",
    )
    parser.add_argument(
        "--max-volatility",
        type=float,
        default=0.10,
        help="Maximum non-annualized 21-session volatility; use a negative value for no cap",
    )
    parser.add_argument("--deterioration-drop", type=float, default=0.15)
    parser.add_argument("--deterioration-volume-multiple", type=float, default=1.5)
    parser.add_argument(
        "--disable-deterioration",
        action="store_true",
        help="Disable the optional volume/price deterioration exit",
    )
    parser.add_argument("--trailing-activation", type=float)
    parser.add_argument("--trailing-initial-floor", type=float, default=0.60)
    parser.add_argument("--trailing-peak-step", type=float, default=0.10)
    parser.add_argument("--trailing-floor-step", type=float, default=0.05)
    parser.add_argument(
        "--rule",
        action="append",
        choices=sorted(RULES),
        help="Evaluate only the named rule; repeat to select multiple rules",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.holding_months is None and args.holding_weeks is None:
        args.holding_months = 12
    if args.holding_months is not None and args.holding_months < 1:
        parser.error("holding months must be positive")
    if args.holding_weeks is not None and args.holding_weeks < 1:
        parser.error("holding weeks must be positive")
    if args.max_open_lots_per_ticker is not None and args.max_open_lots_per_ticker < 1:
        parser.error("max open lots per ticker must be positive")
    if args.nominal_day and args.entry_weekday:
        parser.error("--nominal-day and --entry-weekday cannot be combined")
    if args.trailing_activation is not None:
        if not 0 <= args.trailing_initial_floor < args.trailing_activation:
            parser.error("trailing initial floor must be below activation")
        if args.trailing_peak_step <= 0 or args.trailing_floor_step <= 0:
            parser.error("trailing steps must be positive")
    active_rules = {name: RULES[name] for name in (args.rule or RULES)}
    current_month_end = date(args.end.year, args.end.month, calendar.monthrange(args.end.year, args.end.month)[1])
    entry_cutoff = args.end if args.entry_weekday else (args.end if args.end == current_month_end else date(args.end.year, args.end.month, 1) - timedelta(days=1))
    root = args.project_root.expanduser().resolve()
    output = (args.output or root / "reports/monthly_momentum_lot_matrix").resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Retain roughly a year of prices before the requested entry period so
    # 12-month momentum rules can form their first valid signal.  The prior
    # fixed 2014 cutoff silently prevented backtests from starting before 2015.
    feature_history_start = args.start - timedelta(days=400)
    validated_parquet = root / "data/validated/sp500/eod_adjusted_current.parquet"
    raw_parquet = root / "data/raw/sp500/eod_final_1996-01-01_to_2026-07-12.parquet"
    parquet = (args.parquet or (validated_parquet if validated_parquet.is_file() else raw_parquet)).resolve()
    if not parquet.is_file():
        raise FileNotFoundError(f"Adjusted Parquet file does not exist: {parquet}")
    intervals = root / "data/validated/sp500/eligible_membership_intervals.csv"
    mappings = root / "data/validated/sp500/mapping_decisions_operator.csv"
    tenure_exceptions = root / "data/validated/sp500/membership_tenure_exceptions.csv"

    registry = load_mapping_decisions(mappings).registry
    aliases = approved_provider_to_constituent(registry, "EODHD")
    nominal_days = sorted(set(args.nominal_day or range(1, 32)))
    weekdays = sorted(set(args.entry_weekday or []))
    top_n_values = sorted(set(args.top_n or range(1, 6)))
    schedule_rows: list[tuple[int, int, int, date]] = []
    if args.entry_weekday:
        cursor = args.start
        while cursor <= entry_cutoff:
            if cursor.weekday() in weekdays:
                schedule_rows.append((cursor.year, cursor.month, cursor.weekday(), cursor))
            cursor += timedelta(days=1)
    else:
        for year in range(args.start.year, entry_cutoff.year + 1):
            first_month = args.start.month if year == args.start.year else 1
            last_month = entry_cutoff.month if year == entry_cutoff.year else 12
            for month in range(first_month, last_month + 1):
                for day in nominal_days:
                    schedule_rows.append((year, month, day, scheduled_calendar_date(year, month, day)))

    # The weekly runner may launch several independent matrices at once.  Keep
    # each DuckDB connection single-threaded so parallel workers do not
    # oversubscribe CPU and memory on desktop machines.
    con = duckdb.connect(":memory:", config={"threads": "1"})
    try:
        con.execute("CREATE TABLE excluded_tickers(ticker VARCHAR)")
        con.execute("CREATE TABLE selected_top_n(top_n INTEGER)")
        con.executemany("INSERT INTO selected_top_n VALUES (?)", [(value,) for value in top_n_values])
        excluded_tickers = sorted({str(ticker).strip().upper() for ticker in args.exclude_ticker if str(ticker).strip()})
        if excluded_tickers:
            con.executemany("INSERT INTO excluded_tickers VALUES (?)", [(ticker,) for ticker in excluded_tickers])
        con.execute("CREATE TABLE aliases(provider VARCHAR, constituent VARCHAR)")
        if aliases:
            con.executemany("INSERT INTO aliases VALUES (?, ?)", sorted(aliases.items()))
        con.execute(
            "CREATE TABLE schedules("
            "year INTEGER, month INTEGER, nominal_day INTEGER, target DATE)"
        )
        con.executemany("INSERT INTO schedules VALUES (?, ?, ?, ?)", schedule_rows)
        con.execute(
            """
            CREATE TABLE universe_intervals AS
            SELECT i.*,
              COALESCE((
                SELECT MIN(CAST(x.effective_from AS DATE))
                FROM read_csv_auto(?,header=true) x
                WHERE LOWER(x.status)='approved'
                  AND UPPER(x.constituent_symbol)=UPPER(i.constituent_symbol)
                  AND CAST(x.effective_from AS DATE)<=CAST(i.effective_from AS DATE)
                  AND CAST(x.effective_from AS DATE)>COALESCE((
                    SELECT MAX(CAST(p.effective_to AS DATE))
                    FROM read_csv_auto(?,header=true) p
                    WHERE UPPER(p.constituent_symbol)=UPPER(i.constituent_symbol)
                      AND CAST(p.effective_from AS DATE)<CAST(i.effective_from AS DATE)
                  ),DATE '1900-01-01')
              ),CAST(i.effective_from AS DATE)) eligibility_from
            FROM read_csv_auto(?,header=true) i
            """,
            [str(tenure_exceptions), str(intervals), str(intervals)],
        )
        con.execute(
            """
            CREATE TABLE prices AS
            SELECT COALESCE(a.constituent, UPPER(p.Ticker)) ticker,
                   CAST(p.Date AS DATE) observed, p.Open open, p.High high,
                   p.Low low, p.Close close_price, p.Volume volume
            FROM read_parquet(?) p LEFT JOIN aliases a ON UPPER(p.Ticker)=a.provider
            WHERE CAST(p.Date AS DATE) BETWEEN ? AND ?
              AND p.Open > 0 AND p.High > 0 AND p.Low > 0 AND p.Close > 0
            """,
            [str(parquet), feature_history_start, args.end],
        )
        con.execute(
            """
            CREATE TABLE calendar AS
            SELECT observed, LAG(observed) OVER (ORDER BY observed) previous_session
            FROM (SELECT observed FROM prices GROUP BY observed HAVING COUNT(DISTINCT ticker)>=100)
            """
        )
        # Adjusted prices should not contain unreviewed multi-fold overnight
        # jumps.  Such jumps usually indicate a ticker-identity or corporate
        # action splice and can create impossible backtest returns.
        con.execute(
            """
            CREATE TABLE quarantined_tickers AS
            WITH changes AS (
              SELECT ticker, close_price,
                     LAG(close_price) OVER(PARTITION BY ticker ORDER BY observed) prior_close
              FROM prices
            )
            SELECT DISTINCT ticker
            FROM changes
            WHERE prior_close > 0
              AND GREATEST(close_price / prior_close, prior_close / close_price) > 5
            """
        )
        con.execute(
            """
            CREATE TABLE executions AS
            SELECT s.year, s.month, s.nominal_day, s.target,
                   MIN(c.observed) execution_date
            FROM schedules s JOIN calendar c ON c.observed >= s.target
            WHERE c.observed <= ? GROUP BY ALL
            """,
            [args.end],
        )
        con.execute(
            """
            CREATE TABLE price_returns AS
            SELECT *, LAG(observed) OVER(PARTITION BY ticker ORDER BY observed) prior_date,
              close_price/LAG(close_price) OVER(PARTITION BY ticker ORDER BY observed)-1 daily_return
            FROM prices
            """
        )
        con.execute(
            """
            CREATE TABLE segmented_prices AS
            SELECT *, SUM(CASE WHEN prior_date IS NULL OR DATEDIFF('day',prior_date,observed)>45
                               THEN 1 ELSE 0 END)
              OVER(PARTITION BY ticker ORDER BY observed) segment_id
            FROM price_returns
            """
        )
        con.execute(
            """
            CREATE TABLE feature_lags AS
            SELECT ticker, observed, close_price, segment_id,
              ROW_NUMBER() OVER(PARTITION BY ticker,segment_id ORDER BY observed) history_sessions,
              close_price/FIRST_VALUE(close_price) OVER(
                PARTITION BY ticker,segment_id ORDER BY observed)-1 return_since_start,
              CASE WHEN COUNT(daily_return) OVER(
                     PARTITION BY ticker,segment_id ORDER BY observed ROWS BETWEEN 20 PRECEDING AND CURRENT ROW)=21
                   THEN STDDEV_SAMP(daily_return) OVER(
                     PARTITION BY ticker,segment_id ORDER BY observed ROWS BETWEEN 20 PRECEDING AND CURRENT ROW)
              END volatility_1m,
              LAG(observed,42) OVER(PARTITION BY ticker,segment_id ORDER BY observed) date42,
              LAG(close_price,42) OVER(PARTITION BY ticker,segment_id ORDER BY observed) close42,
              LAG(observed,63) OVER(PARTITION BY ticker,segment_id ORDER BY observed) date63,
              LAG(close_price,63) OVER(PARTITION BY ticker,segment_id ORDER BY observed) close63,
              LAG(observed,84) OVER(PARTITION BY ticker,segment_id ORDER BY observed) date84,
              LAG(close_price,84) OVER(PARTITION BY ticker,segment_id ORDER BY observed) close84,
              LAG(observed,105) OVER(PARTITION BY ticker,segment_id ORDER BY observed) date105,
              LAG(close_price,105) OVER(PARTITION BY ticker,segment_id ORDER BY observed) close105,
              LAG(observed,126) OVER(PARTITION BY ticker,segment_id ORDER BY observed) date126,
              LAG(close_price,126) OVER(PARTITION BY ticker,segment_id ORDER BY observed) close126,
              LAG(observed,147) OVER(PARTITION BY ticker,segment_id ORDER BY observed) date147,
              LAG(close_price,147) OVER(PARTITION BY ticker,segment_id ORDER BY observed) close147,
              LAG(observed,168) OVER(PARTITION BY ticker,segment_id ORDER BY observed) date168,
              LAG(close_price,168) OVER(PARTITION BY ticker,segment_id ORDER BY observed) close168,
              LAG(observed,189) OVER(PARTITION BY ticker,segment_id ORDER BY observed) date189,
              LAG(close_price,189) OVER(PARTITION BY ticker,segment_id ORDER BY observed) close189,
              LAG(observed,252) OVER(PARTITION BY ticker,segment_id ORDER BY observed) date252,
              LAG(close_price,252) OVER(PARTITION BY ticker,segment_id ORDER BY observed) close252
            FROM segmented_prices
            """
        )
        con.execute(
            """
            CREATE TABLE features AS
            SELECT ticker, observed, close_price, history_sessions, return_since_start,
              volatility_1m,
              CASE WHEN DATEDIFF('day',date42,observed)<=73
                   THEN close_price/close42-1 END ret42,
              CASE WHEN DATEDIFF('day',date63,observed)<=110
                   THEN close_price/close63-1 END ret63,
              CASE WHEN DATEDIFF('day',date84,observed)<=147
                   THEN close_price/close84-1 END ret84,
              CASE WHEN DATEDIFF('day',date105,observed)<=184
                   THEN close_price/close105-1 END ret105,
              CASE WHEN DATEDIFF('day',date126,observed)<=221
                   THEN close_price/close126-1 END ret126,
              CASE WHEN DATEDIFF('day',date147,observed)<=257
                   THEN close_price/close147-1 END ret147,
              CASE WHEN DATEDIFF('day',date168,observed)<=294
                   THEN close_price/close168-1 END ret168,
              CASE WHEN DATEDIFF('day',date189,observed)<=331
                   THEN close_price/close189-1 END ret189,
              CASE WHEN DATEDIFF('day',date252,observed)<=441
                   THEN close_price/close252-1 END ret252
            FROM feature_lags
            """
        )
        unions = " UNION ALL ".join(
            f"SELECT '{name}' AS rule_name, * FROM base WHERE {condition}"
            for name, condition in active_rules.items()
        )
        con.execute(
            f"""
            CREATE TABLE rankings AS
            WITH base AS (
              SELECT e.nominal_day, e.target, e.execution_date, c.previous_session signal_date,
                     f.ticker, f.ret42, f.ret63, f.ret84, f.ret105, f.ret126,
                     f.ret147, f.ret168, f.ret189, f.ret252,
                     COALESCE(f.ret252,f.return_since_start) ranking_return,
                     f.return_since_start,f.history_sessions,f.volatility_1m,
                     p.open entry_price,
                     (x.constituent_symbol IS NOT NULL
                      AND c.previous_session<i.eligibility_from+INTERVAL 60 DAY)
                       seasoning_exception,
                     (x.constituent_symbol IS NOT NULL
                      AND c.previous_session<CAST(i.effective_from AS DATE))
                       inherited_eligibility_exception,
                     x.parent_symbol exception_parent,
                     x.reason exception_reason
              FROM executions e JOIN calendar c ON c.observed=e.execution_date
              JOIN features f ON f.observed=c.previous_session
              JOIN prices p ON p.ticker=f.ticker AND p.observed=e.execution_date
              JOIN universe_intervals i ON UPPER(i.constituent_symbol)=f.ticker
                AND c.previous_session>=i.eligibility_from
                AND (i.effective_to IS NULL OR CAST(i.effective_to AS VARCHAR)=''
                     OR c.previous_session<=CAST(i.effective_to AS DATE))
                AND e.execution_date>=i.eligibility_from
                AND (i.effective_to IS NULL OR CAST(i.effective_to AS VARCHAR)=''
                     OR e.execution_date<=CAST(i.effective_to AS DATE))
              LEFT JOIN read_csv_auto(?, header=true) x
                ON UPPER(x.constituent_symbol)=f.ticker AND LOWER(x.status)='approved'
               AND c.previous_session>=CAST(x.effective_from AS DATE)
               AND (x.effective_to IS NULL OR CAST(x.effective_to AS VARCHAR)=''
                    OR c.previous_session<=CAST(x.effective_to AS DATE))
              WHERE e.execution_date BETWEEN ? AND ?
                AND NOT EXISTS (SELECT 1 FROM excluded_tickers q WHERE q.ticker=f.ticker)
                AND NOT EXISTS (SELECT 1 FROM quarantined_tickers q WHERE q.ticker=f.ticker)
                AND (? < 0 OR f.volatility_1m<=?)
                AND (c.previous_session>=i.eligibility_from+INTERVAL 60 DAY
                     OR x.constituent_symbol IS NOT NULL)
            ), qualifying AS ({unions})
            SELECT *, ROW_NUMBER() OVER(
              PARTITION BY rule_name, nominal_day, execution_date ORDER BY ranking_return DESC, ticker
            ) rank, COUNT(*) OVER(
              PARTITION BY rule_name, nominal_day, execution_date
            ) candidate_count
            FROM qualifying QUALIFY rank<=5
            """,
            [
                str(tenure_exceptions), args.start, args.end,
                args.max_volatility, args.max_volatility,
            ],
        )
        con.execute(
            """
            CREATE TABLE deterioration_signals AS
            SELECT ticker,observed,daily_return,volume,
              AVG(volume) OVER(PARTITION BY ticker,segment_id ORDER BY observed
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) prior_10d_average_volume,
              COUNT(volume) OVER(PARTITION BY ticker,segment_id ORDER BY observed
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) prior_10d_count
            FROM segmented_prices
            """
        )
        con.execute(
            """
            CREATE TABLE expanded AS
            SELECT r.*, n.top_n, ?/LEAST(n.top_n,r.candidate_count) allocation,
                   (?/LEAST(n.top_n,r.candidate_count))/(1+?) gross_entry_notional,
                   r.entry_price*(1-?) stop_price
            FROM rankings r CROSS JOIN selected_top_n n WHERE r.rank<=n.top_n
            """,
            [args.monthly_budget, args.monthly_budget, args.cost, args.stop],
        )
        maturity_interval = (
            "(? * INTERVAL 7 DAY)" if args.holding_weeks is not None else "(? * INTERVAL 1 MONTH)"
        )
        holding_value = args.holding_weeks or args.holding_months
        trade_rows = con.execute(
            """
            WITH maturities AS (
              SELECT e.*,
                (SELECT MIN(c.observed) FROM calendar c
                  WHERE c.observed>=e.execution_date+""" + maturity_interval + """) scheduled_maturity_date,
                (SELECT MIN(p.observed) FROM prices p
                  WHERE p.ticker=e.ticker AND p.observed>e.execution_date
                    -- Hold through the scheduled maturity session's close;
                    -- exit at the following available market open.
                    AND p.observed>(SELECT MIN(c.observed) FROM calendar c
                      WHERE c.observed>=e.execution_date+""" + maturity_interval + """)) maturity_exit
              FROM expanded e
            ), dates AS (
              SELECT e.*,
                (SELECT MIN(p.observed) FROM prices p WHERE p.ticker=e.ticker
                  -- Stops are signals confirmed at the completed close, not
                  -- intraday fills.  They remain eligible through maturity.
                  AND p.observed>=e.execution_date
                  AND p.observed<=e.scheduled_maturity_date
                  AND p.close_price<=e.stop_price) stop_signal_date,
                (SELECT MIN(s.observed) FROM deterioration_signals s
                  WHERE s.ticker=e.ticker AND s.observed>=e.execution_date
                    AND (e.maturity_exit IS NULL OR s.observed<e.maturity_exit)
                    AND NOT ?
                    AND s.prior_10d_count=10
                    AND s.volume>=?*s.prior_10d_average_volume
                    AND s.daily_return<=-?) deterioration_signal_date,
                (SELECT MIN(p.observed) FROM prices p
                  WHERE p.ticker=e.ticker AND p.observed>e.execution_date
                    AND (e.maturity_exit IS NULL OR p.observed<e.maturity_exit)
                    AND ? IS NOT NULL
                    AND (SELECT MAX(h.close_price) FROM prices h
                         WHERE h.ticker=e.ticker
                           AND h.observed>=e.execution_date
                           AND h.observed<=p.observed)>=e.entry_price*(1+?)
                    AND p.close_price<=e.entry_price*(1+?+?*FLOOR(
                      GREATEST(0,(
                        (SELECT MAX(h.close_price) FROM prices h
                         WHERE h.ticker=e.ticker
                           AND h.observed>=e.execution_date
                           AND h.observed<=p.observed)/e.entry_price-1-?
                      )+1e-12)/?))) trailing_signal_date
              FROM maturities e
            ), executable AS (
              SELECT d.*,
                (SELECT MIN(p.observed) FROM prices p WHERE p.ticker=d.ticker
                  AND p.observed>d.stop_signal_date) stop_exit_date,
                (SELECT MIN(p.observed) FROM prices p WHERE p.ticker=d.ticker
                AND p.observed>d.deterioration_signal_date) deterioration_exit_date,
                (SELECT MIN(p.observed) FROM prices p WHERE p.ticker=d.ticker
                AND p.observed>d.trailing_signal_date) trailing_exit_date
              FROM dates d
            ), resolved_dates AS (
              SELECT e.*,NULLIF(LEAST(
                COALESCE(stop_exit_date,DATE '9999-12-31'),
                COALESCE(deterioration_exit_date,DATE '9999-12-31'),
                COALESCE(trailing_exit_date,DATE '9999-12-31'),
                COALESCE(maturity_exit,DATE '9999-12-31')),DATE '9999-12-31') exit_date
              FROM executable e
            ), resolved AS (
              SELECT d.*,CASE WHEN exit_date=stop_exit_date THEN 'stop'
                WHEN exit_date=deterioration_exit_date THEN 'volume_price_deterioration'
                WHEN exit_date=trailing_exit_date THEN 'stepwise_profit_trailing'
                WHEN exit_date=maturity_exit THEN 'one_year' ELSE 'open_mtm' END status
              FROM resolved_dates d
            )
            SELECT r.rule_name,r.nominal_day,r.top_n,r.target,r.signal_date,r.execution_date,
              r.ticker,r.rank,r.ret42,r.ret63,r.ret84,r.ret105,r.ret126,r.ret147,
              r.ret168,r.ret189,r.ret252,r.ranking_return,
              r.return_since_start,r.history_sessions,r.volatility_1m,r.entry_price,
              r.seasoning_exception,r.inherited_eligibility_exception,
              r.exception_parent,r.exception_reason,
              r.allocation,r.gross_entry_notional,r.stop_price,r.deterioration_signal_date,
              r.trailing_signal_date,
              r.exit_date,r.status,
              CASE WHEN r.status='open_mtm' THEN lastp.close_price
                   WHEN r.status IN ('one_year','volume_price_deterioration',
                                     'stepwise_profit_trailing','stop') THEN xp.open END exit_price,
              CASE WHEN r.status='stop' THEN 'stop_close_next_open' ELSE r.status END exit_reason
            FROM resolved r
            LEFT JOIN prices xp ON xp.ticker=r.ticker AND xp.observed=r.exit_date
            LEFT JOIN LATERAL (SELECT close_price FROM prices p WHERE p.ticker=r.ticker
              AND p.observed<=? ORDER BY p.observed DESC LIMIT 1) lastp ON TRUE
            ORDER BY r.rule_name,r.nominal_day,r.top_n,r.execution_date,r.rank
            """,
            [
                holding_value,
                holding_value,
                args.disable_deterioration,
                args.deterioration_volume_multiple,
                args.deterioration_drop,
                args.trailing_activation,
                args.trailing_activation,
                args.trailing_initial_floor,
                args.trailing_floor_step,
                args.trailing_activation,
                args.trailing_peak_step,
                args.end,
            ],
        ).fetchall()
        columns = [item[0] for item in con.description]
    finally:
        con.close()

    trades: list[dict[str, object]] = []
    for values in trade_rows:
        row = dict(zip(columns, values, strict=True))
        row["rule"] = row.pop("rule_name")
        shares = float(row["gross_entry_notional"]) / float(row["entry_price"])
        gross_exit = shares * float(row["exit_price"])
        entry_cost = float(row["allocation"]) - float(row["gross_entry_notional"])
        exit_cost = gross_exit * args.cost
        net_exit = gross_exit - exit_cost
        row.update(
            shares=shares,
            entry_cost=entry_cost,
            exit_cost=exit_cost,
            net_proceeds=net_exit,
            net_profit=net_exit - float(row["allocation"]),
            return_pct=net_exit / float(row["allocation"]) - 1,
            valuation_date=row["exit_date"] or args.end,
        )
        trades.append(row)

    if args.max_open_lots_per_ticker is not None:
        capped: list[dict[str, object]] = []
        by_configuration: dict[tuple[str, int, int], list[dict[str, object]]] = defaultdict(list)
        for trade in trades:
            by_configuration[
                (str(trade["rule"]), int(trade["nominal_day"]), int(trade["top_n"]))
            ].append(trade)
        for items in by_configuration.values():
            open_exits: dict[str, list[date | None]] = defaultdict(list)
            for trade in sorted(items, key=lambda item: (item["execution_date"], item["rank"], item["ticker"])):
                ticker = str(trade["ticker"])
                entry_date = trade["execution_date"]
                open_exits[ticker] = [
                    exit_date for exit_date in open_exits[ticker]
                    if exit_date is None or exit_date > entry_date
                ]
                if len(open_exits[ticker]) >= args.max_open_lots_per_ticker:
                    continue
                open_exits[ticker].append(trade["exit_date"])
                capped.append(trade)
        trades = capped

    groups: dict[tuple[str, int, int], list[dict[str, object]]] = defaultdict(list)
    for trade in trades:
        groups[(str(trade["rule"]), int(trade["nominal_day"]), int(trade["top_n"]))].append(trade)
    summaries: list[dict[str, object]] = []
    expected_entries_by_day: dict[int, int] = defaultdict(int)
    for _, _, nominal_day, _ in schedule_rows:
        expected_entries_by_day[nominal_day] += 1
    for (rule, day, top_n), items in groups.items():
        deployed_months = len({item["execution_date"] for item in items})
        idle_cash = (expected_entries_by_day[day] - deployed_months) * args.monthly_budget
        invested = sum(float(item["allocation"]) for item in items) + idle_cash
        proceeds = sum(float(item["net_proceeds"]) for item in items) + idle_cash
        flows = [(item["execution_date"], -float(item["allocation"])) for item in items]
        flows += [(item["valuation_date"], float(item["net_proceeds"])) for item in items]
        summaries.append(
            {
                "rule": rule,
                "nominal_day": day,
                "top_n": top_n,
                "trade_count": len(items),
                "deployed_months": deployed_months,
                "idle_cash_contributions": idle_cash,
                "invested_capital": invested,
                "net_proceeds": proceeds,
                "net_profit": proceeds - invested,
                "roi": proceeds / invested - 1,
                "xirr": _xirr(flows),
                "win_rate": sum(float(i["net_profit"]) > 0 for i in items) / len(items),
                "stop_rate": (
                    sum(str(i["exit_reason"]).startswith("stop") for i in items) / len(items)
                ),
                "open_lots": sum(i["status"] == "open_mtm" for i in items),
                "maximum_single_trade_return": max(float(i["return_pct"]) for i in items),
                "minimum_single_trade_return": min(float(i["return_pct"]) for i in items),
            }
        )
    summaries.sort(key=lambda x: (-x["roi"], -x["net_profit"], x["stop_rate"]))
    for index, row in enumerate(summaries, 1):
        row["rank"] = index

    trade_headers = list(trades[0])
    summary_headers = list(summaries[0])
    _write_csv(output / "all_trades.csv", trade_headers, trades)
    best_configuration = summaries[0]
    best_trades = [
        trade
        for trade in trades
        if trade["rule"] == best_configuration["rule"]
        and trade["nominal_day"] == best_configuration["nominal_day"]
        and trade["top_n"] == best_configuration["top_n"]
    ]
    _write_csv(output / "best_configuration_trades.csv", trade_headers, best_trades)
    spinoff_trades = [
        trade for trade in trades
        if bool(trade["seasoning_exception"])
        or bool(trade["inherited_eligibility_exception"])
    ]
    _write_csv(output / "spinoff_selected_trades.csv", trade_headers, spinoff_trades)
    spinoff_summary: list[dict[str, object]] = []
    for ticker in sorted({str(trade["ticker"]) for trade in spinoff_trades}):
        ticker_trades = [trade for trade in spinoff_trades if trade["ticker"] == ticker]
        spinoff_summary.append(
            {
                "ticker": ticker,
                "parent": ticker_trades[0]["exception_parent"],
                "selected_trade_rows": len(ticker_trades),
                "distinct_configurations": len(
                    {(t["rule"], t["nominal_day"], t["top_n"]) for t in ticker_trades}
                ),
                "first_selection": min(t["execution_date"] for t in ticker_trades),
                "last_selection": max(t["execution_date"] for t in ticker_trades),
                "best_rank": min(int(t["rank"]) for t in ticker_trades),
                "average_return": sum(float(t["return_pct"]) for t in ticker_trades)
                / len(ticker_trades),
            }
        )
    _write_csv(
        output / "spinoff_selection_summary.csv",
        [
            "ticker", "parent", "selected_trade_rows", "distinct_configurations",
            "first_selection", "last_selection", "best_rank", "average_return",
        ],
        spinoff_summary,
    )
    _write_csv(output / "configuration_summary.csv", summary_headers, summaries)
    day_summary: list[dict[str, object]] = []
    for day in (weekdays if args.entry_weekday else nominal_days):
        rows = [row for row in summaries if row["nominal_day"] == day]
        if not rows:
            continue
        best = min(rows, key=lambda row: int(row["rank"]))
        day_summary.append(
            {
                "nominal_day": day,
                "best_rule": best["rule"],
                "best_top_n": best["top_n"],
                "best_xirr": best["xirr"],
                "best_roi": best["roi"],
                "best_net_profit": best["net_profit"],
            }
        )
    _write_csv(output / "day_summary.csv", list(day_summary[0]), day_summary)
    assumptions = {
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "adjusted_parquet": str(parquet),
        "last_entry_month_end": entry_cutoff.isoformat(),
        "entry_frequency": "weekly_by_weekday" if args.entry_weekday else "monthly_by_calendar_day",
        "entry_weekdays": weekdays if args.entry_weekday else None,
        "monthly_budget": args.monthly_budget,
        "holding_months": args.holding_months,
        "holding_weeks": args.holding_weeks,
        "annual_budget": args.monthly_budget * (52 * len(weekdays) if args.entry_weekday else 12),
        "stop_loss": args.stop,
        "transaction_cost_each_side": args.cost,
        "maximum_one_month_volatility": (
            None if args.max_volatility < 0 else args.max_volatility
        ),
        "deterioration_drop_threshold": args.deterioration_drop,
        "deterioration_volume_multiple": args.deterioration_volume_multiple,
        "deterioration_disabled": args.disable_deterioration,
        "stepwise_profit_trailing": {
            "enabled": args.trailing_activation is not None,
            "activation": args.trailing_activation,
            "initial_floor": args.trailing_initial_floor,
            "peak_step": args.trailing_peak_step,
            "floor_step": args.trailing_floor_step,
            "signal_and_fill": "completed daily close; exit at next session open",
        },
        "holding_period": (
            f"{args.holding_weeks} calendar week(s); hold through the target session close "
            "and sell at the following market open" if args.holding_weeks is not None else
            f"{args.holding_months} subsequent scheduled monthly purchase cycle(s); "
            "sell at that session open and reuse after-tax proceeds for the same-session purchase"
        ),
        "rules": list(active_rules),
        "top_n_values": top_n_values,
        "nominal_days": nominal_days,
        "best_configuration": best_configuration,
        "point_in_time_membership": True,
        "minimum_continuous_membership_days": 60,
        "reviewed_data_quality_exclusions": excluded_tickers,
        "approved_seasoning_exceptions_file": str(tenure_exceptions),
        "spinoff_selected_trade_rows": len(spinoff_trades),
        "spinoff_selected_tickers": sorted({str(t["ticker"]) for t in spinoff_trades}),
        "ranking_metric": (
            "252-session return when available; otherwise return from the start of "
            "the current continuous security-history segment"
        ),
        "minimum_history_by_rule": {
            "12M>9M>6M>3M>0": "252 sessions",
            "12M>9M>6M>3M>0 & 2M>0": "252 sessions",
            "9M>6M>3M>0 & 2M>0": "189 sessions",
            "6M>3M>0 & 2M>0": "126 sessions",
            "5M>2M>0": "105 sessions",
            "5M>3M>0": "105 sessions",
            "6M>4M>0": "126 sessions",
            "4M>2M>0": "84 sessions",
            "3M>2M>0": "63 sessions",
            "7M>4M>0": "147 sessions",
            "8M>5M>0": "168 sessions",
            "9M>6M>0": "189 sessions",
        },
        "one_month_volatility": (
            "sample standard deviation of 21 completed daily simple returns; "
            + ("no cap" if args.max_volatility < 0 else f"maximum {args.max_volatility:.0%}")
            + ", not annualized"
        ),
        "deterioration_exit": (
            "disabled"
            if args.disable_deterioration
            else (
                f"close-to-close daily return <= -{args.deterioration_drop:.0%} "
                "(including gaps) AND volume >= "
                f"{args.deterioration_volume_multiple:g}x the prior 10-session average; "
                "exit at next session open"
            )
        ),
        "comparison_metric": "total ROI on contributed capital; XIRR is secondary",
        "open_lots": "marked to final available close",
    }
    (output / "report.json").write_text(json.dumps(assumptions, indent=2, default=str) + "\n")
    print(json.dumps({"output": str(output), **assumptions}, indent=2, default=str))


if __name__ == "__main__":
    main()
