"""Transparent long-only portfolio simulation for demand-zone trade plans."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date

from quantresearch.simulation.brackets import BracketExitReason, resolve_long_bracket
from quantresearch.simulation.models import (
    Bar,
    EquityPoint,
    Order,
    OrderStatus,
    Position,
    SignalAction,
    SimulationResult,
    Trade,
)
from quantresearch.strategies.supply_demand_signals import (
    DemandEntryType,
    DemandTradePlan,
)


@dataclass(frozen=True, slots=True)
class DemandSimulationConfig:
    initial_cash: float = 100_000.0
    risk_fraction: float = 0.01
    maximum_position_weight: float = 0.10
    max_positions: int = 10
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    short_term_profit_haircut: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive and finite")
        if not 0 < self.risk_fraction <= 1:
            raise ValueError("risk_fraction must be in (0, 1]")
        if not 0 < self.maximum_position_weight <= 1:
            raise ValueError("maximum_position_weight must be in (0, 1]")
        if not isinstance(self.max_positions, int) or self.max_positions < 1:
            raise ValueError("max_positions must be a positive integer")
        if not 0 <= self.commission_bps <= 1_000:
            raise ValueError("commission_bps must be between 0 and 1000")
        if not 0 <= self.slippage_bps <= 1_000:
            raise ValueError("slippage_bps must be between 0 and 1000")
        if not 0 <= self.short_term_profit_haircut <= 1:
            raise ValueError("short_term_profit_haircut must be between zero and one")


@dataclass(slots=True)
class _OpenBracket:
    position: Position
    trade_index: int
    plan: DemandTradePlan


class DemandTradeSimulator:
    """Reference next-session entry and daily stop/target portfolio engine."""

    def __init__(self, config: DemandSimulationConfig | None = None) -> None:
        self.config = config or DemandSimulationConfig()

    def run(
        self,
        *,
        bars: Iterable[Bar],
        plans: Iterable[DemandTradePlan],
        membership: Mapping[date, frozenset[str]],
    ) -> SimulationResult:
        ordered_bars = sorted(bars, key=lambda item: (item.date, item.ticker))
        keys = [(item.ticker, item.date) for item in ordered_bars]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate ticker-date bars are not allowed")
        bar_dates = {item.date for item in ordered_bars}

        plans_by_date: dict[date, list[DemandTradePlan]] = {}
        seen_plans: set[tuple[str, date]] = set()
        for plan in plans:
            key = (plan.ticker, plan.decision_date)
            if key in seen_plans:
                raise ValueError("duplicate ticker-date demand plans are not allowed")
            seen_plans.add(key)
            if plan.available_after > plan.decision_date:
                raise ValueError("Demand plans cannot be used before availability")
            if plan.decision_date not in bar_dates:
                raise ValueError("Demand plan decision date requires a completed market bar")
            plans_by_date.setdefault(plan.decision_date, []).append(plan)

        bars_by_date: dict[date, dict[str, Bar]] = {}
        for item in ordered_bars:
            bars_by_date.setdefault(item.date, {})[item.ticker] = item

        cash = self.config.initial_cash
        open_brackets: dict[str, _OpenBracket] = {}
        pending: list[tuple[DemandTradePlan, Order]] = []
        orders: list[Order] = []
        trades: list[Trade] = []
        equity_curve: list[EquityPoint] = []
        last_closes: dict[str, float] = {}

        for current_date, daily_bars in sorted(bars_by_date.items()):
            for ticker in sorted(tuple(open_brackets)):
                item = daily_bars.get(ticker)
                if item is not None:
                    cash = self._apply_bracket(
                        open_brackets[ticker], item, cash, open_brackets, trades, orders
                    )

            remaining: list[tuple[DemandTradePlan, Order]] = []
            for plan, order in pending:
                item = daily_bars.get(plan.ticker)
                if item is None:
                    remaining.append((plan, order))
                    continue
                if plan.ticker not in membership.get(current_date, frozenset()):
                    order.status = OrderStatus.REJECTED_INELIGIBLE
                    order.execution_date = current_date
                    order.rejection_reason = "not eligible on execution date"
                    continue
                if plan.ticker in open_brackets or len(open_brackets) >= self.config.max_positions:
                    order.status = OrderStatus.REJECTED_POSITION_EXISTS
                    order.execution_date = current_date
                    order.rejection_reason = "position capacity unavailable"
                    continue
                fill = self._entry_fill(plan, item)
                if fill is None:
                    order.status = OrderStatus.UNFILLED
                    order.execution_date = current_date
                    order.rejection_reason = "next-session limit not reached"
                    continue
                quantity = self._quantity(cash, fill, plan.stop_price)
                commission = fill * quantity * self.config.commission_bps / 10_000
                total = fill * quantity + commission
                if quantity <= 0 or total > cash + 1e-10:
                    order.status = OrderStatus.REJECTED_CASH
                    order.execution_date = current_date
                    order.rejection_reason = "insufficient cash or risk capacity"
                    continue
                position = Position(plan.ticker, quantity, current_date, fill, commission)
                trades.append(Trade(plan.ticker, quantity, current_date, fill, commission))
                bracket = _OpenBracket(position, len(trades) - 1, plan)
                open_brackets[plan.ticker] = bracket
                cash -= total
                order.status = OrderStatus.FILLED
                order.execution_date = current_date
                order.fill_price = fill
                cash = self._apply_bracket(bracket, item, cash, open_brackets, trades, orders)
            pending = remaining

            available_slots = self.config.max_positions - len(open_brackets) - len(pending)
            members = membership.get(current_date, frozenset())
            eligible = [
                plan
                for plan in plans_by_date.get(current_date, [])
                if plan.ticker in members
                and plan.ticker not in open_brackets
                and all(existing.ticker != plan.ticker for existing, _ in pending)
            ]
            ranked = sorted(eligible, key=lambda plan: (-plan.ranking_score, plan.ticker))
            for plan in ranked[: max(available_slots, 0)]:
                order = Order(
                    plan.plan_id,
                    plan.decision_date,
                    plan.ticker,
                    SignalAction.ENTRY,
                    None,
                    plan.entry_price if plan.entry_type is DemandEntryType.LIMIT else None,
                )
                orders.append(order)
                pending.append((plan, order))

            last_closes.update({ticker: item.close for ticker, item in daily_bars.items()})
            market_value = sum(
                bracket.position.quantity * last_closes[ticker]
                for ticker, bracket in open_brackets.items()
                if ticker in last_closes
            )
            equity_curve.append(EquityPoint(current_date, cash, market_value, cash + market_value))

        for _, order in pending:
            order.status = OrderStatus.UNFILLED
            order.rejection_reason = "no later bar"

        positions = tuple(
            sorted((item.position for item in open_brackets.values()), key=lambda item: item.ticker)
        )
        ending_equity = equity_curve[-1].equity if equity_curve else cash
        return SimulationResult(
            tuple(orders), tuple(trades), positions, tuple(equity_curve), cash, ending_equity
        )

    def _entry_fill(self, plan: DemandTradePlan, bar: Bar) -> float | None:
        slip = self.config.slippage_bps / 10_000
        if plan.entry_type is DemandEntryType.NEXT_OPEN_MARKET:
            return bar.open * (1 + slip)
        if bar.low > plan.entry_price:
            return None
        return min(plan.entry_price, min(bar.open, plan.entry_price) * (1 + slip))

    def _quantity(self, cash: float, fill: float, stop: float) -> float:
        risk_per_share = fill - stop
        if risk_per_share <= 0:
            return 0.0
        by_risk = self.config.initial_cash * self.config.risk_fraction / risk_per_share
        by_weight = self.config.initial_cash * self.config.maximum_position_weight / fill
        by_cash = cash / (fill * (1 + self.config.commission_bps / 10_000))
        return max(min(by_risk, by_weight, by_cash), 0.0)

    def _apply_bracket(
        self,
        bracket: _OpenBracket,
        bar: Bar,
        cash: float,
        open_brackets: dict[str, _OpenBracket],
        trades: list[Trade],
        orders: list[Order],
    ) -> float:
        resolution = resolve_long_bracket(
            bar,
            stop_price=bracket.plan.stop_price,
            target_price=bracket.plan.target_price,
        )
        if resolution.reason is BracketExitReason.OPEN:
            return cash
        raw_fill = float(resolution.fill_price)
        fill = raw_fill * (1 - self.config.slippage_bps / 10_000)
        position = bracket.position
        proceeds = fill * position.quantity
        commission = proceeds * self.config.commission_bps / 10_000
        gross_profit = max((fill - position.entry_price) * position.quantity, 0.0)
        held_days = (bar.date - position.entry_date).days
        tax = (
            gross_profit * self.config.short_term_profit_haircut if held_days <= 365 else 0.0
        )
        net_profit = (
            proceeds
            - commission
            - tax
            - position.entry_price * position.quantity
            - position.entry_commission
        )
        trades[bracket.trade_index] = replace(
            trades[bracket.trade_index],
            exit_date=bar.date,
            exit_price=fill,
            exit_commission=commission,
            tax_haircut=tax,
            net_profit=net_profit,
        )
        exit_order = Order(
            f"{bracket.plan.plan_id}_exit",
            bar.date,
            position.ticker,
            SignalAction.EXIT,
            position.quantity,
            raw_fill,
            status=OrderStatus.FILLED,
            execution_date=bar.date,
            fill_price=fill,
            rejection_reason=resolution.reason.value,
        )
        orders.append(exit_order)
        del open_brackets[position.ticker]
        return cash + proceeds - commission - tax

