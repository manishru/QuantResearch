"""Causal equal-weight rebalancing for cross-sectional momentum research."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from quantresearch.simulation.models import Bar, EquityPoint


@dataclass(frozen=True, slots=True)
class MomentumRebalance:
    """A ranking frozen at ``signal_date`` and executable later."""

    signal_date: date
    execution_date: date
    tickers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.execution_date <= self.signal_date:
            raise ValueError("execution_date must follow signal_date")
        normalized = tuple(ticker.strip().upper() for ticker in self.tickers)
        if any(not ticker for ticker in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("tickers must be nonempty and unique")
        object.__setattr__(self, "tickers", normalized)


@dataclass(frozen=True, slots=True)
class MomentumTransaction:
    date: date
    ticker: str
    shares_delta: float
    price: float
    absolute_notional: float
    allocated_cost: float


@dataclass(frozen=True, slots=True)
class MomentumExecution:
    signal_date: date
    execution_date: date
    requested_tickers: tuple[str, ...]
    executed_tickers: tuple[str, ...]
    turnover_notional: float
    cost: float


@dataclass(frozen=True, slots=True)
class MomentumSimulationResult:
    equity_curve: tuple[EquityPoint, ...]
    holdings: Mapping[str, float]
    transactions: tuple[MomentumTransaction, ...]
    executions: tuple[MomentumExecution, ...]
    total_cost: float
    total_turnover_notional: float

    @property
    def rebalance_count(self) -> int:
        return len(self.executions)


def simulate_equal_weight_rebalances(
    bars: tuple[Bar, ...],
    rebalances: tuple[MomentumRebalance, ...],
    *,
    initial_cash: float,
    cost_fraction: float,
    execution_membership: Mapping[date, frozenset[str]] | None = None,
) -> MomentumSimulationResult:
    """Execute frozen rankings at next-session opens with fractional shares.

    Costs are a fraction of absolute traded notional. The initial purchase therefore
    incurs cost on the full amount deployed. Daily equity is marked at closing prices.
    """
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("initial_cash must be positive and finite")
    if not math.isfinite(cost_fraction) or not 0 <= cost_fraction < 1:
        raise ValueError("cost_fraction must be in [0, 1)")
    if len({(bar.ticker, bar.date) for bar in bars}) != len(bars):
        raise ValueError("bars contain duplicate ticker-date observations")
    if len({item.execution_date for item in rebalances}) != len(rebalances):
        raise ValueError("only one rebalance is allowed per execution date")

    bars_by_date: dict[date, dict[str, Bar]] = {}
    for bar in bars:
        bars_by_date.setdefault(bar.date, {})[bar.ticker] = bar
    rebalance_by_date = {item.execution_date: item for item in rebalances}

    cash = float(initial_cash)
    holdings: dict[str, float] = {}
    last_prices: dict[str, float] = {}
    equity_curve: list[EquityPoint] = []
    transactions: list[MomentumTransaction] = []
    executions: list[MomentumExecution] = []
    total_cost = 0.0
    total_turnover = 0.0

    for current_date in sorted(bars_by_date):
        day = bars_by_date[current_date]
        rebalance = rebalance_by_date.get(current_date)
        if rebalance is not None:
            allowed = (
                execution_membership.get(current_date, frozenset())
                if execution_membership is not None
                else None
            )
            targets = tuple(
                ticker
                for ticker in rebalance.tickers
                if ticker in day and (allowed is None or ticker in allowed)
            )
            open_value = cash + sum(
                quantity
                * (day[ticker].open if ticker in day else last_prices.get(ticker, 0.0))
                for ticker, quantity in holdings.items()
            )
            provisional_target = open_value / len(targets) if targets else 0.0
            union = set(holdings) | set(targets)
            deltas: dict[str, float] = {}
            turnover = 0.0
            for ticker in union:
                price = day[ticker].open if ticker in day else last_prices.get(ticker)
                if price is None or price <= 0:
                    continue
                current_notional = holdings.get(ticker, 0.0) * price
                desired_notional = provisional_target if ticker in targets else 0.0
                deltas[ticker] = desired_notional - current_notional
                turnover += abs(deltas[ticker])
            cost = turnover * cost_fraction
            investable = max(open_value - cost, 0.0)
            final_target = investable / len(targets) if targets else 0.0

            final_holdings: dict[str, float] = {}
            actual_turnover = 0.0
            raw_transactions: list[tuple[str, float, float, float]] = []
            for ticker in union:
                price = day[ticker].open if ticker in day else last_prices.get(ticker)
                if price is None or price <= 0:
                    continue
                desired_shares = final_target / price if ticker in targets else 0.0
                shares_delta = desired_shares - holdings.get(ticker, 0.0)
                notional = abs(shares_delta * price)
                actual_turnover += notional
                if abs(shares_delta) > 1e-12:
                    raw_transactions.append((ticker, shares_delta, price, notional))
                if desired_shares > 1e-12:
                    final_holdings[ticker] = desired_shares
            # The cost definition uses the pre-cost target portfolio. This makes the
            # first deployment exactly initial_cash * cost_fraction.
            allocated = sum(item[3] for item in raw_transactions)
            for ticker, shares_delta, price, notional in raw_transactions:
                transactions.append(
                    MomentumTransaction(
                        current_date,
                        ticker,
                        shares_delta,
                        price,
                        notional,
                        cost * notional / allocated if allocated else 0.0,
                    )
                )
            holdings = final_holdings
            cash = investable - sum(
                quantity * day[ticker].open for ticker, quantity in holdings.items()
            )
            total_cost += cost
            total_turnover += turnover
            executions.append(
                MomentumExecution(
                    rebalance.signal_date,
                    current_date,
                    rebalance.tickers,
                    targets,
                    turnover,
                    cost,
                )
            )

        last_prices.update({ticker: bar.close for ticker, bar in day.items()})
        market_value = sum(
            quantity * last_prices[ticker]
            for ticker, quantity in holdings.items()
            if ticker in last_prices
        )
        equity_curve.append(EquityPoint(current_date, cash, market_value, cash + market_value))

    return MomentumSimulationResult(
        tuple(equity_curve),
        MappingProxyType(dict(sorted(holdings.items()))),
        tuple(transactions),
        tuple(executions),
        total_cost,
        total_turnover,
    )
