"""Typed contracts for the reference simulator."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class SignalAction(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"


class OrderStatus(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    UNFILLED = "unfilled"
    REJECTED_INELIGIBLE = "rejected_ineligible"
    REJECTED_NO_POSITION = "rejected_no_position"
    REJECTED_CASH = "rejected_cash"
    REJECTED_POSITION_EXISTS = "rejected_position_exists"


@dataclass(frozen=True, slots=True)
class Bar:
    ticker: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        prices = (self.open, self.high, self.low, self.close)
        if not self.ticker.strip() or not all(
            math.isfinite(value) and value > 0 for value in prices
        ):
            raise ValueError("Bar ticker and prices must be valid and positive")
        tolerance = 1e-10
        if self.high + tolerance < max(self.open, self.low, self.close):
            raise ValueError("Bar high violates OHLC relationship")
        if self.low - tolerance > min(self.open, self.high, self.close):
            raise ValueError("Bar low violates OHLC relationship")
        if not math.isfinite(self.volume) or self.volume < 0:
            raise ValueError("Bar volume must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class Signal:
    decision_date: date
    ticker: str
    action: SignalAction
    quantity: float | None = None
    trigger_price: float | None = None

    def __post_init__(self) -> None:
        if not self.ticker.strip():
            raise ValueError("Signal ticker cannot be empty")
        if self.action is SignalAction.ENTRY:
            if self.quantity is None or not math.isfinite(self.quantity) or self.quantity <= 0:
                raise ValueError("Entry signal requires a positive finite quantity")
        if self.trigger_price is not None and (
            not math.isfinite(self.trigger_price) or self.trigger_price <= 0
        ):
            raise ValueError("Trigger price must be positive and finite")
        if self.action is SignalAction.EXIT and self.trigger_price is not None:
            raise ValueError("Reference exit signals do not accept a trigger price")


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    initial_cash: float = 100_000.0
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    short_term_profit_haircut: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive and finite")
        if not 0 <= self.commission_bps <= 1_000:
            raise ValueError("commission_bps must be between 0 and 1000")
        if not 0 <= self.slippage_bps <= 1_000:
            raise ValueError("slippage_bps must be between 0 and 1000")
        if not 0 <= self.short_term_profit_haircut <= 1:
            raise ValueError("short_term_profit_haircut must be between zero and one")


@dataclass(slots=True)
class Order:
    order_id: str
    signal_date: date
    ticker: str
    action: SignalAction
    quantity: float | None
    trigger_price: float | None
    status: OrderStatus = OrderStatus.PENDING
    execution_date: date | None = None
    fill_price: float | None = None
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Trade:
    ticker: str
    quantity: float
    entry_date: date
    entry_price: float
    entry_commission: float
    exit_date: date | None = None
    exit_price: float | None = None
    exit_commission: float = 0.0
    tax_haircut: float = 0.0
    net_profit: float = 0.0


@dataclass(frozen=True, slots=True)
class Position:
    ticker: str
    quantity: float
    entry_date: date
    entry_price: float
    entry_commission: float


@dataclass(frozen=True, slots=True)
class EquityPoint:
    date: date
    cash: float
    market_value: float
    equity: float


@dataclass(frozen=True, slots=True)
class SimulationResult:
    orders: tuple[Order, ...]
    trades: tuple[Trade, ...]
    positions: tuple[Position, ...]
    equity_curve: tuple[EquityPoint, ...]
    ending_cash: float
    ending_equity: float
