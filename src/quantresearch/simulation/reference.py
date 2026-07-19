"""Slow, transparent reference implementation for long-only simulation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date

from quantresearch.research.models import canonical_id
from quantresearch.simulation.models import (
    Bar,
    EquityPoint,
    Order,
    OrderStatus,
    Position,
    Signal,
    SignalAction,
    SimulationConfig,
    SimulationResult,
    Trade,
)


class ReferenceSimulator:
    """Deterministic next-session simulator used as the correctness oracle."""

    def __init__(self, config: SimulationConfig | None = None) -> None:
        self.config = config or SimulationConfig()

    def run(
        self,
        bars: Iterable[Bar],
        signals: Iterable[Signal],
        *,
        membership: Mapping[date, frozenset[str]],
    ) -> SimulationResult:
        ordered_bars = sorted(bars, key=lambda item: (item.date, item.ticker))
        ordered_signals = sorted(signals, key=lambda item: (item.decision_date, item.ticker))
        self._validate(ordered_bars, ordered_signals)

        bars_by_date: dict[date, dict[str, Bar]] = {}
        for item in ordered_bars:
            bars_by_date.setdefault(item.date, {})[item.ticker] = item
        signals_by_date: dict[date, list[Signal]] = {}
        for item in ordered_signals:
            signals_by_date.setdefault(item.decision_date, []).append(item)

        cash = self.config.initial_cash
        positions: dict[str, Position] = {}
        open_trade_indexes: dict[str, int] = {}
        trades: list[Trade] = []
        orders: list[Order] = []
        pending: list[Order] = []
        equity_curve: list[EquityPoint] = []
        last_closes: dict[str, float] = {}

        for current_date, daily_bars in sorted(bars_by_date.items()):
            next_pending: list[Order] = []
            for order in pending:
                item = daily_bars.get(order.ticker)
                if item is None:
                    next_pending.append(order)
                    continue
                if order.action is SignalAction.ENTRY:
                    cash = self._execute_entry(
                        order, item, membership, cash, positions, trades, open_trade_indexes
                    )
                else:
                    cash = self._execute_exit(
                        order, item, cash, positions, trades, open_trade_indexes
                    )
            pending = next_pending

            for signal in signals_by_date.get(current_date, []):
                order = self._create_order(signal, len(orders))
                orders.append(order)
                if signal.action is SignalAction.ENTRY and signal.ticker not in membership.get(
                    current_date, frozenset()
                ):
                    order.status = OrderStatus.REJECTED_INELIGIBLE
                    order.rejection_reason = "not eligible on signal date"
                elif signal.action is SignalAction.ENTRY and signal.ticker in positions:
                    order.status = OrderStatus.REJECTED_POSITION_EXISTS
                    order.rejection_reason = "position already exists"
                elif signal.action is SignalAction.EXIT and signal.ticker not in positions:
                    order.status = OrderStatus.REJECTED_NO_POSITION
                    order.rejection_reason = "no open position"
                else:
                    pending.append(order)

            last_closes.update({ticker: item.close for ticker, item in daily_bars.items()})
            market_value = sum(
                position.quantity * last_closes[position.ticker]
                for position in positions.values()
                if position.ticker in last_closes
            )
            equity_curve.append(EquityPoint(current_date, cash, market_value, cash + market_value))

        for order in pending:
            order.status = OrderStatus.UNFILLED
            order.rejection_reason = "no later bar"

        ending_equity = equity_curve[-1].equity if equity_curve else cash
        return SimulationResult(
            orders=tuple(orders),
            trades=tuple(trades),
            positions=tuple(sorted(positions.values(), key=lambda item: item.ticker)),
            equity_curve=tuple(equity_curve),
            ending_cash=cash,
            ending_equity=ending_equity,
        )

    def _execute_entry(
        self,
        order: Order,
        item: Bar,
        membership: Mapping[date, frozenset[str]],
        cash: float,
        positions: dict[str, Position],
        trades: list[Trade],
        open_trade_indexes: dict[str, int],
    ) -> float:
        if order.ticker not in membership.get(item.date, frozenset()):
            order.status = OrderStatus.REJECTED_INELIGIBLE
            order.rejection_reason = "not eligible on execution date"
            return cash
        if order.trigger_price is not None and item.high < order.trigger_price:
            order.status = OrderStatus.UNFILLED
            order.execution_date = item.date
            order.rejection_reason = "trigger not reached"
            return cash
        base_price = max(item.open, order.trigger_price or item.open)
        fill_price = base_price * (1 + self.config.slippage_bps / 10_000)
        quantity = float(order.quantity)
        commission = fill_price * quantity * self.config.commission_bps / 10_000
        total = fill_price * quantity + commission
        if total > cash + 1e-10:
            order.status = OrderStatus.REJECTED_CASH
            order.rejection_reason = "insufficient cash"
            return cash
        position = Position(order.ticker, quantity, item.date, fill_price, commission)
        positions[order.ticker] = position
        trades.append(Trade(order.ticker, quantity, item.date, fill_price, commission))
        open_trade_indexes[order.ticker] = len(trades) - 1
        order.status = OrderStatus.FILLED
        order.execution_date = item.date
        order.fill_price = fill_price
        return cash - total

    def _execute_exit(
        self,
        order: Order,
        item: Bar,
        cash: float,
        positions: dict[str, Position],
        trades: list[Trade],
        open_trade_indexes: dict[str, int],
    ) -> float:
        position = positions.get(order.ticker)
        if position is None:
            order.status = OrderStatus.REJECTED_NO_POSITION
            order.rejection_reason = "no open position at execution"
            return cash
        fill_price = item.open * (1 - self.config.slippage_bps / 10_000)
        proceeds = fill_price * position.quantity
        commission = proceeds * self.config.commission_bps / 10_000
        gross_price_profit = max(
            (fill_price - position.entry_price) * position.quantity,
            0.0,
        )
        held_days = (item.date - position.entry_date).days
        tax_haircut = (
            gross_price_profit * self.config.short_term_profit_haircut if held_days <= 365 else 0.0
        )
        net_profit = (
            proceeds
            - commission
            - tax_haircut
            - position.entry_price * position.quantity
            - position.entry_commission
        )
        trade_index = open_trade_indexes.pop(order.ticker)
        trades[trade_index] = replace(
            trades[trade_index],
            exit_date=item.date,
            exit_price=fill_price,
            exit_commission=commission,
            tax_haircut=tax_haircut,
            net_profit=net_profit,
        )
        del positions[order.ticker]
        order.status = OrderStatus.FILLED
        order.execution_date = item.date
        order.fill_price = fill_price
        return cash + proceeds - commission - tax_haircut

    @staticmethod
    def _create_order(signal: Signal, sequence: int) -> Order:
        order_id = canonical_id(
            {
                "date": signal.decision_date.isoformat(),
                "ticker": signal.ticker,
                "action": signal.action.value,
                "quantity": signal.quantity,
                "trigger": signal.trigger_price,
                "sequence": sequence,
            },
            "ord_",
        )
        return Order(
            order_id,
            signal.decision_date,
            signal.ticker,
            signal.action,
            signal.quantity,
            signal.trigger_price,
        )

    @staticmethod
    def _validate(bars: list[Bar], signals: list[Signal]) -> None:
        keys = [(item.ticker, item.date) for item in bars]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate ticker-date bars are not allowed")
        signal_keys = [(item.ticker, item.decision_date) for item in signals]
        if len(signal_keys) != len(set(signal_keys)):
            raise ValueError("conflicting same-day signals are not allowed")
        bar_dates = {item.date for item in bars}
        missing_dates = {item.decision_date for item in signals} - bar_dates
        if missing_dates:
            raise ValueError("signal decision dates must be completed market sessions")
