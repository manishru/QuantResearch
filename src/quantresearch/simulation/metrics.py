"""Deterministic performance and risk metrics for simulation results."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from quantresearch.simulation.models import SimulationResult


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    total_return: float
    cagr: float
    maximum_drawdown: float
    average_calendar_year_return: float
    median_calendar_year_return: float
    worst_calendar_year: int
    worst_calendar_year_return: float
    positive_year_fraction: float
    annualized_volatility: float
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    calendar_year_returns: dict[int, float]
    closed_trade_count: int
    open_trade_count: int
    win_rate: float | None
    profit_factor: float | None


def calculate_performance(
    result: SimulationResult,
    *,
    initial_equity: float,
    periods_per_year: int = 252,
) -> PerformanceReport:
    """Calculate transparent unlevered metrics from a reconciled equity curve."""
    if not result.equity_curve:
        raise ValueError("A nonempty equity curve is required")
    if not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("initial_equity must be positive and finite")

    points = result.equity_curve
    equities = [point.equity for point in points]
    if any(not math.isfinite(value) or value <= 0 for value in equities):
        raise ValueError("Equity values must be positive and finite")

    total_return = equities[-1] / initial_equity - 1
    elapsed_days = (points[-1].date - points[0].date).days
    cagr = (
        (equities[-1] / initial_equity) ** (365.2425 / elapsed_days) - 1
        if elapsed_days > 0
        else 0.0
    )

    peak = equities[0]
    maximum_drawdown = 0.0
    for equity in equities:
        peak = max(peak, equity)
        maximum_drawdown = min(maximum_drawdown, equity / peak - 1)

    year_ends: dict[int, float] = {}
    for point in points:
        year_ends[point.date.year] = point.equity
    calendar_year_returns: dict[int, float] = {}
    previous = initial_equity
    for year, ending in sorted(year_ends.items()):
        calendar_year_returns[year] = ending / previous - 1
        previous = ending

    yearly_values = list(calendar_year_returns.values())
    worst_calendar_year = min(calendar_year_returns, key=calendar_year_returns.get)
    average_year = statistics.fmean(yearly_values)
    median_year = statistics.median(yearly_values)
    positive_fraction = sum(value > 0 for value in yearly_values) / len(yearly_values)

    period_returns = [
        current / previous - 1 for previous, current in zip(equities, equities[1:], strict=False)
    ]
    annualized_volatility = (
        statistics.stdev(period_returns) * math.sqrt(periods_per_year)
        if len(period_returns) >= 2
        else 0.0
    )
    mean_period_return = statistics.fmean(period_returns) if period_returns else 0.0
    sharpe = (
        mean_period_return / statistics.stdev(period_returns) * math.sqrt(periods_per_year)
        if len(period_returns) >= 2 and statistics.stdev(period_returns) > 0
        else None
    )
    downside = [min(value, 0.0) for value in period_returns]
    downside_deviation = (
        math.sqrt(statistics.fmean(value * value for value in downside)) if downside else 0.0
    )
    sortino = (
        mean_period_return / downside_deviation * math.sqrt(periods_per_year)
        if downside_deviation > 0
        else None
    )
    calmar = cagr / abs(maximum_drawdown) if maximum_drawdown < 0 else None

    closed = [trade for trade in result.trades if trade.exit_date is not None]
    open_count = len(result.trades) - len(closed)
    wins = [trade.net_profit for trade in closed if trade.net_profit > 0]
    losses = [trade.net_profit for trade in closed if trade.net_profit < 0]
    win_rate = len(wins) / len(closed) if closed else None
    if losses:
        profit_factor = sum(wins) / abs(sum(losses))
    elif wins:
        profit_factor = math.inf
    else:
        profit_factor = None

    return PerformanceReport(
        total_return=total_return,
        cagr=cagr,
        maximum_drawdown=maximum_drawdown,
        average_calendar_year_return=average_year,
        median_calendar_year_return=median_year,
        worst_calendar_year=worst_calendar_year,
        worst_calendar_year_return=calendar_year_returns[worst_calendar_year],
        positive_year_fraction=positive_fraction,
        annualized_volatility=annualized_volatility,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        calendar_year_returns=calendar_year_returns,
        closed_trade_count=len(closed),
        open_trade_count=open_count,
        win_rate=win_rate,
        profit_factor=profit_factor,
    )
