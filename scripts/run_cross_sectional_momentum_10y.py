#!/usr/bin/env python3
"""Reproduce the causal weekly top-10 52-week momentum benchmark."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from datetime import date, datetime
from pathlib import Path

import duckdb

from quantresearch.ingestion.parquet_bars import (
    approved_provider_to_constituent,
    load_adjusted_bars,
)
from quantresearch.ingestion.review_decisions import load_mapping_decisions
from quantresearch.research.cross_sectional_momentum import (
    MomentumRebalance,
    simulate_equal_weight_rebalances,
)


def _date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _write_csv(path: Path, headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def _metrics(equities: list[tuple[date, float]], initial: float) -> dict[str, object]:
    values = [value for _, value in equities]
    elapsed = (equities[-1][0] - equities[0][0]).days
    total_return = values[-1] / initial - 1
    cagr = (values[-1] / initial) ** (365.2425 / elapsed) - 1 if elapsed else 0.0
    peak = values[0]
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    returns = [
        current / previous - 1
        for previous, current in zip(values, values[1:], strict=False)
    ]
    volatility = statistics.stdev(returns) * math.sqrt(252) if len(returns) > 1 else 0.0
    sharpe = (
        statistics.fmean(returns) / statistics.stdev(returns) * math.sqrt(252)
        if len(returns) > 1 and statistics.stdev(returns) > 0
        else None
    )
    year_end: dict[int, float] = {}
    for observed, value in equities:
        year_end[observed.year] = value
    calendar: dict[str, float] = {}
    prior = initial
    for year, value in sorted(year_end.items()):
        calendar[str(year)] = value / prior - 1
        prior = value
    return {
        "initial_equity": initial,
        "ending_equity": values[-1],
        "total_return": total_return,
        "cagr": cagr,
        "maximum_drawdown": drawdown,
        "annualized_volatility": volatility,
        "sharpe_zero_risk_free": sharpe,
        "calendar_year_returns": calendar,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--start", type=date.fromisoformat, default=date(2016, 7, 11))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 7, 10))
    parser.add_argument("--initial-cash", type=float, default=100_000.0)
    parser.add_argument("--cost", type=float, default=0.001)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.project_root.expanduser().resolve()
    parquet = root / "data/raw/sp500/eod_final_1996-01-01_to_2026-07-12.parquet"
    intervals = root / "data/validated/sp500/eligible_membership_intervals.csv"
    mappings_path = root / "data/validated/sp500/mapping_decisions_operator.csv"
    output = (args.output or root / "reports/cross_sectional_momentum_10y").resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.top <= 0:
        raise ValueError("--top must be positive")

    mapping_import = load_mapping_decisions(mappings_path)
    provider_to_constituent = approved_provider_to_constituent(
        mapping_import.registry, "EODHD"
    )
    constituent_to_provider = {
        constituent: provider for provider, constituent in provider_to_constituent.items()
    }

    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TEMP TABLE aliases(provider VARCHAR, constituent VARCHAR)")
        if provider_to_constituent:
            connection.executemany(
                "INSERT INTO aliases VALUES (?, ?)", sorted(provider_to_constituent.items())
            )
        ranking_rows = connection.execute(
            """
            WITH prices AS (
              SELECT COALESCE(a.constituent, UPPER(p.Ticker)) AS ticker,
                     CAST(p.Date AS DATE) AS observed, p.Close AS close
              FROM read_parquet(?) p
              LEFT JOIN aliases a ON UPPER(p.Ticker) = a.provider
              WHERE CAST(p.Date AS DATE) >= DATE '2015-01-01'
                AND CAST(p.Date AS DATE) <= ? AND p.Close > 0
            ), momentum AS (
              SELECT ticker, observed, close,
                     close / LAG(close, 252) OVER (
                       PARTITION BY ticker ORDER BY observed
                     ) - 1 AS momentum_252
              FROM prices
            ), session_counts AS (
              SELECT observed, COUNT(DISTINCT ticker) AS security_count
              FROM prices GROUP BY observed
            ), calendar AS (
              SELECT observed,
                     LEAD(observed) OVER (ORDER BY observed) AS next_session
              FROM session_counts WHERE security_count >= 100
            ), week_ends AS (
              SELECT DATE_TRUNC('week', observed) AS week_start,
                     MAX(observed) AS signal_date
              FROM calendar GROUP BY 1
            ), eligible AS (
              SELECT m.ticker, m.observed AS signal_date, c.next_session AS execution_date,
                     m.momentum_252
              FROM momentum m
              JOIN week_ends w ON m.observed = w.signal_date
              JOIN calendar c ON c.observed = m.observed
              JOIN read_csv_auto(?, header=true) i
                ON UPPER(i.constituent_symbol) = m.ticker
               AND m.observed >= CAST(i.effective_from AS DATE)
               AND (i.effective_to IS NULL OR CAST(i.effective_to AS VARCHAR) = ''
                    OR m.observed <= CAST(i.effective_to AS DATE))
              WHERE m.observed >= ? AND m.observed < ?
                AND c.next_session <= ? AND m.momentum_252 IS NOT NULL
            ), ranked AS (
              SELECT *, ROW_NUMBER() OVER (
                PARTITION BY signal_date ORDER BY momentum_252 DESC, ticker
              ) AS rank
              FROM eligible
            )
            SELECT signal_date, execution_date, ticker, rank, momentum_252
            FROM ranked WHERE rank <= ? ORDER BY signal_date, rank
            """,
            [str(parquet), args.end, str(intervals), args.start, args.end, args.end, args.top],
        ).fetchall()
    finally:
        connection.close()
    if not ranking_rows:
        raise RuntimeError("No point-in-time rankings were generated")

    rankings = [(_date(s), _date(e), str(t), int(r), float(m)) for s, e, t, r, m in ranking_rows]
    grouped: dict[tuple[date, date], list[str]] = {}
    for signal, execution, ticker, _, _ in rankings:
        grouped.setdefault((signal, execution), []).append(ticker)
    rebalances = tuple(
        MomentumRebalance(signal, execution, tuple(tickers))
        for (signal, execution), tickers in sorted(grouped.items())
    )

    selected_constituents = frozenset(row[2] for row in rankings)
    selected_providers = frozenset(
        constituent_to_provider.get(symbol, symbol) for symbol in selected_constituents
    )
    bars = load_adjusted_bars(
        parquet,
        start=args.start,
        end=args.end,
        provider_to_constituent=provider_to_constituent,
        included_provider_symbols=selected_providers,
    )
    execution_dates = frozenset(item.execution_date for item in rebalances)
    membership: dict[date, frozenset[str]] = {}
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TEMP TABLE execution_dates(observed DATE PRIMARY KEY)")
        connection.executemany(
            "INSERT INTO execution_dates VALUES (?)", [(d,) for d in execution_dates]
        )
        member_rows = connection.execute(
            """
            SELECT d.observed, UPPER(i.constituent_symbol)
            FROM execution_dates d JOIN read_csv_auto(?, header=true) i
              ON d.observed >= CAST(i.effective_from AS DATE)
             AND (i.effective_to IS NULL OR CAST(i.effective_to AS VARCHAR) = ''
                  OR d.observed <= CAST(i.effective_to AS DATE))
            ORDER BY d.observed, i.constituent_symbol
            """,
            [str(intervals)],
        ).fetchall()
    finally:
        connection.close()
    mutable_membership: dict[date, set[str]] = {d: set() for d in execution_dates}
    for observed, ticker in member_rows:
        mutable_membership[_date(observed)].add(str(ticker))
    membership = {d: frozenset(symbols) for d, symbols in mutable_membership.items()}

    result = simulate_equal_weight_rebalances(
        bars,
        rebalances,
        initial_cash=args.initial_cash,
        cost_fraction=args.cost,
        execution_membership=membership,
    )
    equities = [(point.date, point.equity) for point in result.equity_curve]
    report = _metrics(equities, args.initial_cash)
    report.update(
        {
            "strategy": "weekly_top10_252_session_cross_sectional_momentum",
            "signal_start": args.start.isoformat(),
            "end": args.end.isoformat(),
            "signal_timing": "final market session of week close",
            "execution_timing": "next market session open",
            "universe": "eligible point-in-time S&P 500 membership",
            "position_count": args.top,
            "cost_fraction_of_absolute_turnover": args.cost,
            "rebalance_count": result.rebalance_count,
            "transaction_count": len(result.transactions),
            "total_cost": result.total_cost,
            "total_turnover_notional": result.total_turnover_notional,
            "selected_security_count": len(selected_constituents),
            "maximum_selected_momentum": max(row[4] for row in rankings),
            "selected_rows_over_300_percent_momentum": sum(row[4] > 3 for row in rankings),
            "causal_reproduction": True,
            "comparison_warning": (
                "Not equivalent to a same-close prototype; anomalous adjusted histories "
                "remain visible in extreme_momentum.csv."
            ),
        }
    )

    _write_csv(
        output / "target_rankings.csv",
        ("signal_date", "execution_date", "ticker", "rank", "momentum_252"),
        [(s, e, t, r, m) for s, e, t, r, m in rankings],
    )
    extremes = sorted((row for row in rankings if row[4] > 3), key=lambda row: row[4], reverse=True)
    _write_csv(
        output / "extreme_momentum.csv",
        ("signal_date", "execution_date", "ticker", "rank", "momentum_252"),
        [(s, e, t, r, m) for s, e, t, r, m in extremes],
    )
    _write_csv(
        output / "equity_curve.csv",
        ("date", "cash", "market_value", "equity"),
        [(p.date, p.cash, p.market_value, p.equity) for p in result.equity_curve],
    )
    _write_csv(
        output / "transactions.csv",
        ("date", "ticker", "shares_delta", "price", "absolute_notional", "allocated_cost"),
        [
            (t.date, t.ticker, t.shares_delta, t.price, t.absolute_notional, t.allocated_cost)
            for t in result.transactions
        ],
    )
    _write_csv(
        output / "rebalances.csv",
        (
            "signal_date",
            "execution_date",
            "requested_tickers",
            "executed_tickers",
            "turnover_notional",
            "cost",
        ),
        [
            (
                e.signal_date,
                e.execution_date,
                "|".join(e.requested_tickers),
                "|".join(e.executed_tickers),
                e.turnover_notional,
                e.cost,
            )
            for e in result.executions
        ],
    )
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), **report}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
